"""N1/N3 conformance: end-to-end provenance from selection back to the tape.

Restricted wording (matrix correction): projections may select memories, but
every persistent evidence item attributed to the Memory Machine must be
rehydratable to the frozen tape or the preserved original. This test ingests a
document, then checks every graph row, chunk memory and rehydrated payload item
against the tape and the original — byte-exact spans and hashes.
"""

from __future__ import annotations

from memory_machine.attachments import _file_hash
from memory_machine.documents import documents_dir
from memory_machine.graph import GraphStore
from memory_machine.groups import Manifest
from memory_machine.ingest_document import ingest_document
from memory_machine.payload import build_evidence_payload, payload_as_context
from memory_machine.tape import Tape
from memory_machine.whiteboard import Annotation

from test_document_ingest import CONTENT, FakeExtractor


def _ingested(tmp_path):
    tape = Tape(tmp_path / "tape.jsonl")
    manifest = Manifest(capacity=50)
    src = tmp_path / "guide.txt"
    src.write_text(CONTENT, encoding="utf-8")
    store = GraphStore(tmp_path / "graph")
    result = ingest_document(
        tape, manifest, src, chunk_size=80, overlap=0,
        store=store, extractor=FakeExtractor(), enable_graph=True,
        documents_root=documents_dir(tmp_path),
    )
    return tape, store, src, result["source"]


def test_every_graph_row_points_back_to_tape_and_original(tmp_path):
    tape, store, src, source = _ingested(tmp_path)
    records = {r.id: r for r in tape.read()}
    original = (documents_dir(tmp_path) / src.name).read_text(encoding="utf-8").strip()
    doc = store.document_by_source(source)
    assert _file_hash(original) == doc.hash

    for relation in store.relations():
        assert relation.memory_id in records
    for mention in store.mentions():
        assert mention.memory_id in records
    for chunk in records.values():
        if chunk.source_document != source:
            continue
        start, end = chunk.source_span
        assert 0 <= start < end <= len(original)
        assert original[start:end] == chunk.why


def test_rehydrated_payload_is_exact_and_traceable(tmp_path):
    tape, store, src, source = _ingested(tmp_path)
    records = {r.id: r for r in tape.read()}
    original = (documents_dir(tmp_path) / src.name).read_text(encoding="utf-8").strip()
    chunk_ids = [r.id for r in records.values() if r.source_document == source]
    assert chunk_ids
    annotations = [
        Annotation(memory_id=memory_id, note="attached chunk", relevance=0.9)
        for memory_id in chunk_ids
    ]
    payload = build_evidence_payload(records, annotations, budget=4000,
                                     min_item_chars=100)
    assert payload
    assert sum(item["used_chars"] for item in payload) <= 4000
    for item in payload:
        memory = records[item["memory_id"]]
        assert memory.source_document == source
        start, end = memory.source_span
        assert original[start:end] in item["evidence"]
        assert _file_hash(original) == store.document_by_source(source).hash
