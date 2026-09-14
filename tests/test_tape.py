import json

import pytest

from memory_machine.tape import (
    MemoryRecord,
    Tape,
    format_id,
    parse_id,
    PROJECT_TYPES,
)


def test_format_and_parse_id():
    assert format_id(1) == "M0001"
    assert format_id(42) == "M0042"
    assert parse_id("M0042") == 42
    with pytest.raises(ValueError):
        parse_id("42")


def test_append_assigns_stable_id(tmp_path):
    tape = Tape(tmp_path / "tape.jsonl")
    r1 = tape.append(MemoryRecord(type="decision", summary="Adopt Postgres"))
    r2 = tape.append(MemoryRecord(type="lesson", summary="Use pooled connections"))
    assert r1.id == "M0001"
    assert r2.id == "M0002"
    assert len(tape) == 2


def test_read_and_range(tmp_path):
    tape = Tape(tmp_path / "tape.jsonl")
    for i in range(10):
        tape.append(MemoryRecord(type="decision", summary=f"Decision {i}"))
    assert len(tape.read()) == 10
    assert [r.id for r in tape.read_range(4, 6)] == ["M0004", "M0005", "M0006"]


def test_append_is_append_only(tmp_path):
    tape = Tape(tmp_path / "tape.jsonl")
    r = tape.append(MemoryRecord(type="decision", summary="A"))
    original_id = r.id
    # Records are immutable: re-appending never mutates the existing line.
    tape.append(MemoryRecord(type="decision", summary="B"))
    first = tape.read()[0]
    assert first.id == original_id
    assert first.summary == "A"


def test_text_representation():
    r = MemoryRecord(
        id="M0001",
        type="decision",
        summary="Adopt Postgres",
        why="ACID + JSONB",
        files=["db/schema.sql"],
    )
    assert r.text().startswith("[M0001] [decision] Adopt Postgres")


def test_project_types():
    assert {"decision", "lesson", "preference", "bugfix", "build"} == PROJECT_TYPES


def test_delete_record(tmp_path):
    tape = Tape(tmp_path / "tape.jsonl")
    tape.append(MemoryRecord(type="decision", summary="A"))
    tape.append(MemoryRecord(type="decision", summary="B"))
    assert tape.delete("M0001") is True
    assert [r.id for r in tape.read()] == ["M0002"]
    assert tape.delete("M0001") is False


def test_set_status(tmp_path):
    tape = Tape(tmp_path / "tape.jsonl")
    tape.append(MemoryRecord(type="decision", summary="A"))
    assert tape.set_status("M0001", "archived") is True
    assert tape.read()[0].status == "archived"
    assert tape.set_status("nope", "archived") is False


def test_status_default_active(tmp_path):
    tape = Tape(tmp_path / "tape.jsonl")
    tape.append(MemoryRecord(type="decision", summary="A"))
    assert tape.read()[0].status == "active"


def test_source_fields_absent_by_default():
    rec = MemoryRecord(type="decision", summary="A")
    d = rec.to_dict()
    assert "source_document" not in d
    assert "source_span" not in d


def test_source_fields_round_trip():
    rec = MemoryRecord(
        type="attachment",
        summary="chunk",
        why="body",
        source="manual.txt#abc123",
        source_span=(1800, 2300),
        source_document="manual.txt#abc123",
    )
    restored = MemoryRecord.from_dict(rec.to_dict())
    assert restored == rec
    assert restored.to_dict()["source_span"] == [1800, 2300]
    assert restored.to_dict()["source_document"] == "manual.txt#abc123"


def test_old_line_stays_byte_equivalent_invariance(tmp_path):
    old = (
        '{"id":"M0001","type":"decision","summary":"A","why":"","files":[],'
        '"created_at":"2000-01-01T00:00:00+00:00","status":"active","source":"",'
        '"derived_from":[],"views":[]}\n'
    )
    p = tmp_path / "tape.jsonl"
    p.write_text(old, encoding="utf-8")
    tape = Tape(p)
    raw = p.read_text(encoding="utf-8")
    record = tape.read()[0]
    assert record.to_dict() == {
        "id": "M0001",
        "type": "decision",
        "summary": "A",
        "why": "",
        "files": [],
        "created_at": "2000-01-01T00:00:00+00:00",
        "status": "active",
        "source": "",
        "derived_from": [],
        "views": [],
    }
    assert json.dumps(record.to_dict(), sort_keys=True) == json.dumps(
        json.loads(raw), sort_keys=True
    )
