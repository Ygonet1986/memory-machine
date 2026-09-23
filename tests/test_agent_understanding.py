"""Per-agent dynamic understanding: prompt slot, persistence, manifest."""

from __future__ import annotations

from memory_machine.agents import agent_system_prompt, run_agents
from memory_machine.groups import Agent, Manifest, ensure_group
from memory_machine.tape import MemoryRecord, Tape
from memory_machine.whiteboard import Whiteboard

from fakes import FakeClient


def _tape_with_group(tmp_path):
    tape = Tape(tmp_path / "tape.jsonl")
    manifest = Manifest(capacity=3)
    for i in range(3):
        tape.append(MemoryRecord(id=f"M{i+1:04d}", type="decision",
                                 summary=f"Decision {i+1}"))
    manifest, group, agent, _ = ensure_group(manifest, 1)
    return tape, manifest, group, agent


def test_prompt_has_dynamic_understanding_slot(tmp_path):
    _tape, _manifest, group, agent = _tape_with_group(tmp_path)
    records = [MemoryRecord(id="M0001", type="decision",
                            summary="Adopt Postgres")]
    empty = agent_system_prompt(agent, group, records)
    assert "Your current understanding of what these memories are" in empty
    assert "(none yet - write the first one)" in empty
    agent.understanding = "records about the admission window decisions"
    filled = agent_system_prompt(agent, group, records)
    assert "records about the admission window decisions" in filled
    assert "(none yet - write the first one)" not in filled


def test_prompt_asks_for_understanding_field(tmp_path):
    _tape, _manifest, group, agent = _tape_with_group(tmp_path)
    with_checklist = agent_system_prompt(agent, group, [])
    without = agent_system_prompt(agent, group, [], include_checklist=False)
    assert '"understanding"' in with_checklist
    assert "Do five things" in with_checklist
    assert '"understanding"' in without
    assert "Do four things" in without


def test_run_agents_persists_understanding(tmp_path):
    tape, manifest, _group, _agent = _tape_with_group(tmp_path)
    wb = Whiteboard(subject="db migration")

    def handler(messages, temperature):
        return ('{"understanding":"these are the db adoption decisions",'
                '"digest":"db decisions","annotations":[]}')

    run_agents(tape, manifest, wb, FakeClient(handler))
    agent = manifest.agents[0]
    assert agent.understanding == "these are the db adoption decisions"
    assert agent.understanding_records == 3


def test_understanding_kept_when_model_omits_it(tmp_path):
    tape, manifest, _group, _agent = _tape_with_group(tmp_path)
    wb = Whiteboard(subject="db migration")
    manifest.agents[0].understanding = "previous understanding"
    manifest.agents[0].understanding_records = 1

    def handler(messages, temperature):
        return '{"digest":"db decisions","annotations":[]}'

    run_agents(tape, manifest, wb, FakeClient(handler))
    agent = manifest.agents[0]
    assert agent.understanding == "previous understanding"
    assert agent.understanding_records == 1


def test_manifest_roundtrip_preserves_understanding(tmp_path):
    manifest = Manifest(capacity=3)
    manifest.agents.append(Agent(id="A1", group_id="G1",
                                 understanding="what these memories are",
                                 understanding_records=7))
    path = tmp_path / "manifest.json"
    from memory_machine.groups import load_manifest, save_manifest

    save_manifest(manifest, path)
    loaded = load_manifest(path)
    assert loaded.agents[0].understanding == "what these memories are"
    assert loaded.agents[0].understanding_records == 7


def test_agent_prompt_still_embeds_records(tmp_path):
    _tape, _manifest, group, agent = _tape_with_group(tmp_path)
    prompt = agent_system_prompt(agent, group, [])
    assert "(no memories in this group)" in prompt
