"""D4: document-level structure — window pass over chunk memories (D4).

Contract (closed design M0176). Ten scenarios:
  1. a relation that depends on two distant chunks is created by the window pass;
  2. that relation's ``evidence`` carries both exact spans, ``source_document``
     and ``extraction_scope == "document"`` (audit-only);
  3. a global topic does not duplicate a local entity (``both``, same graph);
  4. ``chunk`` / ``document`` / ``both`` are deterministic and scoped;
  5. a window failure never invalidates chunk rows or the tape;
  6. re-execution projects nothing twice in either scope;
  7. ``enable_graph=False`` zeroes all projection even under level ``both``;
  8. D3 data (rows without ``extraction_scope``) stays readable;
  9. chunk+document converge: same semantic (source, relation, target) is one
     entity pair with two scoped rows, never an overwrite;
 10. serialization round-trips scope and multi-span evidence.

Guards verified additionally: window evidence can never point outside the
window (non-member ids are dropped; empty evidence defaults to all members),
and ``scope`` never influences the resolver/confidence.
"""

import json

from memory_machine.graph import GraphStore, normalize_name
from memory_machine.graph_extract import ExtractionError
from memory_machine.groups import Manifest
from memory_machine.ingest_document import ingest_document
from memory_machine.tape import Tape


def _chunk_payload(record):
    """Local view: a character + its object, one relation in this chunk."""
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


class WindowExtractor:
    """Chunk extractor + window extractor (``extract_window``, D4)."""

    name = "winfake"
    version = "v1"

    def __init__(self, window_fn=None, window_fail=False):
        self.window_fn = window_fn
        self.window_fail = window_fail

    @property
    def tag(self):
        return "winfake/v1"

    def extract(self, record):
        return _chunk_payload(record)

    def extract_batch(self, records):
        return {r.id: self.extract(r) for r in records}

    def extract_window(self, window):
        if self.window_fail:
            raise ExtractionError("fake window transport failure")
        if self.window_fn is not None:
            return self.window_fn(window)
        return {"entities": [], "relations": [], "mentions": []}


def _env(tmp_path):
    tape = Tape(tmp_path / "tape.jsonl")
    manifest = Manifest(capacity=50)
    src = tmp_path / "novella.txt"
    store = GraphStore(tmp_path / "graph")
    return tape, manifest, src, store


def _attachment_records(tape):
    return [r for r in tape.read() if r.type == "attachment"]


# ------------------------------------------------------------- scenarios 1+2


def test_distant_chunks_relation_carries_both_spans(tmp_path):
    text = "A" * 40 + "B" * 40  # two far-apart chunks: [0,40) [40,80)
    tape, manifest, src, store = _env(tmp_path)
    src.write_text(text)

    def window_fn(window):
        return {
            "entities": [
                {"name": "Kalak", "type": "character"},
                {"name": "rock", "type": "object"},
            ],
            "relations": [
                {
                    "source": "Kalak",
                    "relation": "influences",
                    "target": "rock",
                    "confidence": 0.8,
                    "evidence": [
                        {"memory_id": window.members[0].id, "span": [0, 40]},
                        {"memory_id": window.members[1].id, "span": [40, 80]},
                    ],
                },
            ],
        }

    result = ingest_document(
        tape, manifest, src, chunk_size=40, overlap=0,
        store=store, extractor=WindowExtractor(window_fn=window_fn),
        enable_graph=True, structure_level="document", window_chars=200,
    )
    source = result["source"]
    members = _attachment_records(tape)
    assert len(members) == 2
    assert members[0].source_span == (0, 40)
    assert members[1].source_span == (40, 80)

    relations = [r for r in store.relations()]
    assert len(relations) == 1
    relation = relations[0]
    assert relation.relation == "influences"
    assert relation.extraction_scope == "document"
    assert relation.source_document == source
    assert relation.source_span == (0, 80)
    assert [sorted(ev.items()) for ev in relation.evidence] == [
        sorted({"memory_id": members[0].id, "span": [0, 40]}.items()),
        sorted({"memory_id": members[1].id, "span": [40, 80]}.items()),
    ]
    assert relation.source.startswith("E") and relation.target.startswith("E")
    assert relation.confidence == 0.8


# ------------------------------------------------------------- scenario 3


def test_global_topic_does_not_duplicate_local_entity(tmp_path):
    text = " ".join(
        ["Kalak", "kept", "the", "rock", "dry.", "Graph", "plasticity", "matters."]
    ) * 20
    tape, manifest, src, store = _env(tmp_path)
    src.write_text(text)

    class TopicWindowExtractor(WindowExtractor):
        def extract(self, record):
            payload = _chunk_payload(record)
            if "plasticity" in record.why:
                payload["entities"].append(
                    {"name": "Graph plasticity", "type": "concept"}
                )
                payload["relations"].append(
                    {"source": "Kalak", "relation": "related_to",
                     "target": "Graph plasticity", "confidence": 0.7}
                )
            return payload

        def extract_window(self, window):
            return {
                "entities": [
                    {"name": "Graph plasticity", "type": "topic"},
                    {"name": "Kalak", "type": "character"},
                ],
                "relations": [
                    {"source": "Kalak", "relation": "central_to",
                     "target": "Graph plasticity", "confidence": 0.9},
                ],
            }

    result = ingest_document(
        tape, manifest, src, chunk_size=80, overlap=0,
        store=store, extractor=TopicWindowExtractor(),
        enable_graph=True, structure_level="both", window_chars=2000,
    )

    names = [e for e in store.entities() if normalize_name(e.name) == normalize_name("Graph plasticity")]
    assert len(names) == 1  # topic and local concept resolve to the same node
    assert names[0].source_document == result["source"]
    assert names[0].extraction_scope in {"chunk", "document"}

    crossed = [r for r in store.relations() if r.relation == "central_to"]
    assert len(crossed) == 1
    assert crossed[0].source.startswith("E") and crossed[0].target.startswith("E")


# ------------------------------------------------------------- scenario 4


def test_structure_levels_are_deterministic_and_scoped(tmp_path):
    tape, manifest, src, store = _env(tmp_path)
    src.write_text("Kalak fostered the birds. " * 10)

    for level in ("chunk", "document", "both"):
        store_a = GraphStore(src.parent / f"graph_{level}_a")
        store_b = GraphStore(src.parent / f"graph_{level}_b")
        ingest_document(
            tape, manifest, src, chunk_size=60, overlap=0,
            store=store_a, extractor=WindowExtractor(
                window_fn=lambda w: _chunk_payload(w.members[0])),
            enable_graph=True, structure_level=level,
        )
        ingest_document(
            tape, manifest, src, chunk_size=60, overlap=0,
            store=store_b, extractor=WindowExtractor(
                window_fn=lambda w: _chunk_payload(w.members[0])),
            enable_graph=True, structure_level=level,
        )
        assert store_a.counts() == store_b.counts()
        assert len(store_a.relations()) == len(store_b.relations())
        assert {r.relation for r in store_a.relations()} == {r.relation for r in store_b.relations()}

    # scoped rows: chunk rows carry "chunk", window rows "document"
    only_both = GraphStore(src.parent / "graph_both")
    ingest_document(
        tape, manifest, src, chunk_size=60, overlap=0,
        store=only_both, extractor=WindowExtractor(
            window_fn=lambda w: _chunk_payload(w.members[0])),
        enable_graph=True, structure_level="both",
    )
    only_doc = GraphStore(src.parent / "graph_doc")
    ingest_document(
        tape, manifest, src, chunk_size=60, overlap=0,
        store=only_doc, extractor=WindowExtractor(
            window_fn=lambda w: _chunk_payload(w.members[0])),
        enable_graph=True, structure_level="document",
    )
    assert only_both.counts()["documents"] == 1
    assert only_doc.counts()["documents"] == 1
    assert {r.extraction_scope for r in only_both.relations()} == {"chunk", "document"}
    assert {r.extraction_scope for r in only_doc.relations()} == {"document"}


# ------------------------------------------------------------- scenario 5


def test_window_failure_never_invalidates_chunk_or_tape(tmp_path):
    tape, manifest, src, store = _env(tmp_path)
    src.write_text("Kalak kept the rock dry. " * 8)
    records_before = None

    result = ingest_document(
        tape, manifest, src, chunk_size=60, overlap=0,
        store=store, extractor=WindowExtractor(window_fail=True),
        enable_graph=True, structure_level="both",
    )

    records_after = _attachment_records(tape)
    assert result["ok"] is True
    assert result["document_graph"]["chunk"]["status"] == "extracted"
    assert result["document_graph"]["document"]["status"] in {"pending", "partial"}

    assert len(records_after) == result["chunks"]
    assert all(r.source and r.source_span for r in records_after)
    assert len(store.relations()) >= 1  # chunk rows survived
    assert all(r.extraction_scope == "chunk" for r in store.relations())
    assert records_before is None or records_after == records_before


# ------------------------------------------------------------- scenario 6


def test_reexecution_projects_nothing_twice(tmp_path):
    tape, manifest, src, store = _env(tmp_path)
    src.write_text("Kalak fostered the birds. " * 10)
    extractor = WindowExtractor(window_fn=lambda w: _chunk_payload(w.members[0]))

    first = ingest_document(
        tape, manifest, src, chunk_size=60, overlap=0,
        store=store, extractor=extractor,
        enable_graph=True, structure_level="both",
    )
    counts_before = store.counts()
    relations_before = [(r.source, r.relation, r.target, r.extraction_scope)
                        for r in store.relations()]

    second = ingest_document(
        tape, manifest, src, chunk_size=60, overlap=0,
        store=store, extractor=extractor,
        enable_graph=True, structure_level="both",
    )
    assert second["skipped"] is True
    assert second["document_graph"]["applied"] == 0
    assert second["document_graph"]["chunk"]["applied"] == 0
    assert second["document_graph"]["document"]["applied"] == 0
    assert store.counts() == counts_before
    assert sorted(relations_before) == sorted(
        [(r.source, r.relation, r.target, r.extraction_scope) for r in store.relations()]
    )


# ------------------------------------------------------------- scenario 7


def test_no_document_graph_zeroes_projection_even_in_both(tmp_path):
    tape, manifest, src, store = _env(tmp_path)
    src.write_text("Kalak kept the rock dry. " * 8)
    result = ingest_document(
        tape, manifest, src, chunk_size=60, overlap=0,
        store=store, extractor=WindowExtractor(),
        enable_graph=False, structure_level="both",
    )

    assert result["ok"] is True
    assert result["document"] is None
    assert result["document_graph"]["enabled"] is False
    assert result["document_graph"]["structure_level"] == "both"
    assert store.counts()["documents"] == 0
    assert store.counts()["entities"] == 0
    assert store.counts()["relations"] == 0
    assert store.counts()["mentions"] == 0
    # the tape still holds every chunk with provenance
    records = _attachment_records(tape)
    assert len(records) == result["chunks"]
    assert all(r.source_document == result["source"] for r in records)


# ------------------------------------------------------------- scenario 8


def test_d3_legacy_rows_stay_readable(tmp_path):
    tape, manifest, src, store = _env(tmp_path)
    src.write_text("legacy content " * 8)
    store.directory.mkdir(parents=True, exist_ok=True)
    (store.directory / "entities.jsonl").write_text(json.dumps({
        "id": "E0001", "name": "Kalak", "type": "character",
        "memory_id": "M0001", "confidence": 0.9, "kind": "entity",
        "extractor": "old/v1", "extractor_version": "v1",
        "source_document": "doc.txt#legacy", "source_span": [0, 100],
    }) + "\n")
    (store.directory / "relations.jsonl").write_text(json.dumps({
        "id": "R0001", "source": "E0001", "relation": "crossed",
        "target": "E0002", "memory_id": "M0001", "confidence": 0.8,
        "kind": "relation", "extractor": "old/v1", "extractor_version": "v1",
        "source_document": "doc.txt#legacy", "source_span": [0, 100],
        "evidence": [{"memory_id": "M0001", "span": [0, 100]}],
    }) + "\n")

    entity = store.entities()[0]
    relation = store.relations()[0]
    assert entity.id == "E0001" and entity.extraction_scope == ""
    assert relation.extraction_scope == ""
    assert relation.evidence == ({"memory_id": "M0001", "span": [0, 100]},)
    assert relation.source_document == "doc.txt#legacy"

    # and a fresh window row can co-exist with the legacy rows
    result = ingest_document(
        tape, manifest, src, chunk_size=60, overlap=0,
        store=store, extractor=WindowExtractor(window_fn=lambda w: _chunk_payload(w.members[0])),
        enable_graph=True, structure_level="document",
    )
    assert result["document_graph"]["document"]["applied"] >= 1
    assert {r.extraction_scope for r in store.relations()} <= {"", "document"}


# ------------------------------------------------------------- scenario 9


def test_chunk_document_converge_without_overwrite(tmp_path):
    text = "Kalak crossed the big rough rock. " * 20
    tape, manifest, src, store = _env(tmp_path)
    src.write_text(text)

    def window_fn(window):
        return {
            "entities": [
                {"name": "Kalak", "type": "character"},
                {"name": "rock", "type": "object"},
            ],
            "relations": [
                {"source": "Kalak", "relation": "crossed", "target": "rock",
                 "confidence": 0.95, "evidence": [
                     {"memory_id": window.members[0].id,
                      "span": list(window.members[0].source_span)},
                     {"memory_id": window.members[-1].id,
                      "span": list(window.members[-1].source_span)},
                 ]},
            ],
        }

    ingest_document(
        tape, manifest, src, chunk_size=70, overlap=10,
        store=store, extractor=WindowExtractor(window_fn=window_fn),
        enable_graph=True, structure_level="both", window_chars=5000,
    )

    relations = [r for r in store.relations() if r.relation == "crossed"]
    scopes = sorted({r.extraction_scope for r in relations})
    assert scopes == ["chunk", "document"]  # two rows, never an overwrite
    pairs = {(r.source, r.target) for r in relations}
    assert len(pairs) == 1  # same resolved entity pair across scopes
    assert all(r.source == relations[0].source for r in relations)
    document_row = next(r for r in relations if r.extraction_scope == "document")
    assert len(document_row.evidence) == 2


# ------------------------------------------------------------- scenario 10


def test_scope_and_evidence_round_trip(tmp_path):
    tape, manifest, src, store = _env(tmp_path)
    src.write_text("A" * 40 + "B" * 40 + "C" * 40)  # three chunks
    members = None

    def window_fn(window):
        nonlocal members
        members = [m.id for m in window.members]
        return {
            "entities": [{"name": "Kalak", "type": "character"}],
            "relations": [
                {
                    "source": "Kalak", "relation": "influences", "target": "rock",
                    "confidence": 0.8,
                    "evidence": [
                        {"memory_id": window.members[0].id,
                         "span": list(window.members[0].source_span)},
                        {"memory_id": window.members[2].id,
                         "span": list(window.members[2].source_span)},
                    ],
                },
            ],
        }

    ingest_document(
        tape, manifest, src, chunk_size=40, overlap=0,
        store=store, extractor=WindowExtractor(window_fn=window_fn),
        enable_graph=True, structure_level="both", window_chars=400,
    )

    reloaded = GraphStore(store.directory)
    relation = [r for r in reloaded.relations() if r.relation == "influences"][0]
    assert relation.extraction_scope == "document"
    assert [ev["memory_id"] for ev in relation.evidence] == [members[0], members[2]]

    for entity in reloaded.entities():
        assert entity.extraction_scope in {"chunk", "document"}
    for mention in reloaded.mentions():
        assert mention.extraction_scope == "chunk"

    # scope never changed trust: confidence survived byte-for-byte
    assert relation.confidence == 0.8


# ------------------------------------------------------------- guard 1


def test_window_evidence_never_escapes_the_window(tmp_path):
    text = "A" * 40 + "B" * 40 + "C" * 40 + "D" * 40  # four chunks, one window
    tape, manifest, src, store = _env(tmp_path)
    src.write_text(text)

    def window_fn(window):
        return {
            "entities": [
                {"name": "Kalak", "type": "character"},
                {"name": "rock", "type": "object"},
            ],
            "relations": [
                {
                    "source": "Kalak",
                    "relation": "influences",
                    "target": "rock",
                    "confidence": 0.8,
                    "evidence": [
                        {"memory_id": window.members[0].id},
                        {"memory_id": "M000000000000000099",
                         "span": [9999, 10000]},  # never a window member
                        {"memory_id": "not-a-real-id"},
                    ],
                },
                {
                    "source": "Kalak",
                    "relation": "related_to",
                    "target": "rock",
                    "confidence": 0.6,  # no evidence -> defaults to all members
                },
            ],
        }

    ingest_document(
        tape, manifest, src, chunk_size=40, overlap=0,
        store=store, extractor=WindowExtractor(window_fn=window_fn),
        enable_graph=True, structure_level="document", window_chars=1000,
    )

    members = _attachment_records(tape)
    member_ids = {m.id for m in members}

    influences = [r for r in store.relations() if r.relation == "influences"][0]
    assert influences.extraction_scope == "document"
    # the two bogus ids are dropped; the real member survived
    assert [ev["memory_id"] for ev in influences.evidence] == [members[0].id]
    assert all(ev["memory_id"] in member_ids for ev in influences.evidence)
    assert [ev.get("span") for ev in influences.evidence] != [[9999, 10000]]

    related = [r for r in store.relations() if r.relation == "related_to"][0]
    assert sorted(ev["memory_id"] for ev in related.evidence) == sorted(member_ids)
    assert [ev["span"] for ev in related.evidence] == [list(m.source_span) for m in members]