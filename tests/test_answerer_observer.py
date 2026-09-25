"""Two conversation agents: observer (understanding + guidance) + answerer."""

from __future__ import annotations

import json

from fakes import FakeClient
from memory_machine.config import Config
from memory_machine.context import Turn
from memory_machine.coordinator import Machine
from memory_machine.groups import ensure_group
from memory_machine.main_chatbot import (
    main_user_prompt, observer_pass, run_main_chatbot,
)
from memory_machine.tape import MemoryRecord
from memory_machine.whiteboard import Whiteboard


def test_observer_pass_parses_understanding_and_guidance():
    payload = json.dumps({"understanding": "discutindo o orçamento",
                          "guidance": ["confirme o valor", "cite a decisão"]})
    client = FakeClient(lambda messages, temperature: payload)
    understanding, guidance = observer_pass(
        client, Whiteboard(subject="s"), "Pessoa: oi", "quanto?",
        previous_understanding="anterior")
    assert understanding == "discutindo o orçamento"
    assert guidance == ["confirme o valor", "cite a decisão"]
    assert len(client.calls) == 1


def test_observer_pass_keeps_previous_on_bad_output():
    client = FakeClient(lambda messages, temperature: "sem json")
    understanding, guidance = observer_pass(
        client, Whiteboard(subject="s"), "", "t",
        previous_understanding="anterior")
    assert understanding == "anterior"
    assert guidance == []


def test_answerer_prompt_includes_observer_guidance():
    board = Whiteboard(subject="s")
    prompt = main_user_prompt(board, "task", observer_guidance="- cite a decisão")
    assert "## Observador da conversa" in prompt
    assert "- cite a decisão" in prompt
    plain = main_user_prompt(board, "task")
    assert "## Observador da conversa" not in plain


def _machine_with_observer(tmp_path, enabled: bool):
    calls: list[str] = []
    seen: dict[str, str] = {}

    def handler(messages, temperature):
        system = next(m["content"] for m in messages if m["role"] == "system")
        calls.append(system[:40])
        if system.startswith("You are a memory agent"):
            return '{"annotations":[]}'
        if system.startswith("You are the conversation observer"):
            seen["observer_user"] = next(
                m["content"] for m in messages if m["role"] == "user")
            return json.dumps({"understanding": "estado observado",
                               "guidance": ["confirme a dedicatória"]})
        if system.startswith("You are the main assistant"):
            seen["answerer_user"] = next(
                m["content"] for m in messages if m["role"] == "user")
            return "resposta"
        return "ok"

    machine = Machine(tmp_path, config=Config(answerer_observer=enabled),
                      client=FakeClient(handler))
    machine.tape.append(MemoryRecord(id="M0001", type="decision",
                                     summary="Adopt Postgres"))
    machine.manifest, _g, _a, _ = ensure_group(machine.manifest, 1)
    machine.context.turns.append(Turn(task="pergunta", reply="resposta"))
    machine.context.understanding = "anterior"
    return machine, calls, seen


def test_observer_guides_the_answerer_and_persists_understanding(tmp_path):
    machine, calls, seen = _machine_with_observer(tmp_path, True)
    machine.run("pergunta nova?")

    assert any(call.startswith("You are the conversation observer")
               for call in calls)
    assert machine.context.understanding == "estado observado"
    assert "anterior" in seen["observer_user"]
    assert "## Observador da conversa" in seen["answerer_user"]
    assert "confirme a dedicatória" in seen["answerer_user"]

    machine.save()
    reloaded = Machine(tmp_path)
    assert reloaded.context.understanding == "estado observado"


def test_observer_can_be_disabled(tmp_path):
    machine, calls, seen = _machine_with_observer(tmp_path, False)
    machine.run("pergunta nova?")

    assert not any(call.startswith("You are the conversation observer")
                   for call in calls)
    assert "## Observador da conversa" not in seen["answerer_user"]
    assert machine.context.understanding == "anterior"
    assert run_main_chatbot  # keep import used
