import json

from memory_machine.config import Config
from memory_machine.coordinator import Machine
from memory_machine.graph import (
    ExtractorSpec,
    GraphStore,
    TransientExtractionError,
    apply_record_extraction,
    build_graph,
)
from memory_machine.graph_extract import GraphExtractor
from memory_machine.tape import MemoryRecord, Tape

from fakes import FakeClient

EXTRACT_PAYLOAD = json.dumps(
    {
        "entities": [{"ref": "e1", "name": "Kalak", "type": "person"}],
        "events": [],
        "relations": [],
    }
)


def _client():
    return FakeClient(lambda messages, temperature: EXTRACT_PAYLOAD)


def _machine(tmp_path, *, enabled=True, client=None):
    return Machine(
        tmp_path,
        config=Config(capacity=50, router_enabled=False, graph_enabled=enabled),
        client=client or _client(),
    )


def _store(machine):
    return GraphStore(machine.root / machine.config.graph_path)


def test_graph_disabled_makes_no_projection_and_no_calls(tmp_path):
    client = _client()
    machine = _machine(tmp_path, enabled=False, client=client)

    machine.add_memory(MemoryRecord(type="decision", summary="Kalak crossed the rock"))

    assert not _store(machine).exists()
    assert client.calls == []


def test_write_time_extracts_durable_memory(tmp_path):
    machine = _machine(tmp_path)

    out = machine.add_memory(MemoryRecord(type="decision", summary="Kalak crossed the rock"))

    store = _store(machine)
    assert store.exists()
    assert [e.name for e in store.entities()] == ["Kalak"]
    assert store.extracted_ids("llm/v1") == {out["record"]["id"]}
    assert store.meta()["extractor"] == "llm"


def test_same_entity_across_two_memories_is_deduplicated(tmp_path):
    machine = _machine(tmp_path)

    machine.add_memory(MemoryRecord(type="decision", summary="Kalak crossed the rock"))
    machine.add_memory(MemoryRecord(type="lesson", summary="Kalak learned to swim"))

    store = _store(machine)
    assert len(store.entities()) == 1
    assert len(store.extracted_ids("llm/v1")) == 2


def test_write_time_and_build_are_idempotent(tmp_path):
    machine = _machine(tmp_path)
    machine.add_memory(MemoryRecord(type="decision", summary="Kalak crossed the rock"))
    store = _store(machine)
    before = store.counts()

    extractor = GraphExtractor(machine.client)
    result = build_graph(
        machine.tape,
        store,
        ExtractorSpec(extractor.extract, extractor.version),
        extractor_name="llm",
    )

    assert result["extracted"] == 0 and result["skipped"] == 1
    assert store.counts() == before


def test_projection_never_touches_the_tape_bytes(tmp_path):
    machine = _machine(tmp_path)
    machine.add_memory(MemoryRecord(type="decision", summary="Kalak crossed the rock"))
    first_line = (tmp_path / "tape.jsonl").read_bytes().splitlines()[0]

    record = machine.tape.read()[0]
    extractor = GraphExtractor(machine.client)
    apply_record_extraction(
        _store(machine),
        record,
        extractor.extract,
        tag=extractor.tag,
        extractor_name=extractor.name,
        extractor_version=extractor.version,
    )

    assert (tmp_path / "tape.jsonl").read_bytes().splitlines()[0] == first_line


def test_api_failure_keeps_the_tape_and_pends(tmp_path):
    def boom(messages, temperature):
        raise RuntimeError("api down")

    machine = _machine(tmp_path, client=FakeClient(boom))

    out = machine.add_memory(MemoryRecord(type="decision", summary="Kalak crossed the rock"))

    assert [r.id for r in machine.tape.read()] == [out["record"]["id"]]
    store = _store(machine)
    assert store.extracted_ids("llm/v1") == set()
    assert [p["memory_id"] for p in store.pending_rows("llm/v1")] == [out["record"]["id"]]


def test_pending_becomes_failed_after_max_attempts(tmp_path):
    tape = Tape(tmp_path / "tape.jsonl")
    record = tape.append(MemoryRecord(type="decision", summary="x"))
    store = GraphStore(tmp_path / "graph")

    def always_fail(record):
        raise TransientExtractionError("api down")

    for _ in range(3):
        apply_record_extraction(
            store,
            record,
            always_fail,
            tag="llm/v1",
            extractor_name="llm",
            extractor_version="v1",
            max_attempts=3,
        )

    assert store.pending_rows("llm/v1") == []
    assert [row["memory_id"] for row in store.failed_rows()] == [record.id]


def test_checkpoint_extracts_explicit_memory_and_ignores_the_turn(tmp_path):
    machine = _machine(tmp_path)

    machine.checkpoint(
        "what did we decide?",
        "we decided to cross the rock",
        memories=[{"type": "decision", "summary": "Kalak crossed the rock"}],
    )

    store = _store(machine)
    extracted = store.extracted_ids("llm/v1")
    assert "M0001" in extracted
    turn = machine.tape.read()[-1]
    assert turn.type == "memory"
    assert turn.id not in extracted


def test_attachment_is_not_extracted(tmp_path):
    machine = _machine(tmp_path)
    src = tmp_path / "spec.txt"
    src.write_text("Kalak crossed the rock")

    machine.attach(src)

    assert not _store(machine).exists()


def test_rollup_record_is_not_extracted(tmp_path):
    machine = _machine(tmp_path)
    for i in range(3):
        machine.add_memory(MemoryRecord(type="decision", summary=f"decision {i}"))
    extracted_before = _store(machine).extracted_ids("llm/v1")

    result = machine.rollup(keep_recent=1)

    extracted = _store(machine).extracted_ids("llm/v1")
    assert str(result["rollup_id"]) not in extracted
    assert len(extracted_before) == 3


EVENT_PAYLOAD = json.dumps(
    {
        "entities": [
            {"ref": "e1", "name": "Kalak", "type": "person"},
            {"ref": "e2", "name": "rochedo", "type": "object"},
        ],
        "events": [
            {"ref": "ev1", "action": "cross", "agent": "e1", "object": "e2", "confidence": 0.9}
        ],
        "relations": [],
    }
)


def test_event_projects_into_event_entity_and_edges(tmp_path):
    machine = _machine(tmp_path, client=FakeClient(lambda m, t: EVENT_PAYLOAD))

    machine.add_memory(MemoryRecord(type="decision", summary="Kalak crossed the rock"))

    store = _store(machine)
    by_name = {e.name: e for e in store.entities()}
    assert by_name["Kalak"].type == "person"
    assert by_name["rochedo"].type == "object"
    assert by_name["cross"].type == "action"
    event_entity = by_name["cross (M0001)"]
    assert event_entity.type == "event"

    relations = store.relations()
    assert {(r.relation, r.kind) for r in relations} == {
        ("action", "event"),
        ("agent", "event"),
        ("object", "event"),
    }
    assert all(r.source == event_entity.id for r in relations)
    assert all(r.extractor == "llm" and r.extractor_version == "v1" for r in relations)
    assert all(r.memory_id == "M0001" for r in relations)


def test_rebuild_converges_with_write_time(tmp_path):
    def extractor_fn(record):
        return {"entities": [{"ref": "e1", "name": "Kalak", "type": "person"}], "relations": []}

    machine = _machine(
        tmp_path, client=FakeClient(lambda m, t: json.dumps(extractor_fn(None)))
    )
    machine.add_memory(MemoryRecord(type="decision", summary="Kalak crossed the rock"))
    store = _store(machine)
    before = sorted((e.name, e.type) for e in store.entities())

    store.clear()
    result = build_graph(
        machine.tape, store, extractor_fn, extractor_name="llm"
    )

    after = sorted((e.name, e.type) for e in store.entities())
    assert result["extracted"] == 1
    assert after == before == [("Kalak", "person")]


def test_resolver_hypothesis_and_alias_merge_at_projection_level(tmp_path):
    from memory_machine.graph import Extraction, normalize_name
    from memory_machine.graph_resolve import Resolution

    machine = _machine(tmp_path)  # hook extracts "Kalak"
    machine.add_memory(MemoryRecord(type="decision", summary="Kalak crossed the rock"))
    store = _store(machine)
    kalak = next(e for e in store.entities() if e.name == "Kalak")

    class StubResolver:
        def __init__(self, resolution):
            self.resolution = resolution

        def bind(self, index):
            pass

        def resolve(self, spec):
            return self.resolution if spec.get("name") in {"criatura", "kallak"} else None

    hypothesis_record = machine.tape.append(
        MemoryRecord(type="decision", summary="criatura appeared")
    )
    hypothesis = Extraction.from_obj(
        {"entities": [{"ref": "e1", "name": "criatura", "type": "creature"}]},
        memory_id=hypothesis_record.id,
    )
    apply_record_extraction(
        store,
        hypothesis_record,
        lambda record: hypothesis,
        tag="stub/v1",
        extractor_name="stub",
        extractor_version="v1",
        resolver=StubResolver(
            Resolution(
                entity_id="",
                confidence=0.75,
                method="hypothesis",
                hypothesis=True,
                other_id=kalak.id,
            )
        ),
    )
    edges = [r for r in store.relations() if r.kind == "hypothesis"]
    criatura = next(e for e in store.entities() if e.name == "criatura")
    assert len(edges) == 1
    assert edges[0].relation == "possibly_same_as"
    assert edges[0].source == criatura.id and edges[0].target == kalak.id

    merge_record = machine.tape.append(
        MemoryRecord(type="decision", summary="kallak appeared again")
    )
    merge = Extraction.from_obj(
        {"entities": [{"ref": "e1", "name": "kallak", "type": "person"}]},
        memory_id=merge_record.id,
    )
    apply_record_extraction(
        store,
        merge_record,
        lambda record: merge,
        tag="stub/v1",
        extractor_name="stub",
        extractor_version="v1",
        resolver=StubResolver(
            Resolution(entity_id=kalak.id, confidence=0.95, method="embedding")
        ),
    )
    assert not [e for e in store.entities() if normalize_name(e.name) == "kallak"]
    assert any(
        a.alias == "kallak" and a.entity_id == kalak.id and a.method == "embedding"
        for a in store.aliases()
    )
