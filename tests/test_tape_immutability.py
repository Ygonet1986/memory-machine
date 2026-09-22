"""N9 conformance: content immutability vs administrative status.

The frozen tape is append-only at the **content** level: a record's factual
fields (id/type/summary/why/files/source/derived_from/created_at/trilepsia)
never change once written. Administrative operations may rewrite the file to
change `status` or to delete a record, and corrections are new records — this
test proves the content survives those operations byte-for-byte.
"""

from __future__ import annotations

import json

from memory_machine.tape import MemoryRecord, Tape

FACTUAL_FIELDS = (
    "id", "type", "summary", "why", "files", "created_at", "source",
    "derived_from", "views", "trilepsia",
)


def _content(record: MemoryRecord) -> dict:
    data = record.to_dict()
    return {key: data.get(key) for key in FACTUAL_FIELDS}


def test_status_change_preserves_every_factual_field(tmp_path):
    tape = Tape(tmp_path / "tape.jsonl")
    first = tape.append(MemoryRecord(type="decision", summary="use Postgres", why="ACID"))
    second = tape.append(MemoryRecord(type="lesson", summary="avoid global locks"))
    before_first, before_second = _content(first), _content(second)

    assert tape.set_status(first.id, "superseded")
    reloaded = {r.id: r for r in tape.read()}
    assert reloaded[first.id].status == "superseded"
    assert _content(reloaded[first.id]) == before_first
    assert _content(reloaded[second.id]) == before_second


def test_correction_is_a_new_record_and_old_content_is_intact(tmp_path):
    tape = Tape(tmp_path / "tape.jsonl")
    original = tape.append(MemoryRecord(type="decision", summary="use MySQL"))
    before = _content(original)
    correction = tape.append(
        MemoryRecord(type="decision", summary="use Postgres",
                     why="supersedes the MySQL decision", derived_from=[original.id])
    )
    assert correction.id != original.id
    reloaded = {r.id: r for r in tape.read()}
    assert _content(reloaded[original.id]) == before
    assert reloaded[correction.id].derived_from == [original.id]


def test_delete_removes_only_the_target_and_preserves_others(tmp_path):
    tape = Tape(tmp_path / "tape.jsonl")
    keep = tape.append(MemoryRecord(type="lesson", summary="keep me"))
    drop = tape.append(MemoryRecord(type="lesson", summary="drop me"))
    before = _content(keep)

    assert tape.delete(drop.id) is True
    remaining = tape.read()
    assert [r.id for r in remaining] == [keep.id]
    assert _content(remaining[0]) == before


def test_reload_from_disk_keeps_written_bytes_unchanged(tmp_path):
    path = tmp_path / "tape.jsonl"
    tape = Tape(path)
    record = tape.append(MemoryRecord(type="preference", summary="vim keybindings"))
    line_before = path.read_text(encoding="utf-8").strip()
    reread_line = json.dumps(tape.read()[0].to_dict(), ensure_ascii=False)
    assert reread_line == line_before
    assert record.id in reread_line
