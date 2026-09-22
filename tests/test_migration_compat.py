"""Migration/backward-compat conformance.

Covers the "migração e compatibilidade" rows of the conformance matrix:
old tape lines without the newer fields load, unknown keys are ignored,
switching modes is read-only on the tape, and the views index is a
reproducible projection of the tape tags.
"""

from __future__ import annotations

import json

from memory_machine.config import Config
from memory_machine.coordinator import Machine
from memory_machine.tape import MemoryRecord, Tape
from memory_machine.views import build_index

from fakes import FakeClient

AGENT_JSON = (
    '{"digest":"d","checklist":[],"annotations":'
    '[{"memory_id":"M0001","note":"router note","relevance":0.9}],'
    '"coverage":"complete"}'
)


def _client() -> FakeClient:
    return FakeClient(lambda messages, temperature: AGENT_JSON)


def test_old_tape_line_without_new_fields_loads(tmp_path):
    path = tmp_path / "tape.jsonl"
    path.write_text(
        json.dumps({
            "id": "M0001", "type": "decision", "summary": "use Postgres",
            "why": "ACID", "files": [], "created_at": "2026-01-01T00:00:00+00:00",
            "status": "active", "source": "",
        }) + "\n",
        encoding="utf-8",
    )
    record = Tape(path).read()[0]
    assert record.summary == "use Postgres"
    assert record.source_span == ()
    assert record.source_document == ""
    assert record.trilepsia == {}
    assert record.views == []  # legacy rows carry no tags; retagging is the path


def test_unknown_fields_and_broken_lines_are_tolerated(tmp_path):
    path = tmp_path / "tape.jsonl"
    path.write_text(
        json.dumps({"id": "M0001", "type": "lesson", "summary": "ok",
                    "future_field": {"nested": True}}) + "\n"
        + "{not json}\n",
        encoding="utf-8",
    )
    records = Tape(path).read()
    assert [r.id for r in records] == ["M0001"]


def test_mode_switch_is_read_only_on_the_tape(tmp_path):
    tape = Tape(tmp_path / "tape.jsonl")
    tape.append(MemoryRecord(type="decision", summary="use Postgres",
                             views=["topic/db"]))
    tape.append(MemoryRecord(type="lesson", summary="avoid global locks",
                             views=["topic/db"]))
    before = (tmp_path / "tape.jsonl").read_bytes()

    group = Machine(tmp_path, config=Config(capacity=10), client=_client())
    group.whiteboard.subject = "database decision"
    group.recall("which database?")
    assert (tmp_path / "tape.jsonl").read_bytes() == before

    view = Machine(
        tmp_path,
        config=Config(capacity=10, agent_mode="view",
                      view_router_mode="lexical", whiteboard_mode="dimension",
                      attention_mode="state"),
        client=_client(),
    )
    view.whiteboard.subject = "database decision"
    view.recall("which database?")
    assert (tmp_path / "tape.jsonl").read_bytes() == before


def test_views_index_is_a_reproducible_projection(tmp_path):
    tape = Tape(tmp_path / "tape.jsonl")
    tape.append(MemoryRecord(type="decision", summary="a", views=["topic/db"]))
    tape.append(MemoryRecord(type="lesson", summary="b", views=["topic/db", "subject/x"]))
    first = build_index(tape)
    second = build_index(tape)
    assert first == second
    assert first["topic/db"] == ["M0001", "M0002"]
    assert first["subject/x"] == ["M0002"]
