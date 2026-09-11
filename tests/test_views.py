from memory_machine.agents import run_agents
from memory_machine.groups import Manifest, ensure_group
from memory_machine.tape import MemoryRecord, Tape
from memory_machine.views import (
    build_index,
    ids_in_views,
    list_views,
    rank_views,
    records_in_views,
)
from memory_machine.whiteboard import Whiteboard

from fakes import FakeClient


def test_default_views_assigned(tmp_path):
    tape = Tape(tmp_path / "tape.jsonl")
    tape.append(MemoryRecord(type="decision", summary="Use Postgres"))
    rec = tape.read()[0]
    assert any(v.startswith("time/") for v in rec.views)
    assert "type/decision" in rec.views


def test_source_view(tmp_path):
    tape = Tape(tmp_path / "tape.jsonl")
    tape.append(MemoryRecord(type="attachment", summary="chunk", source="spec.txt#abc"))
    assert "source/spec.txt" in tape.read()[0].views


def test_explicit_views_preserved(tmp_path):
    tape = Tape(tmp_path / "tape.jsonl")
    tape.append(MemoryRecord(type="decision", summary="x", views=["topic/router"]))
    assert "topic/router" in tape.read()[0].views


def test_build_index_and_list(tmp_path):
    tape = Tape(tmp_path / "tape.jsonl")
    tape.append(MemoryRecord(type="decision", summary="a"))
    tape.append(MemoryRecord(type="lesson", summary="b"))
    index = build_index(tape)
    assert index["type/decision"] == ["M0001"]
    assert index["type/lesson"] == ["M0002"]
    views = {v["view"]: v["count"] for v in list_views(tape)}
    assert views["type/decision"] == 1


def test_rank_views(tmp_path):
    tape = Tape(tmp_path / "tape.jsonl")
    tape.append(MemoryRecord(type="decision", summary="Use PostgreSQL database"))
    tape.append(MemoryRecord(type="preference", summary="Compose bossa nova guitar"))
    hits = rank_views(tape, "which database should we use")
    assert hits


def test_records_in_views(tmp_path):
    tape = Tape(tmp_path / "tape.jsonl")
    tape.append(MemoryRecord(type="decision", summary="a"))
    tape.append(MemoryRecord(type="lesson", summary="b"))
    assert [r.id for r in records_in_views(tape, ["type/decision"])] == ["M0001"]
    assert ids_in_views(tape, ["type/lesson"]) == {"M0002"}


def test_run_agents_views_filter(tmp_path):
    tape = Tape(tmp_path / "tape.jsonl")
    manifest = Manifest(capacity=10)
    tape.append(
        MemoryRecord(id="M0001", type="decision", summary="Use Postgres", views=["topic/db"])
    )
    tape.append(
        MemoryRecord(id="M0002", type="preference", summary="Bossa nova", views=["topic/music"])
    )
    manifest, _g, _a1, _ = ensure_group(manifest, 1)
    wb = Whiteboard(subject="x")
    seen: dict[str, str] = {}

    def handler(messages, temperature):
        seen["sys"] = "\n".join(
            m.get("content", "") for m in messages if m.get("role") == "system"
        )
        return '{"digest":"d","checklist":[],"annotations":[]}'

    run_agents(tape, manifest, wb, FakeClient(handler), views_filter={"topic/db"})
    assert "M0001" in seen["sys"]
    assert "M0002" not in seen["sys"]
