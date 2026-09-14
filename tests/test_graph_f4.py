import argparse
import json
import re

from memory_machine.graph import (
    Extraction,
    ExtractorSpec,
    GraphStore,
    build_graph,
    explain_relation,
)
from memory_machine.graph_extract import GraphExtractor
from memory_machine.graph_recall import GraphRecall
from memory_machine.graph_resolve import Resolution
from memory_machine.tape import MemoryRecord, Tape

from fakes import FakeClient, text

PAYLOADS = {
    "M0001": {
        "entities": [
            {"ref": "e1", "name": "Kalak", "type": "person"},
            {"ref": "e2", "name": "rochedo", "type": "place"},
        ],
        "events": [],
        "relations": [
            {"source": "e1", "relation": "cross", "target": "e2", "confidence": 0.9}
        ],
    },
    "M0002": {
        "entities": [
            {"ref": "e1", "name": "Kalak", "type": "person"},
            {"ref": "e3", "name": "petronante", "type": "creature"},
        ],
        "events": [],
        "relations": [
            {"source": "e1", "relation": "find", "target": "e3", "confidence": 0.8}
        ],
    },
    "M0003": {"entities": [{"ref": "e1", "name": "Kalak"}], "events": [], "relations": []},
    "M0004": {
        "entities": [
            {"ref": "e1", "name": "arautos", "type": "organization"},
            {"ref": "e2", "name": "Roshar", "type": "place"},
        ],
        "events": [],
        "relations": [
            {"source": "e1", "relation": "belong_to", "target": "e2", "confidence": 0.7}
        ],
    },
}


def _tape(tmp_path):
    tape = Tape(tmp_path / "tape.jsonl")
    tape.append(MemoryRecord(type="decision", summary="Kalak crossed the rock"))
    tape.append(MemoryRecord(type="lesson", summary="Kalak found a petronante"))
    tape.append(MemoryRecord(type="decision", summary="Kalak returned"))
    tape.append(MemoryRecord(type="build", summary="The arautos belong to Roshar"))
    return tape


def _single_handler(messages, temperature):
    user = text(messages, "user")
    match = re.search(r"\[(M\d+)\]", user)
    memory_id = match.group(1) if match else ""
    item = dict(PAYLOADS.get(memory_id, {"entities": [], "events": [], "relations": []}))
    item["memory_id"] = memory_id
    return json.dumps(item)


def _batch_handler(override=None):
    def handler(messages, temperature):
        system = text(messages, "system")
        if "SEVERAL memory records" not in system:
            return _single_handler(messages, temperature)
        user = text(messages, "user")
        ids = re.findall(r"### \[(M\d+)\]", user)
        records = []
        for memory_id in ids:
            item = dict(
                PAYLOADS.get(memory_id, {"entities": [], "events": [], "relations": []})
            )
            item["memory_id"] = memory_id
            records.append(item)
        payload = {"records": records}
        if override:
            payload = override(payload, ids)
        return json.dumps(payload)

    return handler


def _canonical(store):
    index = store.index()

    def name(entity_id):
        entity = index.entities.get(entity_id)
        return entity.name.lower() if entity else entity_id

    entities = sorted((entity.name.lower(), entity.type) for entity in store.entities())
    relations = sorted(
        (name(r.source), r.relation, name(r.target), r.memory_id)
        for r in store.relations()
        if r.kind not in {"resolution", "hypothesis"}
    )
    mentions = sorted((m.memory_id, name(m.entity_id)) for m in store.mentions())
    return entities, relations, mentions


def _spec(handler):
    extractor = GraphExtractor(FakeClient(handler))
    return extractor, ExtractorSpec(extractor.extract, extractor.version)


def test_batch_equals_single_projection(tmp_path):
    tape = _tape(tmp_path)
    single_store = GraphStore(tmp_path / "single")
    batch_store = GraphStore(tmp_path / "batch")

    single_extractor, single_spec = _spec(_single_handler)
    build_graph(tape, single_store, single_spec, extractor_name="llm")

    batch_extractor, batch_spec = _spec(_batch_handler())
    result = build_graph(
        tape,
        batch_store,
        batch_spec,
        extractor_name="llm",
        batch_size=8,
        batch_fn=batch_extractor.extract_batch,
    )

    assert result["extracted"] == 4
    assert _canonical(single_store) == _canonical(batch_store)


def test_batch_partial_missing_and_unknown_are_safe(tmp_path):
    tape = _tape(tmp_path)
    store = GraphStore(tmp_path / "graph")

    def override(payload, ids):
        payload["records"] = [r for r in payload["records"] if r["memory_id"] != "M0002"]
        payload["records"].append({"memory_id": "M9999", "entities": [{"name": "ghost"}]})
        return payload

    extractor, spec = _spec(_batch_handler(override))
    result = build_graph(
        tape, store, spec, extractor_name="llm", batch_size=8,
        batch_fn=extractor.extract_batch,
    )

    assert result["extracted"] == 3
    assert result["pending"] == 1
    assert [row["memory_id"] for row in store.pending_rows()] == ["M0002"]
    assert not [e for e in store.entities() if e.name.lower() == "ghost"]


def test_batch_duplicate_memory_id_keeps_first(tmp_path):
    tape = _tape(tmp_path)
    store = GraphStore(tmp_path / "graph")

    def override(payload, ids):
        payload["records"].append(
            {"memory_id": "M0001", "entities": [{"name": "impostor", "type": "person"}]}
        )
        return payload

    extractor, spec = _spec(_batch_handler(override))
    build_graph(
        tape, store, spec, extractor_name="llm", batch_size=8,
        batch_fn=extractor.extract_batch,
    )

    assert not [e for e in store.entities() if e.name.lower() == "impostor"]
    assert [e for e in store.entities() if e.name.lower() == "rochedo"]


def test_batch_retry_does_not_duplicate(tmp_path):
    tape = _tape(tmp_path)
    store = GraphStore(tmp_path / "graph")
    extractor, spec = _spec(_batch_handler())

    first = build_graph(
        tape, store, spec, extractor_name="llm", batch_size=8,
        batch_fn=extractor.extract_batch,
    )
    counts = store.counts()
    second = build_graph(
        tape, store, spec, extractor_name="llm", batch_size=8,
        batch_fn=extractor.extract_batch,
    )

    assert first["extracted"] == 4
    assert second["extracted"] == 0 and second["skipped"] == 4
    assert store.counts() == counts


def test_whole_batch_api_failure_pends_everything(tmp_path):
    tape = _tape(tmp_path)
    store = GraphStore(tmp_path / "graph")

    def boom(messages, temperature):
        raise RuntimeError("api down")

    extractor, spec = _spec(boom)
    result = build_graph(
        tape, store, spec, extractor_name="llm", batch_size=8,
        batch_fn=extractor.extract_batch,
    )

    assert result["extracted"] == 0
    assert result["pending"] == 4
    assert len(store.pending_rows()) == 4


def test_batch_size_one_uses_single_transport(tmp_path):
    tape = _tape(tmp_path)
    store = GraphStore(tmp_path / "graph")
    client = FakeClient(_batch_handler())
    extractor = GraphExtractor(client)
    spec = ExtractorSpec(extractor.extract, extractor.version)

    build_graph(
        tape, store, spec, extractor_name="llm", batch_size=1,
        batch_fn=extractor.extract_batch,
    )

    systems = [text(messages, "system") for messages in client.calls]
    assert systems and all("SEVERAL memory records" not in system for system in systems)


def test_chunk_records_respects_both_limits(tmp_path):
    from memory_machine.graph import _chunk_records

    tape = _tape(tmp_path)
    records = tape.read()
    by_size = _chunk_records(records, 2, 0)
    assert [len(batch) for batch in by_size] == [2, 2]

    by_chars = _chunk_records(records, 10, 100)
    assert all(len(batch) >= 1 for batch in by_chars)
    assert sum(len(batch) for batch in by_chars) == len(records)
    assert len(by_chars) > 1


def test_meta_declares_schema_extractor_resolver_and_source(tmp_path):
    tape = _tape(tmp_path)
    store = GraphStore(tmp_path / "graph")
    extractor, spec = _spec(_single_handler)
    build_graph(tape, store, spec, extractor_name="llm")

    meta = store.meta()
    assert meta["schema_version"] == 1
    assert meta["version"] == 1
    assert meta["extractor"] == "llm"
    assert meta["extractor_version"] == "v1"
    assert meta["resolver_version"] == "1.0"
    assert meta["source"]["tape_records_seen"] == 4
    assert meta["source"]["eligible_records"] == 4
    assert meta["source"]["extracted_records"] == 4


def test_failed_rebuild_keeps_the_previous_graph(tmp_path, monkeypatch):
    tape = _tape(tmp_path)
    store = GraphStore(tmp_path / "graph")
    extractor, spec = _spec(_single_handler)
    build_graph(tape, store, spec, extractor_name="llm")
    before = _canonical(store)

    import memory_machine.graph as graph_mod

    def boom(*args, **kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(graph_mod, "_build_into", boom)
    result = build_graph(tape, store, spec, extractor_name="llm", rebuild=True)

    assert result["ok"] is False
    assert "previous graph kept" in result["error"]
    assert _canonical(store) == before


def test_successful_rebuild_swaps_and_updates_meta(tmp_path):
    tape = _tape(tmp_path)
    store = GraphStore(tmp_path / "graph")
    extractor, spec = _spec(_single_handler)
    build_graph(tape, store, spec, extractor_name="llm")
    assert store.entities()

    empty_extractor, empty_spec = _spec(
        lambda messages, temperature: '{"entities":[],"events":[],"relations":[]}'
    )
    result = build_graph(tape, store, empty_spec, extractor_name="llm", rebuild=True)

    assert result["rebuilt"] is True
    assert store.counts()["entities"] == 0
    assert not (tmp_path / "graph.previous").exists()


class _StubResolver:
    def __init__(self, name="criatura", other_id="E0001"):
        self.name = name
        self.other_id = other_id

    def bind(self, index):
        pass

    def resolve(self, spec):
        if spec.get("name", "").lower() == self.name:
            return Resolution(
                entity_id="",
                confidence=0.75,
                method="hypothesis",
                hypothesis=True,
                other_id=self.other_id,
            )
        return None


def _hypothesis_extraction():
    return Extraction.from_obj(
        {
            "entities": [
                {"ref": "e1", "name": "petronante", "type": "creature"},
                {"ref": "e2", "name": "criatura", "type": "creature"},
            ]
        },
        memory_id="M0001",
    )


def _hypothesis_setup(tmp_path):
    tape = Tape(tmp_path / "tape.jsonl")
    tape.append(MemoryRecord(type="decision", summary="A criatura appeared"))
    store = GraphStore(tmp_path / "graph")
    extraction = _hypothesis_extraction()
    result = build_graph(
        tape, store, lambda record: extraction, extractor_name="stub", resolver=_StubResolver()
    )
    assert result["extracted"] == 1
    return tape, store


def test_hypothesis_appears_in_review_and_skip_keeps_open(tmp_path):
    from memory_machine.cli import _graph_review

    _tape_path, store = _hypothesis_setup(tmp_path)
    listing = _graph_review(
        store,
        argparse.Namespace(id="", accept=False, reject=False, skip=False),
    )
    assert listing["count"] == 1
    hypothesis = listing["open"][0]
    assert hypothesis["source_name"] == "criatura"
    assert hypothesis["target_name"] == "petronante"
    assert hypothesis["confidence"] == 0.75

    skipped = _graph_review(
        store,
        argparse.Namespace(id=hypothesis["id"], accept=False, reject=False, skip=True),
    )
    assert skipped["status"] == "open"
    assert _graph_review(
        store, argparse.Namespace(id="", accept=False, reject=False, skip=False)
    )["count"] == 1


def test_accept_creates_merge_alias_without_rewriting_entities(tmp_path):
    from memory_machine.cli import _graph_review

    _tape_path, store = _hypothesis_setup(tmp_path)
    entities_before = len(store.entities())
    relations_before = len(store.relations())

    result = _graph_review(
        store,
        argparse.Namespace(id="H0001", accept=True, reject=False, skip=False),
    )

    assert result["status"] == "accepted"
    assert len(store.entities()) == entities_before
    assert len(store.relations()) == relations_before
    merge = next(a for a in store.aliases() if a.method == "merge")
    assert merge.entity_id == "E0001" and merge.alias.startswith("E")
    index = store.index()
    assert index.canonical(merge.alias) == "E0001"


def test_reject_prevents_representation_after_rebuild(tmp_path):
    _tape_path, store = _hypothesis_setup(tmp_path)
    store.decide_hypothesis("H0001", "reject")
    extraction = _hypothesis_extraction()

    result = build_graph(
        _tape_path, store, lambda record: extraction, extractor_name="stub",
        resolver=_StubResolver(), rebuild=True,
    )

    assert result["extracted"] == 1
    assert store.open_hypotheses() == []
    assert not [r for r in store.relations() if r.kind == "resolution"]


def test_review_never_touches_the_tape(tmp_path):
    from memory_machine.cli import _graph_review

    tape, store = _hypothesis_setup(tmp_path)
    before = (tmp_path / "tape.jsonl").read_bytes()

    _graph_review(store, argparse.Namespace(id="", accept=False, reject=False, skip=False))
    _graph_review(store, argparse.Namespace(id="H0001", accept=True, reject=False, skip=False))

    assert (tmp_path / "tape.jsonl").read_bytes() == before


def test_resolution_edges_are_not_traversed_by_recall(tmp_path):
    _tape_path, store = _hypothesis_setup(tmp_path)
    index = store.index()
    source = next(
        e.id for e in store.entities() if e.name.lower() == "criatura"
    )

    edges = index.edges_of(source)
    assert all(edge.kind != "resolution" for edge in edges)

    result = GraphRecall(index, depth=2).recall("criatura")
    resolution_ids = {
        r.id for r in store.relations() if r.kind in {"resolution", "hypothesis"}
    }
    used = {rid for item in result.evidence for rid in item.relation_ids}
    assert not (used & resolution_ids)


def test_pending_retry_then_extracted_and_failed_stays_auditable(tmp_path):
    from memory_machine.cli import _graph_retry

    tape = _tape(tmp_path)
    store = GraphStore(tmp_path / "graph")
    store.mark_pending("M0001", "api down", extractor="llm/v1", attempts=1)

    extractor, spec = _spec(_single_handler)
    machine = argparse.Namespace(tape=tape, config=argparse.Namespace(graph_max_attempts=3))
    result = _graph_retry(
        store,
        machine,
        spec,
        "llm",
        "llm/v1",
        argparse.Namespace(id=""),
        None,
    )

    assert result["retried"] == 1
    assert result["outcomes"][0]["status"] == "extracted"
    assert store.pending_rows() == []
    assert store.extracted_ids("llm/v1") == {"M0001"}

    store.mark_failed("M0001", "old failure", extractor="llm/v1")
    extracted = explain_relation(
        store, tape, store.relations()[0].id
    )
    assert extracted["ok"] is True
    assert len(store.failed_rows()) == 1  # audit history is append-only
