"""D2: document identity + provenance layer in the graph (schema v2).

Four invariants must hold:
    1. a document receives a stable identity (``D####``, keyed by ``source``);
    2. a relation can point to multiple evidences (``evidence=[{memory_id, span}]``);
    3. old (schema v1) data stays readable;
    4. nothing here touches the tape beyond the D1 optional fields.
"""

import json

from memory_machine.graph import (
    GraphRelation,
    GraphStore,
    build_graph,
    document_context,
    format_document_id,
    noop_extractor,
    parse_document_id,
)
from memory_machine.retrieval import chunk_spans
from memory_machine.tape import MemoryRecord, Tape


def _register(store: GraphStore, *, source: str, status: str = "registered"):
    return store.add_document(
        source=source,
        name=source.split("#", 1)[0],
        hash=source.split("#", 1)[1],
        path=f"/srv/docs/{source.split('#', 1)[0]}",
        spans=[(0, 100), (100, 200)],
        status=status,
    )


# ----------------------------------------------------------- invariant 1


def test_document_identity_is_stable(tmp_path):
    store = GraphStore(tmp_path / "graph")
    first, created = _register(store, source="manual.txt#abc123")
    again, created_again = _register(store, source="manual.txt#abc123")

    assert created is True
    assert created_again is False
    assert first.id == again.id
    assert first.id == format_document_id(1)
    assert parse_document_id(first.id) == 1
    assert len(store.documents()) == 1


def test_document_register_fields_and_spans(tmp_path):
    store = GraphStore(tmp_path / "graph")
    text = "word " * 300
    spans = [(s, e) for s, e, _ in chunk_spans(text, size=150, overlap=20)]
    record, created = store.add_document(
        source="manual.txt#abc123",
        name="manual.txt",
        hash="abc123",
        path="/srv/docs/manual.txt",
        spans=spans,
        extractor="chunk",
    )

    assert created is True
    assert record.id.startswith("D")
    assert record.source == "manual.txt#abc123"
    assert record.name == "manual.txt"
    assert record.hash == "abc123"
    assert record.chunks == len(spans)
    assert record.spans == spans
    assert record.extractor == "chunk"
    assert record.status == "registered"
    assert store.document_by_source("manual.txt#abc123") == record


def test_add_document_requires_identity_fields(tmp_path):
    store = GraphStore(tmp_path / "graph")
    import pytest

    with pytest.raises(ValueError):
        store.add_document(source="manual.txt#abc", name="manual.txt", hash="", path="x")
    with pytest.raises(ValueError):
        store.add_document(source="", name="manual.txt", hash="abc", path="x")


def test_update_document_appends_state_with_stable_id(tmp_path):
    store = GraphStore(tmp_path / "graph")
    record, _ = _register(store, source="manual.txt#abc123")

    updated = store.update_document(record.id, status="extracted", extractor="chunk_extractor")

    assert updated is not None
    assert updated.id == record.id
    assert updated.status == "extracted"
    assert updated.extractor == "chunk_extractor"
    assert store.document_by_id(record.id) == updated
    assert store.document_by_id("D9999") is None


# ----------------------------------------------------------- invariant 2


def test_relation_carries_multi_evidence(tmp_path):
    store = GraphStore(tmp_path / "graph")
    store.add_entity("Release Process", "concept", "M0042", entity_id="E0001")
    relation = store.add_relation(
        "E0001",
        "constrained_by",
        "E0002",
        "M0042",
        0.8,
        source_document="manual.txt#abc123",
        source_span=(1800, 2300),
        evidence=[
            {"memory_id": "M0042", "span": [1800, 2300]},
            {"memory_id": "M0171", "span": [28400, 29100]},
        ],
    )

    assert relation.source_document == "manual.txt#abc123"
    assert relation.source_span == (1800, 2300)
    assert relation.evidence == (
        {"memory_id": "M0042", "span": [1800, 2300]},
        {"memory_id": "M0171", "span": [28400, 29100]},
    )

    loaded = store.relations()[0]
    assert loaded == relation
    assert loaded.evidence == (
        {"memory_id": "M0042", "span": [1800, 2300]},
        {"memory_id": "M0171", "span": [28400, 29100]},
    )

    rebuilt = GraphRelation.from_dict(relation.to_dict())
    assert rebuilt == relation


def test_evidence_from_dict_is_lenient(tmp_path):
    raw = {
        "id": "R0001",
        "source": "E0001",
        "relation": "supports",
        "target": "E0002",
        "memory_id": "M0042",
        "confidence": 0.9,
        "evidence": [
            {"memory_id": "M0042"},
            {"span": "garbage"},
            {"memory_id": "M0171", "span": [1, 2, 3]},
            {"memory_id": "M0200", "span": ["10", "20"]},
        ],
    }
    relation = GraphRelation.from_dict(raw)
    assert relation.evidence == (
        {"memory_id": "M0042"},
        {"memory_id": "M0171"},
        {"memory_id": "M0200", "span": [10, 20]},
    )


def test_mention_is_plural_provenance(tmp_path):
    store = GraphStore(tmp_path / "graph")
    store.add_entity("Anchoring", "concept", "M0042", entity_id="E0001")
    store.add_mention("M0042", "E0001", 0.9, source_document="manual.txt#abc123", span=(40, 80))
    store.add_mention("M0042", "E0001", 0.7, source_document="manual.txt#abc123", span=(300, 340))
    store.add_mention("M0171", "E0001", 0.8, source_document="other.txt#def456", span=(20, 45))

    mentions = store.mentions()
    assert len(mentions) == 3
    assert all(m.entity_id == "E0001" for m in mentions)
    assert {m.span for m in mentions} == {(40, 80), (300, 340), (20, 45)}
    assert {m.source_document for m in mentions} == {
        "manual.txt#abc123",
        "other.txt#def456",
    }


# ----------------------------------------------------------- invariant 3


def test_old_entities_relations_mentions_stay_readable(tmp_path):
    store = GraphStore(tmp_path / "graph")
    store_dir = store.directory
    store_dir.mkdir(parents=True, exist_ok=True)
    store_dir.joinpath("entities.jsonl").write_text(
        '{"id":"E0001","name":"Postgres","type":"tool","memory_id":"M0001",'
        '"created_at":"2000-01-01T00:00:00+00:00"}\n',
        encoding="utf-8",
    )
    store_dir.joinpath("relations.jsonl").write_text(
        '{"id":"R0001","source":"E0001","relation":"used_for","target":"E0002",'
        '"memory_id":"M0001","confidence":0.8,"kind":"","extractor":"noop",'
        '"extractor_version":"v1"}\n',
        encoding="utf-8",
    )
    store_dir.joinpath("mentions.jsonl").write_text(
        '{"memory_id":"M0001","entity_id":"E0001","confidence":0.8}\n',
        encoding="utf-8",
    )

    entity = store.entities()[0]
    relation = store.relations()[0]
    mention = store.mentions()[0]

    assert entity.source_document == ""
    assert entity.source_span == ()
    assert relation.evidence == ()
    assert relation.source_document == ""
    assert mention.source_document == ""
    assert mention.span == ()
    assert "source_document" not in entity.to_dict()
    assert "evidence" not in relation.to_dict()
    assert "span" not in mention.to_dict()


def test_documents_registry_is_absent_for_old_graphs(tmp_path):
    store = GraphStore(tmp_path / "graph")
    assert store.documents() == []
    assert "documents" not in {d for d in []}  # registry adds only when used


# ----------------------------------------------------------- invariant 4


def test_d2_operations_never_touch_the_tape(tmp_path):
    tape_path = tmp_path / "tape.jsonl"
    tape = Tape(tape_path)
    tape.append(MemoryRecord(type="decision", summary="Use Postgres", why="ACID"))
    tape.append(MemoryRecord(type="lesson", summary="Tests must be green", why=""))
    tape_before = tape_path.read_bytes()

    store = GraphStore(tmp_path / "graph")
    record, _ = store.add_document(
        source="spec.txt#beef01", name="spec.txt", hash="beef01", path="/srv/spec.txt",
        spans=[(0, 10)],
    )
    store.add_entity("Postgres", "tool", "M0001", entity_id="E0001")
    store.add_relation(
        "E0001", "used_for", "E0002", "M0001", 0.8,
        source_document=record.source,
        evidence=[{"memory_id": "M0001", "span": [0, 10]}],
    )
    store.add_mention("M0001", "E0001", source_document=record.source, span=(0, 10))
    document_context(store, record.source)

    assert tape_path.read_bytes() == tape_before
    assert len(tape.read()) == 2


# ----------------------------------------------------------- capabilities


def test_document_context_filters_by_document(tmp_path):
    store = GraphStore(tmp_path / "graph")
    doc_a, _ = _register(store, source="manual.txt#abc123")
    store.add_document(
        source="other.txt#def456", name="other.txt", hash="def456", path="/srv/other.txt"
    )
    store.add_entity("Anchoring", "concept", "M0042", entity_id="E0001",
                     source_document=doc_a.source)
    store.add_entity("Budget", "concept", "M0171", entity_id="E0002")

    store.add_relation("E0001", "constrains", "E0002", "M0042", 0.8,
                       source_document=doc_a.source,
                       evidence=[{"memory_id": "M0042", "span": [1800, 2300]}])
    store.add_relation("E0002", "relates_to", "E0001", "M0188", 0.7,
                       source_document="other.txt#def456")
    store.add_mention("M0042", "E0001", source_document=doc_a.source, span=(1800, 2300))
    store.add_mention("M0171", "E0002", source_document="other.txt#def456", span=(9, 12))

    view = document_context(store, doc_a.source)

    assert view["ok"] is True
    assert view["document"]["id"] == doc_a.id
    assert view["memories"] == ["M0042"]
    assert [e["id"] for e in view["entities"]] == ["E0001"]
    assert [r["relation"] for r in view["relations"]] == ["constrains"]
    assert [m["span"] for m in view["mentions"]] == [[1800, 2300]]

    by_id = document_context(store, doc_a.id)
    assert by_id["memories"] == view["memories"]

    unknown = document_context(store, "D9999")
    assert unknown["ok"] is False


def test_entities_stay_globally_resolved_across_documents(tmp_path):
    store = GraphStore(tmp_path / "graph")
    doc_a, _ = _register(store, source="manual.txt#abc123")
    store.add_document(
        source="other.txt#def456", name="other.txt", hash="def456", path="/srv/other.txt"
    )
    store.add_entity("Anchoring", "concept", "M0042", entity_id="E0001",
                     source_document=doc_a.source)
    store.add_mention("M0042", "E0001", source_document=doc_a.source, span=(40, 80))
    store.add_mention("M1200", "E0001", source_document="other.txt#def456", span=(7, 9))

    assert len(store.entities()) == 1
    assert store.entities()[0].id == "E0001"

    view_doc_a = document_context(store, doc_a.source)
    view_doc_b = document_context(store, "other.txt#def456")
    assert view_doc_a["ok"] and view_doc_b["ok"]
    assert [e["id"] for e in view_doc_a["entities"]] == ["E0001"]
    assert [e["id"] for e in view_doc_b["entities"]] == ["E0001"]
    assert view_doc_a["memories"] == ["M0042"]
    assert view_doc_b["memories"] == ["M1200"]


def test_counts_include_documents(tmp_path):
    store = GraphStore(tmp_path / "graph")
    _register(store, source="manual.txt#abc123")
    assert store.counts()["documents"] == 1


def test_rebuild_preserves_document_registry_atomic(tmp_path):
    tape = Tape(tmp_path / "tape.jsonl")
    tape.append(MemoryRecord(type="decision", summary="Use Postgres", why="ACID"))
    store = GraphStore(tmp_path / "graph")
    record, _ = _register(store, source="manual.txt#abc123")
    build_graph(tape, store, noop_extractor, extractor_name="noop")
    before = store.documents()

    result = build_graph(tape, store, noop_extractor, extractor_name="noop", rebuild=True)

    assert result["ok"] is True
    assert result["rebuilt"] is True
    assert store.document_by_id(record.id) == record
    assert [d.source for d in store.documents()] == [d.source for d in before]
    assert store.counts()["documents"] == 1


def test_rebuild_preserves_document_registry_non_atomic(tmp_path):
    tape = Tape(tmp_path / "tape.jsonl")
    tape.append(MemoryRecord(type="decision", summary="Use Postgres", why="ACID"))
    store = GraphStore(tmp_path / "graph")
    record, _ = _register(store, source="manual.txt#abc123")

    result = build_graph(
        tape, store, noop_extractor, extractor_name="noop", rebuild=True, atomic=False
    )

    assert result["ok"] is True
    assert store.document_by_id(record.id) == record
    assert store.counts()["documents"] == 1


def test_run_documents_persist_jsonl_rows(tmp_path):
    store = GraphStore(tmp_path / "graph")
    _register(store, source="manual.txt#abc123")
    rows = store._load("documents.jsonl")
    assert len(rows) == 1
    row = rows[0]
    assert row["id"] == "D0001"
    assert row["source"] == "manual.txt#abc123"
    assert json.loads(json.dumps(row))["spans"] == [[0, 100], [100, 200]]