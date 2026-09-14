"""D3: document ingestion → tape → registry → graph (chunk-level provenance).

Seven scenarios must hold:
    1. a .txt becomes tape chunks + a ``D####`` row + graph rows;
    2. provenance (``source_document``/``source_span``/``evidence``) is correct
       down to ``GraphMention``;
    3. an extractor failure retries without duplicating memories;
    4. ``enable_graph=False`` (``--no-document-graph``) adds no graph rows;
    5. re-ingestion is idempotent (same ``source``);
    6. a secret chunk is skipped and never produces false provenance;
    7. a partial batch failure does not corrupt other batches.
"""

import json

from memory_machine.graph import GraphStore
from memory_machine.graph_extract import ExtractionError
from memory_machine.groups import Manifest
from memory_machine.ingest_document import ingest_document
from memory_machine.tape import MemoryRecord, Tape

CONTENT = (
    "Kalak crossed the rock. "
    "Kalak fostered the birds. "
    "Kalak kept the rock dry. "
)


def _default_extraction(record):
    return {
        "entities": [
            {"name": "Kalak", "type": "character"},
            {"name": "rock", "type": "object"},
        ],
        "relations": [
            {"source": "Kalak", "relation": "crossed", "target": "rock", "confidence": 0.9},
        ],
        "mentions": ["Kalak"],
    }


class FakeExtractor:
    """Chunk extractor: per-record ``extract`` + batched ``extract_batch``.

    ``transport_failures`` simulates transient API/LLM failures on the first
    calls; ``batch_miss_first`` drops the first record from a batch response.
    """

    name = "fake_doc"
    version = "v1"

    def __init__(self, transport_failures=0, batch_miss_first=False):
        self.transport_failures = transport_failures
        self.batch_miss_first = batch_miss_first
        self.calls = 0

    @property
    def tag(self):
        return "fake_doc/v1"

    def _transient(self):
        if self.transport_failures > 0:
            self.transport_failures -= 1
            raise ExtractionError("fake transient failure")

    def _result(self, record):
        return _default_extraction(record)

    def extract(self, record):
        self.calls += 1
        self._transient()
        return self._result(record)

    def extract_batch(self, records):
        self.calls += 1
        self._transient()
        results = {}
        for i, record in enumerate(records):
            if self.batch_miss_first and i == 0:
                continue
            results[record.id] = self._result(record)
        return results


def _env(tmp_path):
    tape = Tape(tmp_path / "tape.jsonl")
    manifest = Manifest(capacity=50)
    src = tmp_path / "guide.txt"
    store = GraphStore(tmp_path / "graph")
    return tape, manifest, src, store


def _records(tape):
    return [r for r in tape.read() if r.type == "attachment"]


# ------------------------------------------------------------- scenario 1


def test_txt_becomes_tape_plus_document_plus_graph(tmp_path):
    tape, manifest, src, store = _env(tmp_path)
    src.write_text(CONTENT * 3)
    result = ingest_document(
        tape, manifest, src, chunk_size=80, overlap=0,
        store=store, extractor=FakeExtractor(), enable_graph=True,
    )

    assert result["ok"] is True
    assert result["saved"] == result["chunks"] >= 3
    source = result["source"]

    records = _records(tape)
    assert len(records) == result["saved"]
    assert all(r.source == source for r in records)
    assert all(r.source_document == source for r in records)
    assert all(len(r.source_span) == 2 for r in records)

    doc = store.document_by_source(source)
    assert doc is not None and doc.id == result["document"]["id"]
    assert doc.id.startswith("D")
    assert doc.status == "extracted"
    assert doc.chunks == result["chunks"]

    counts = store.counts()
    assert counts["entities"] >= 2
    assert counts["relations"] >= 1
    assert counts["mentions"] >= 1
    entities = {e.name.lower(): e for e in store.entities()}
    assert {"kalak", "rock"} <= set(entities)
    assert entities["kalak"].source_document == source


# ------------------------------------------------------------- scenario 2


def test_provenance_reaches_graph_mention_and_evidence(tmp_path):
    tape, manifest, src, store = _env(tmp_path)
    src.write_text(CONTENT * 3)
    result = ingest_document(
        tape, manifest, src, chunk_size=80, overlap=40,
        store=store, extractor=FakeExtractor(), enable_graph=True,
    )
    source = result["source"]

    mentions = store.mentions()
    assert mentions
    assert all(m.source_document == source for m in mentions)
    assert all(isinstance(m.span, tuple) and len(m.span) == 2 for m in mentions)

    for relation in store.relations():
        assert relation.source_document == source
        assert isinstance(relation.source_span, tuple) and len(relation.source_span) == 2
        assert len(relation.evidence) == 1
        evidence = relation.evidence[0]
        assert evidence["memory_id"] == relation.memory_id
        assert evidence["span"] == list(relation.source_span)

    saved_ids = {r.id for r in _records(tape)}
    assert all(m.memory_id in saved_ids for m in mentions)


def test_durable_records_stay_free_of_provenance(tmp_path):
    tape, manifest, src, store = _env(tmp_path)
    src.write_text(CONTENT * 3)
    from memory_machine.groups import add_memory

    add_memory(tape, manifest, MemoryRecord(type="decision", summary="Kalak", why="later"))
    ingest_document(
        tape, manifest, src, chunk_size=80, overlap=0,
        store=store, extractor=FakeExtractor(), enable_graph=True,
    )

    decisions = [r for r in tape.read() if r.type == "decision"]
    assert len(decisions) == 1
    assert decisions[0].source_document == ""

    for entity in store.entities():
        assert entity.source_document
    for relation in store.relations():
        assert relation.source_document


# ------------------------------------------------------------- scenario 3


def test_extractor_retry_does_not_duplicate_memories(tmp_path):
    tape, manifest, src, store = _env(tmp_path)
    src.write_text(CONTENT * 2)
    extractor = FakeExtractor(transport_failures=1)
    first = ingest_document(
        tape, manifest, src, chunk_size=80, overlap=0,
        store=store, extractor=extractor, enable_graph=True,
    )
    first_records = _records(tape)
    assert first["document_graph"]["status"] in {"pending", "partial"}
    assert first["document_graph"]["failed"] == 0

    second = ingest_document(
        tape, manifest, src, chunk_size=80, overlap=0,
        store=store, extractor=extractor, enable_graph=True,
    )
    assert second["skipped"] is True
    assert second["document_graph"]["applied"] >= 1
    assert _records(tape) == first_records  # no duplicate memories

    extracted = store.extracted_ids("fake_doc/v1")
    assert len(extracted) == len(first_records)
    assert all(r.id in extracted for r in first_records)


# ------------------------------------------------------------- scenario 4


def test_no_document_graph_adds_no_graph_rows(tmp_path):
    tape, manifest, src, store = _env(tmp_path)
    src.write_text(CONTENT * 3)
    result = ingest_document(
        tape, manifest, src, chunk_size=80, overlap=0,
        store=store, extractor=FakeExtractor(), enable_graph=False,
    )

    assert result["ok"] is True
    assert result["document"] is None
    assert result["document_graph"]["enabled"] is False
    counts = store.counts()
    assert counts["documents"] == 0
    assert counts["entities"] == 0
    assert counts["relations"] == 0
    assert counts["mentions"] == 0

    records = _records(tape)
    assert len(records) == result["chunks"]
    assert all(r.source_document for r in records)
    assert all(r.source_span for r in records)


# ------------------------------------------------------------- scenario 5


def test_reingestion_is_idempotent(tmp_path):
    tape, manifest, src, store = _env(tmp_path)
    src.write_text(CONTENT * 3)
    extractor = FakeExtractor()
    first = ingest_document(
        tape, manifest, src, chunk_size=80, overlap=0,
        store=store, extractor=extractor, enable_graph=True,
    )
    before = _records(tape)

    second = ingest_document(
        tape, manifest, src, chunk_size=80, overlap=0,
        store=store, extractor=FakeExtractor(), enable_graph=True,
    )

    assert second["ok"] is True
    assert second["skipped"] is True
    assert second["saved"] == 0
    assert _records(tape) == before
    assert store.document_by_source(first["source"]) is not None
    assert len(store.documents()) == 1


# ------------------------------------------------------------- scenario 6


def test_secret_chunk_skipped_without_false_provenance(tmp_path):
    tape, manifest, src, store = _env(tmp_path)
    secret_text = "sk-abcdefghijklmnopqrstuvwxyz123456"
    src.write_text("A" * 40 + secret_text)
    result = ingest_document(
        tape, manifest, src, chunk_size=40, overlap=0,
        store=store, extractor=FakeExtractor(), enable_graph=True,
    )

    assert result["ok"] is True
    assert result["saved"] == 1
    assert result["skipped_secrets"] == 1

    records = _records(tape)
    assert len(records) == 1
    assert records[0].source_span == (0, 40)
    assert all(secret_text not in r.why for r in records)

    for mention in store.mentions():
        assert mention.memory_id == records[0].id
        assert mention.source_document == result["source"]
    for entity in store.entities():
        assert entity.source_document == result["source"]
    # nobody points at a memory that does not exist on the tape
    saved_ids = {r.id for r in records}
    assert all(m.memory_id in saved_ids for m in store.mentions())


# ------------------------------------------------------------- scenario 7


def test_partial_batch_failure_isolated(tmp_path):
    tape, manifest, src, store = _env(tmp_path)
    src.write_text(CONTENT * 6)
    extractor = FakeExtractor(batch_miss_first=True)
    result = ingest_document(
        tape, manifest, src, chunk_size=60, overlap=0,
        store=store, extractor=extractor, enable_graph=True,
    )

    assert result["ok"] is True
    total = result["chunks"]
    batch = result["document_graph"]
    assert batch["applied"] == total - 1
    assert batch["pending"] == 1  # first record missing from the batch response

    records = _records(tape)
    assert len(records) == total  # tape never lost a chunk
    failed_id = records[0].id  # first in the batch

    projected = {m.memory_id for m in store.mentions()}
    assert failed_id not in projected
    assert projected == {r.id for r in records[1:]}


def test_manifest_json_registry_persists(tmp_path):
    tape, manifest, src, store = _env(tmp_path)
    src.write_text(CONTENT * 3)
    ingest_document(
        tape, manifest, src, chunk_size=80, overlap=0,
        store=store, extractor=FakeExtractor(), enable_graph=True,
    )
    rows = [json.loads(line) for line in (store.directory / "documents.jsonl").read_text().splitlines()]
    assert any(str(row.get("id", "")).startswith("D") for row in rows)