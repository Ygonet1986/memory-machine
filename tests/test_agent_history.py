"""Opt-in conversation window for memory agents (off by default)."""

from __future__ import annotations

from memory_machine.agents import agent_user_prompt, run_agents
from memory_machine.config import Config
from memory_machine.coordinator import Machine
from memory_machine.groups import Manifest, ensure_group
from memory_machine.tape import MemoryRecord, Tape
from memory_machine.turns import add_turn_slot, render_recent_turns
from memory_machine.whiteboard import Whiteboard

from fakes import FakeClient


def _slots(tmp_path, pairs: int = 6) -> Tape:
    tape = Tape(tmp_path / "tape.jsonl")
    manifest = Manifest(capacity=50)
    for index in range(pairs):
        question = add_turn_slot(tape, manifest, slot="question",
                                 text=f"pergunta {index + 1}",
                                 message_id=f"q{index + 1}")
        add_turn_slot(tape, manifest, slot="reply",
                      text=f"resposta {index + 1}",
                      message_id=f"r{index + 1}",
                      pair_message_id=f"q{index + 1}")
        assert question["ok"]
    return tape


def test_config_default_is_ten_and_clamps():
    assert Config().agent_history_messages == 10
    config = Config(agent_history_messages=7)
    config.validate()
    assert config.agent_history_messages == 7
    config = Config(agent_history_messages=0)
    config.validate()
    assert config.agent_history_messages == 0
    config = Config(agent_history_messages=999)
    config.validate()
    assert config.agent_history_messages == 50


def test_render_recent_turns_keeps_the_last_and_truncates(tmp_path):
    tape = _slots(tmp_path)
    block = render_recent_turns(tape, 10)
    lines = block.splitlines()
    assert len(lines) == 10
    assert lines[0] == "Pessoa: pergunta 2"
    assert lines[-1] == "Assistente: resposta 6"
    assert lines[2] == "Pessoa: pergunta 3"

    short = render_recent_turns(tape, 2, max_chars=8)
    assert short.splitlines()[-1].endswith("…")
    assert render_recent_turns(tape, 0) == ""
    empty = Tape(tmp_path / "empty.jsonl")
    assert render_recent_turns(empty, 10) == ""


def test_agent_user_prompt_default_is_byte_identical():
    board = Whiteboard(subject="s", objective="o")
    assert agent_user_prompt(board) == \
        "## Whiteboard\n\n" + board.render(include_annotations=False)
    with_history = agent_user_prompt(board, "Pessoa: oi\nAssistente: olá")
    assert with_history.startswith(agent_user_prompt(board))
    assert "## Conversa recente" in with_history
    assert "Pessoa: oi" in with_history


def test_run_agents_receives_history(tmp_path):
    tape = Tape(tmp_path / "tape.jsonl")
    manifest = Manifest(capacity=3)
    for index in range(3):
        tape.append(MemoryRecord(id=f"M{index + 1:04d}", type="decision",
                                 summary=f"Decision {index + 1}"))
    manifest, _group, _agent, _ = ensure_group(manifest, 1)
    seen: list[str] = []

    def handler(messages, temperature):
        seen.append("\n".join(m["content"] for m in messages
                              if m["role"] == "user"))
        return '{"annotations":[]}'

    run_agents(tape, manifest, Whiteboard(subject="s"), FakeClient(handler),
               history="Pessoa: oi\nAssistente: olá")
    assert seen and all("## Conversa recente" in text for text in seen)
    assert all("Pessoa: oi" in text for text in seen)


def test_no_history_no_section(tmp_path):
    tape = Tape(tmp_path / "tape.jsonl")
    manifest = Manifest(capacity=3)
    tape.append(MemoryRecord(id="M0001", type="decision", summary="A"))
    manifest, _group, _agent, _ = ensure_group(manifest, 1)
    seen: list[str] = []

    def handler(messages, temperature):
        seen.append("\n".join(m["content"] for m in messages
                              if m["role"] == "user"))
        return '{"annotations":[]}'

    run_agents(tape, manifest, Whiteboard(subject="s"), FakeClient(handler))
    assert seen and "## Conversa recente" not in seen[0]


def test_machine_history_defaults_on_and_can_be_disabled(tmp_path):
    machine = Machine(tmp_path)
    assert machine._agent_history() == ""
    add_turn_slot(machine.tape, machine.manifest, slot="question",
                  text="pergunta", message_id="q1")
    add_turn_slot(machine.tape, machine.manifest, slot="reply",
                  text="resposta", message_id="r1", pair_message_id="q1")
    block = machine._agent_history()
    assert "Pessoa: pergunta" in block
    assert "Assistente: resposta" in block

    disabled = Machine(tmp_path, config=Config(agent_history_messages=0))
    assert disabled._agent_history() == ""
