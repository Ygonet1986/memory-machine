"""D5: operational document graph — rebuild, subgraph, explain, originals.

Closed design (M0180). Ten scenarios plus the decisive round-trip:
  1. ingest preserves the original under ``<root>/documents/`` with a
     registered ``original`` and matching hash;
  2. **round-trip**: ingest -> snapshot -> drop the derived projection ->
     rebuild -> structural + provenance equivalence (the tape/registry/
     originals are the only truth);
  3. a missing original aborts the rebuild explicitly, previous graph kept;
  4. an altered original (hash mismatch) aborts the rebuild explicitly;
  5. rebuild respects ``document_structure_level`` (chunk only / both);
  6. an incremental re-run projects nothing twice (idempotent);
  7. ``graph document`` view: by id/source/name, ``--memory`` / ``--span``
     filters, window map and hash-validated original status;
  8. ``graph explain`` shows **all** evidence spans re-hydrated from the
     preserved original and links the document/window chain;
  9. durable explain contract is unchanged (old keys, first-class provenance);
 10. plain ``build_graph`` (no doc knobs) keeps the graph-v3 projection
     byte-behavior (document pass off by default).
"""

import argparse
import json

from memory_machine.cli import cmd_graph
from memory_machine.documents import documents_dir
from memory_machine.graph import (
    GraphStore,
    build_graph,
    document_view,
    explain_relation,
    noop_extractor,
)
from memory_machine.groups import Manifest
from memory_machine.ingest_document import DocumentRebuildError, ingest_document
from memory_machine.tape import MemoryRecord, Tape

CONTENT = "Kalak crossed the rock. " + "A" * 60 + "B" * 60 + "C" * 60


class WindowExtractor:
    """Deterministic chunk + window extractor (no transport)."""

    name = "winfake"
    version = "v1"

    @property
    def tag(self):
        return "winfake/v1"

    def _result(self, record):
        return {
            "entities": [
                {"name": "Kalak", "type": "character"},
                {"name": "rock", "type": "object"},
            ],
            "relations": [
                {"source": "Kalak", "relation": "crossed", "target": "rock",
                 "confidence": 0.9},
            ],
            "mentions": ["Kalak"],
        }

    def extract(self, record):
        return self._result(record)

    def extract_batch(self, records):
        return {r.id: self._result(r) for r in records}

    def extract_window(self, window):
        first, last = window.members[0], window.members[-1]
        return {
            "entities": [
                {"name": "Kalak", "type": "character"},
                {"name": "rock", "type": "object"},
                {"name": "graph plasticity", "type": "topic"},
            ],
            "relations": [
                {
                    "source": "Kalak",
                    "relation": "influences",
                    "target": "rock",
                    "confidence": 0.8,
                    "evidence": [
                        {"memory_id": first.id, "span": list(first.source_span)},
                        {"memory_id": last.id, "span": list(last.source_span)},
                    ],
                },
            ],
        }


def _env(tmp_path):
    root = tmp_path / "proj"
    root.mkdir(exist_ok=True)
    tape = Tape(root / "tape.jsonl")
    manifest = Manifest(capacity=50)
    src = root / "novella.txt"
    store = GraphStore(root / "graph")
    return root, tape, manifest, src, store


def _ingest(root, tape, manifest, src, store, extractor, level="both"):
    return ingest_document(
        tape, manifest, src, chunk_size=40, overlap=0,
        store=store, extractor=extractor, enable_graph=True,
        structure_level=level, window_chars=400,
    )


def _rows(store):
    key = lambda x: json.dumps(x, sort_keys=True)  # noqa: E731

    def drop_time(obj):
        for field in ("created_at", "updated_at", "built_at"):
            obj.pop(field, None)
        return obj

    return {
        "entities": json.dumps(
            sorted((drop_time(e.to_dict()) for e in store.entities()), key=key), sort_keys=True),
        "relations": json.dumps(
            sorted((drop_time(r.to_dict()) for r in store.relations()), key=key), sort_keys=True),
        "mentions": json.dumps(
            sorted((drop_time(m.to_dict()) for m in store.mentions()), key=key), sort_keys=True),
        "documents": json.dumps(
            sorted((drop_time(d.to_dict()) for d in store.documents()), key=key), sort_keys=True),
    }


def _snapshot(store):
    return {**store.counts(), **_rows(store)}


def _fresh_store_with_registry(tmp_path, source_store):
    fresh = GraphStore(tmp_path / "graph_fresh")
    fresh.copy_documents_from(source_store)
    return fresh


# ------------------------------------------------------------- scenario 1


def test_ingest_preserves_original_with_hash(tmp_path):
    root, tape, manifest, src, store = _env(tmp_path)
    src.write_text(CONTENT)
    _ingest(root, tape, manifest, src, store, WindowExtractor())

    preserved = documents_dir(root) / "novella.txt"
    assert preserved.exists()
    doc = store.document_by_source(store.documents()[0].source)
    assert doc.original == str(preserved)
    from memory_machine.attachments import _file_hash

    assert _file_hash(preserved.read_text().strip()) == doc.hash


# ------------------------------------------------------------- scenario 2


def test_round_trip_rebuild_reproduces_projection(tmp_path):
    root, tape, manifest, src, store = _env(tmp_path)
    src.write_text(CONTENT)
    _ingest(root, tape, manifest, src, store, WindowExtractor())
    before = _snapshot(store)
    assert store.counts()["relations"] >= 2  # chunk + document rows

    fresh = _fresh_store_with_registry(tmp_path, store)
    result = build_graph(
        tape, fresh, WindowExtractor(), extractor_name="winfake",
        document_structure_level="both", documents_root=root / "documents",
        document_extractor=WindowExtractor(),
        batch_size=8,
    )
    assert result["ok"] is True
    assert result["document"]["applied"] >= 2

    after = _snapshot(fresh)
    assert after["entities"] == before["entities"]
    assert after["relations"] == before["relations"]
    assert after["mentions"] == before["mentions"]
    assert after["documents"] == before["documents"]
    assert fresh.counts()["documents"] == store.counts()["documents"] == 1


# ------------------------------------------------------------- scenarios 3+4


def test_rebuild_fails_explicitly_on_missing_original(tmp_path):
    root, tape, manifest, src, store = _env(tmp_path)
    src.write_text(CONTENT)
    _ingest(root, tape, manifest, src, store, WindowExtractor())
    before = store.counts()
    (root / "documents" / "novella.txt").unlink()

    result = build_graph(
        tape, store, WindowExtractor(), extractor_name="winfake",
        rebuild=True, document_structure_level="both",
        documents_root=root / "documents",
        document_extractor=WindowExtractor(),
    )
    assert result["ok"] is False
    assert "original missing" in result["error"]
    assert result["documents_validated"] is False
    assert store.counts() == before  # previous graph untouched


def test_rebuild_fails_explicitly_on_altered_original(tmp_path):
    root, tape, manifest, src, store = _env(tmp_path)
    src.write_text(CONTENT)
    _ingest(root, tape, manifest, src, store, WindowExtractor())
    preserved = root / "documents" / "novella.txt"
    before = store.counts()
    preserved.write_text(preserved.read_text() + "tampered!")

    result = build_graph(
        tape, store, WindowExtractor(), extractor_name="winfake",
        rebuild=True, document_structure_level="both",
        documents_root=root / "documents",
        document_extractor=WindowExtractor(),
    )
    assert result["ok"] is False
    assert "hash mismatch" in result["error"]
    assert result["documents_validated"] is False
    assert store.counts() == before
    from memory_machine.ingest_document import validate_originals

    try:
        validate_originals(store, root / "documents")
    except DocumentRebuildError:
        pass
    else:
        raise AssertionError("validate_originals must raise DocumentRebuildError")


# ------------------------------------------------------------- scenario 5


def test_rebuild_respects_structure_level(tmp_path):
    root, tape, manifest, src, store = _env(tmp_path)
    src.write_text(CONTENT)
    _ingest(root, tape, manifest, src, store, WindowExtractor())

    chunk_only = _fresh_store_with_registry(tmp_path, store)
    build_graph(
        tape, chunk_only, WindowExtractor(), extractor_name="winfake",
        document_structure_level="chunk", documents_root=root / "documents",
        document_extractor=WindowExtractor(),
    )
    assert {r.extraction_scope for r in chunk_only.relations()} == {"chunk"}

    both = _fresh_store_with_registry(tmp_path, store)
    build_graph(
        tape, both, WindowExtractor(), extractor_name="winfake",
        document_structure_level="both", documents_root=root / "documents",
        document_extractor=WindowExtractor(),
    )
    assert {r.extraction_scope for r in both.relations()} == {"chunk", "document"}


# ------------------------------------------------------------- scenario 6


def test_incremental_rerun_projects_nothing_twice(tmp_path):
    root, tape, manifest, src, store = _env(tmp_path)
    src.write_text(CONTENT)
    _ingest(root, tape, manifest, src, store, WindowExtractor())
    before = store.counts()
    relations_before = [(r.id, r.extraction_scope) for r in store.relations()]

    result = build_graph(
        tape, store, WindowExtractor(), extractor_name="winfake",
        document_structure_level="both", documents_root=root / "documents",
        document_extractor=WindowExtractor(),
    )
    assert result["ok"] is True
    assert result["document"]["applied"] == 0
    assert store.counts() == before
    assert [(r.id, r.extraction_scope) for r in store.relations()] == relations_before


# ------------------------------------------------------------- scenario 7


def test_document_view_filters_windows_and_original(tmp_path):
    root, tape, manifest, src, store = _env(tmp_path)
    src.write_text(CONTENT)
    result = _ingest(root, tape, manifest, src, store, WindowExtractor())
    doc = store.documents()[0]
    chunks = [r for r in tape.read() if r.type == "attachment"]

    view = document_view(store, tape, doc.id, documents_root=root / "documents")
    assert view["ok"] is True
    assert view["document"]["id"] == doc.id
    assert view["original"]["hash_ok"] is True
    assert view["original"]["present"] is True
    assert len(view["chunk_memories"]) == len(chunks)
    assert "windows" in view

    by_source = document_view(store, tape, doc.source, documents_root=root / "documents")
    by_name = document_view(store, tape, src.name, documents_root=root / "documents")
    assert by_source["document"]["id"] == doc.id
    assert by_name["document"]["id"] == doc.id

    mem = document_view(
        store, tape, doc.id, documents_root=root / "documents",
        memory_id=chunks[0].id,
    )
    assert all((r["memory_id"] or "").startswith("D") or
               (r["memory_id"] or "") == chunks[0].id or
               r["source_document"] == doc.source for r in mem["relations"])

    span_view = document_view(
        store, tape, doc.id, documents_root=root / "documents", span="0:200",
    )
    assert span_view["ok"] is True

    bad_span = document_view(store, tape, doc.id, span="oops")
    assert bad_span["ok"] is False
    unknown = document_view(store, tape, "D9999")
    assert unknown["ok"] is False


# ------------------------------------------------------------- scenario 8


def test_explain_shows_all_evidence_and_original_text(tmp_path):
    root, tape, manifest, src, store = _env(tmp_path)
    src.write_text(CONTENT)
    _ingest(root, tape, manifest, src, store, WindowExtractor())

    document_relation = next(
        r for r in store.relations() if r.extraction_scope == "document"
    )
    explained = explain_relation(
        store, tape, document_relation.id, documents_root=root / "documents"
    )
    assert explained["ok"] is True
    assert explained["scope"] == "document"
    assert explained["window"] == document_relation.memory_id  # D####|wNN
    assert len(explained["evidence"]) == 2  # every span, not just the first
    sources = {ev["source"] for ev in explained["evidence"]}
    assert sources == {"original"}  # re-hydrated from documents/novella.txt
    for ev in explained["evidence"]:
        assert ev["text"] in CONTENT
        assert isinstance(ev["span"], list) and len(ev["span"]) == 2
    assert explained["document"]["original"]["hash_ok"] is True
    assert explained["source"]["name"] == "Kalak"
    assert explained["target"]["name"] == "rock"


# ------------------------------------------------------------- scenario 9


def test_durable_explain_contract_unchanged(tmp_path):
    root = tmp_path / "proj"
    root.mkdir(exist_ok=True)
    tape = Tape(root / "tape.jsonl")
    tape.append(MemoryRecord(
        type="decision", summary="Kalak crossed the rock", why="later"
    ))
    store = GraphStore(root / "graph")
    build_graph(tape, store, noop_extractor, extractor_name="noop")
    store.add_entity("Kalak", "character", "M0001", entity_id="E0001")
    store.add_entity("rock", "object", "M0001", entity_id="E0002")
    store.add_relation(
        "E0001", "crossed", "E0002", "M0001", 0.9, relation_id="R0001",
        source_document="", source_span=(), evidence=[{"memory_id": "M0001"}],
    )

    explained = explain_relation(store, tape, "R0001")
    assert explained["ok"] is True
    assert explained["source"]["name"] == "Kalak"
    assert explained["memory"]["id"] == "M0001"
    assert len(explained["evidence"]) == 1
    assert explained["evidence"][0]["memory_id"] == "M0001"
    assert explained["document"] is None  # no document provenance -> no chain


# ------------------------------------------------------------- scenario 10


def test_plain_build_graph_keeps_graph_v3_projection(tmp_path):
    root = tmp_path / "proj"
    root.mkdir(exist_ok=True)
    tape = Tape(root / "tape.jsonl")
    tape.append(MemoryRecord(type="decision", summary="Use Postgres", why="ACID"))
    store = GraphStore(root / "graph")
    store.add_document(
        source="manual.txt#abc123", name="manual.txt", hash="abc123",
        path="manual.txt",
    )

    result = build_graph(tape, store, noop_extractor, extractor_name="noop", rebuild=True)

    assert result["ok"] is True
    assert "document" not in result  # document pass off without doc knobs
    assert store.counts()["documents"] == 1
    assert store.meta()["schema_version"] == 3


# ------------------------------------------------------------- CLI smoke


def _cli_args(root, **kw):
    base = {
        "root": str(root),
        "extractor": "noop",
        "extractor_version": "",
        "action": "document",
        "target": "",
        "target_b": "",
        "rebuild": False,
        "batch_size": 0,
        "batch_max_chars": 0,
        "memory": "",
        "span": "",
        "id": "",
        "accept": False,
        "reject": False,
        "skip": False,
        "depth": 0,
        "top_k": 0,
    }
    base.update(kw)
    return argparse.Namespace(**base)


def test_cli_graph_document_and_explain(tmp_path, capsys):
    root, tape, manifest, src, store = _env(tmp_path)
    src.write_text(CONTENT)
    _ingest(root, tape, manifest, src, store, WindowExtractor())
    doc = store.documents()[0]
    doc_relation = next(r for r in store.relations() if r.extraction_scope == "document")

    assert cmd_graph(_cli_args(root, target=doc.id)) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is True
    assert out["document"]["id"] == doc.id
    assert out["original"]["hash_ok"] is True

    assert cmd_graph(_cli_args(root, action="explain", target=doc_relation.id)) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is True
    assert len(out["evidence"]) == 2

    assert cmd_graph(_cli_args(root, target="D9999")) == 0
    assert json.loads(capsys.readouterr().out)["ok"] is False