import json
from pathlib import Path

from memory_machine.attachments import ingest_attachment, remove_attachments
from memory_machine.config import Config
from memory_machine.coordinator import Machine
from memory_machine.groups import Manifest
from memory_machine.tape import MemoryRecord, Tape

from fakes import FakeClient


def test_ingest_creates_labeled_chunks(tmp_path):
    tape = Tape(tmp_path / "tape.jsonl")
    manifest = Manifest(capacity=50)
    src = tmp_path / "spec.txt"
    src.write_text("A" * 1500)
    res = ingest_attachment(tape, manifest, src, chunk_size=600)

    assert res["ok"] is True
    assert res["chunks"] == 3
    assert res["saved"] == 3
    records = tape.read()
    assert all(r.type == "attachment" for r in records)
    assert records[0].summary == 'Attached text "spec.txt" — chunk 1/3'
    assert records[0].source.startswith("spec.txt#")


def test_ingest_records_byte_equivalent_without_new_fields(tmp_path):
    tape = Tape(tmp_path / "tape.jsonl")
    manifest = Manifest(capacity=50)
    src = tmp_path / "spec.txt"
    src.write_text("A" * 1500)
    ingest_attachment(tape, manifest, src, chunk_size=600)

    for record in tape.read():
        d = record.to_dict()
        assert "source_document" not in d
        assert "source_span" not in d
    raw = tmp_path / "tape.jsonl"
    for line in raw.read_text(encoding="utf-8").splitlines():
        assert "source_document" not in json.loads(line)
        assert "source_span" not in json.loads(line)


def test_ingest_dedupes_by_source(tmp_path):
    tape = Tape(tmp_path / "tape.jsonl")
    manifest = Manifest(capacity=50)
    src = tmp_path / "spec.txt"
    src.write_text("hello world")
    ingest_attachment(tape, manifest, src)
    res2 = ingest_attachment(tape, manifest, src)
    assert res2.get("skipped") is True
    assert len(tape) == 1


def test_ingest_rejects_non_txt(tmp_path):
    tape = Tape(tmp_path / "tape.jsonl")
    manifest = Manifest(capacity=50)
    src = tmp_path / "a.md"
    src.write_text("x")
    assert ingest_attachment(tape, manifest, src)["ok"] is False


def test_ingest_skips_secret_chunks(tmp_path):
    tape = Tape(tmp_path / "tape.jsonl")
    manifest = Manifest(capacity=50)
    src = tmp_path / "spec.txt"
    src.write_text("clean text\nsk-abcdefghijklmnopqrstuvwxyz123456")
    res = ingest_attachment(tape, manifest, src, chunk_size=600)
    assert res["skipped_secrets"] == 1
    assert res["saved"] == 0
    assert len(tape) == 0


def test_attach_invalidates_cache(tmp_path):
    m = Machine(tmp_path, config=Config(capacity=50, router_enabled=False), client=FakeClient(lambda msg, t: '{"annotations":[]}'))
    m.add_memory(MemoryRecord(type="decision", summary="x"))
    m.recall("a question")
    assert m._recall_cache_path().exists()
    src = tmp_path / "spec.txt"
    src.write_text("attached text")
    m.attach(src)
    assert not m._recall_cache_path().exists()


def test_recall_returns_attached_content(tmp_path):
    def handler(messages, temperature):
        sys_text = "\n".join(m.get("content", "") for m in messages if m.get("role") == "system")
        if "You are a memory agent" in sys_text:
            return '{"checklist":[],"annotations":[{"memory_id":"M0001","note":"attached spec","relevance":0.9}]}'
        return '{"annotations":[]}'

    m = Machine(tmp_path, config=Config(capacity=50, router_enabled=False), client=FakeClient(handler))
    src = tmp_path / "spec.txt"
    src.write_text("The spec says to use PostgreSQL.")
    m.attach(src)

    res = m.recall("what does the spec say?")
    assert res["attached_content"]
    assert "PostgreSQL" in res["attached_content"][0]["text"]


def test_remove_attachments_keeps_regular_memories(tmp_path):
    tape = Tape(tmp_path / "tape.jsonl")
    manifest = Manifest(capacity=50)
    src = tmp_path / "spec.txt"
    src.write_text("A" * 1500)
    ingest_attachment(tape, manifest, src, chunk_size=600)
    tape.append(MemoryRecord(type="decision", summary="keep me"))

    removed = remove_attachments(tape)

    assert removed == 3
    assert [r.type for r in tape.read()] == ["decision"]


def test_remove_attachments_by_source(tmp_path):
    tape = Tape(tmp_path / "tape.jsonl")
    manifest = Manifest(capacity=50)
    a = tmp_path / "a.txt"
    a.write_text("alpha text")
    b = tmp_path / "b.txt"
    b.write_text("beta text")
    ra = ingest_attachment(tape, manifest, a)
    ingest_attachment(tape, manifest, b)

    removed = remove_attachments(tape, source=ra["source"])

    assert removed == 1
    assert len(tape) == 1
