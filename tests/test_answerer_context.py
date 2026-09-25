"""Answerer context rule: whole whiteboard + last 10 messages under one budget."""

from __future__ import annotations

from fakes import FakeClient
from memory_machine.config import Config
from memory_machine.context import (
    ANSWERER_WHITEBOARD_FLOOR, ChatContext, Turn, split_answerer_budget,
)
from memory_machine.coordinator import Machine
from memory_machine.groups import ensure_group
from memory_machine.main_chatbot import MAIN_SYSTEM_PROMPT, main_user_prompt
from memory_machine.tape import MemoryRecord
from memory_machine.whiteboard import Whiteboard


def _context(turns: int = 12) -> ChatContext:
    context = ChatContext(summary="resumo consolidado")
    for index in range(turns):
        context.turns.append(Turn(task=f"pergunta {index + 1}",
                                  reply=f"resposta {index + 1}"))
    return context


def test_split_gives_history_priority_and_a_whiteboard_floor():
    assert split_answerer_budget(4000, 0) == (3200, 4000)
    assert split_answerer_budget(4000, 1500) == (3200, 2500)
    assert split_answerer_budget(4000, 3900) == (3200, 800)
    assert split_answerer_budget(500, 0) == (0, 500)
    assert split_answerer_budget(500, 400) == (0, 500)
    assert split_answerer_budget(0, 10) == (0, 0)
    assert split_answerer_budget(100, 50, floor=40) == (60, 50)


def test_render_recent_keeps_summary_and_last_turns_only():
    context = _context()
    block = context.render_recent(10)
    assert block.startswith("## Prior context (consolidated)\nresumo consolidado")
    assert "pergunta 3" in block
    assert "pergunta 2" not in block
    assert "resposta 12" in block
    assert context.render_recent(0) == ""


def test_render_recent_caps_each_side_and_total():
    context = ChatContext()
    context.turns.append(Turn(task="a" * 900, reply="b" * 900))
    block = context.render_recent(10, turn_cap=100)
    assert len(block.splitlines()[0]) <= 100 + len("Task: ")
    tail = context.render_recent(10, turn_cap=900, max_chars=120)
    assert len(tail) <= 120 and tail.startswith("…")


def test_main_user_prompt_budget_trims_the_board_only_when_set():
    board = Whiteboard(subject="s", objective="o")
    board.context = ["c" * 100 for _ in range(30)]
    full = main_user_prompt(board, "task", history="H")
    assert "… (trimmed)" not in full
    assert full.startswith("H\n\n## Whiteboard\n\n")
    trimmed = main_user_prompt(board, "task", history="H",
                               whiteboard_budget=600)
    section = trimmed.split("## Whiteboard\n\n", 1)[1] \
        .split("\n\n## Task", 1)[0]
    assert "… (trimmed)" in section
    assert len(section) <= 600 + len("\n… (trimmed)")


def test_coordinator_uses_the_last_messages_and_bounds_the_board(tmp_path):
    seen: dict[str, str] = {}

    def handler(messages, temperature):
        system = next(m["content"] for m in messages if m["role"] == "system")
        if system.startswith("You are a memory agent"):
            return '{"annotations":[]}'
        if system.startswith("You are the main assistant"):
            seen["user"] = next(m["content"] for m in messages
                                if m["role"] == "user")
            return "resposta do chatbot"
        return "ok"

    machine = Machine(tmp_path, config=Config(
        answerer_history_messages=3, whiteboard_budget=900),
        client=FakeClient(handler))
    machine.tape.append(MemoryRecord(
        id="M0001", type="decision", summary="Adopt Postgres"))
    machine.manifest, _g, _a, _ = ensure_group(machine.manifest, 1)
    for index in range(12):
        machine.context.turns.append(Turn(task=f"pergunta {index + 1}",
                                          reply=f"resposta {index + 1}"))
    machine.whiteboard.subject = "assunto"
    machine.whiteboard.context = ["d" * 200 for _ in range(20)]

    machine.run("qual o estado?")
    user = seen["user"]
    assert "pergunta 10" in user
    assert "pergunta 3" not in user
    board = user.split("## Whiteboard\n\n", 1)[1]
    assert "… (trimmed)" in board
    assert len(board) <= 900
    assert MAIN_SYSTEM_PROMPT
    assert ANSWERER_WHITEBOARD_FLOOR == 800
