import pytest

from memory_machine.agents import (
    agent_system_prompt,
    agent_user_prompt,
    parse_annotations,
    run_agents,
)
from memory_machine.groups import Agent, Group, Manifest, ensure_group
from memory_machine.tape import MemoryRecord, Tape
from memory_machine.whiteboard import Whiteboard

from fakes import FakeClient, text


def _ann_sys(memory_id, note, relevance=0.9):
    return f'{{"annotations":[{{"memory_id":"{memory_id}","note":"{note}","relevance":{relevance}}}]}}'


def test_parse_annotations():
    anns = parse_annotations(_ann_sys("M0001", "relevant"), agent_id="A1")
    assert len(anns) == 1
    assert anns[0].memory_id == "M0001"
    assert anns[0].agent_id == "A1"
    assert anns[0].relevance == 0.9


def test_parse_annotations_clamps_relevance():
    anns = parse_annotations(_ann_sys("M0001", "x", 5.0))
    assert anns[0].relevance == 1.0


def test_parse_annotations_empty():
    assert parse_annotations('{"annotations":[]}') == []


def test_parse_annotations_skips_invalid():
    assert parse_annotations('{"annotations":[{"note":"no id"}]}') == []


def test_agent_system_prompt_embeds_group_records():
    records = [MemoryRecord(id="M0001", type="decision", summary="Adopt Postgres")]
    agent = Agent(id="A1", group_id="G1")
    group = Group(id="G1", start=1, end=10, agent_id="A1")
    prompt = agent_system_prompt(agent, group, records)
    assert "A1" in prompt
    assert "M0001" in prompt
    assert "Adopt Postgres" in prompt


def test_agent_user_prompt_includes_whiteboard_subject():
    wb = Whiteboard(subject="refactor auth", objective="migrate tokens")
    prompt = agent_user_prompt(wb)
    assert "refactor auth" in prompt
    assert "migrate tokens" in prompt


def _two_group_tape(tmp_path):
    tape = Tape(tmp_path / "tape.jsonl")
    manifest = Manifest(capacity=3)
    for i in range(5):
        tape.append(MemoryRecord(id=f"M{i+1:04d}", type="decision", summary=f"Decision {i+1}"))
    manifest, _, _, _ = ensure_group(manifest, 1)
    manifest, _, _, _ = ensure_group(manifest, 4)
    return tape, manifest


def test_run_agents_dispatches_all_agents(tmp_path):
    tape, manifest = _two_group_tape(tmp_path)
    wb = Whiteboard(subject="db migration")

    def handler(messages, temperature):
        sys_text = text(messages, "system")
        if "A1" in sys_text:
            return _ann_sys("M0001", "from A1")
        if "A2" in sys_text:
            return '{"annotations":[]}'
        raise AssertionError("unexpected call")

    client = FakeClient(handler)
    anns = run_agents(tape, manifest, wb, client)
    assert len(client.calls) == 2  # every agent reads the whiteboard
    assert [a.memory_id for a in anns] == ["M0001"]
    assert anns[0].agent_id == "A1"


def test_run_agents_empty_annotations_are_valid(tmp_path):
    tape, manifest = _two_group_tape(tmp_path)
    wb = Whiteboard(subject="unrelated")

    def handler(messages, temperature):
        return '{"annotations":[]}'

    client = FakeClient(handler)
    anns = run_agents(tape, manifest, wb, client)
    assert anns == []
    assert len(client.calls) == 2


def test_run_agents_skip_on_error(tmp_path):
    tape, manifest = _two_group_tape(tmp_path)
    wb = Whiteboard(subject="x")

    def handler(messages, temperature):
        sys_text = text(messages, "system")
        if "A1" in sys_text:
            return _ann_sys("M0001", "ok")
        raise RuntimeError("agent down")

    client = FakeClient(handler)
    anns = run_agents(tape, manifest, wb, client, on_error="skip")
    assert [a.memory_id for a in anns] == ["M0001"]


def test_run_agents_raise_on_error(tmp_path):
    tape, manifest = _two_group_tape(tmp_path)
    wb = Whiteboard(subject="x")

    def handler(messages, temperature):
        raise RuntimeError("agent down")

    client = FakeClient(handler)
    with pytest.raises(RuntimeError):
        run_agents(tape, manifest, wb, client, on_error="raise")


# ------------------------------------------------------------- checklist

def test_agent_system_prompt_includes_checklist():
    agent = Agent(id="A1", group_id="G1", checklist="- remember Postgres")
    group = Group(id="G1", start=1, end=10, agent_id="A1")
    records = [MemoryRecord(id="M0001", type="decision", summary="Use Postgres")]
    prompt = agent_system_prompt(agent, group, records)
    assert "must NOT forget to remind" in prompt
    assert "- remember Postgres" in prompt


def test_run_agents_fuses_checklist_and_annotations(tmp_path):
    tape = Tape(tmp_path / "tape.jsonl")
    manifest = Manifest(capacity=10)
    tape.append(MemoryRecord(id="M0001", type="decision", summary="Use Postgres"))
    manifest, _g, a1, _ = ensure_group(manifest, 1)
    wb = Whiteboard(subject="db migration")

    def handler(messages, temperature):
        return '{"checklist":["remember Postgres is settled"],"annotations":[{"memory_id":"M0001","note":"db choice","relevance":0.9}]}'

    client = FakeClient(handler)
    anns = run_agents(tape, manifest, wb, client)

    assert len(anns) == 1
    assert anns[0].memory_id == "M0001"
    # Checklist updated in the same call (fused).
    assert a1.checklist == "- remember Postgres is settled"
    assert a1.checklist_records == 1
    # Only ONE LLM call per agent (no separate checklist call).
    assert len(client.calls) == 1


def test_run_agents_checklist_falls_back_to_deterministic(tmp_path):
    tape = Tape(tmp_path / "tape.jsonl")
    manifest = Manifest(capacity=10)
    tape.append(MemoryRecord(id="M0001", type="decision", summary="Use Postgres"))
    manifest, _g, a1, _ = ensure_group(manifest, 1)
    wb = Whiteboard(subject="x")

    # No checklist key in response -> deterministic fallback from records.
    client = FakeClient(lambda messages, temperature: '{"annotations":[]}')
    run_agents(tape, manifest, wb, client)
    assert a1.checklist == "- Use Postgres"


def test_run_agents_skips_empty_groups(tmp_path):
    tape = Tape(tmp_path / "tape.jsonl")
    manifest = Manifest(capacity=10)
    manifest, _g, a1, _ = ensure_group(manifest, 1)
    wb = Whiteboard(subject="x")
    client = FakeClient(lambda messages, temperature: "unexpected")
    anns = run_agents(tape, manifest, wb, client)
    assert anns == []
    assert len(client.calls) == 0
