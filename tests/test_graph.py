import json

from memory_machine.graph import (
    DURABLE_TYPES,
    ExtractorSpec,
    GraphStore,
    build_graph,
    explain_relation,
    graph_status,
    normalize_name,
    parse_types,
)
from memory_machine.tape import MemoryRecord, Tape


def _tape(tmp_path):
    tape = Tape(tmp_path / "tape.jsonl")
    tape.append(
        MemoryRecord(type="decision", summary="Kalak crossed the rock", why="at dusk")
    )
    tape.append(
        MemoryRecord(type="decision", summary="Kalak found a petronante", why="later")
    )
    tape.append(MemoryRecord(type="memory", summary="turn record about Kalak"))
    tape.append(MemoryRecord(type="attachment", summary="attached text about Kalak"))
    return tape


def fake_extractor(record):
    if "crossed" in record.summary:
        return {
            "entities": [
                {"name": "Kalak", "type": "character", "aliases": ["the king"]},
                {"name": "rock", "type": "object"},
            ],
            "relations": [
                {"source": "Kalak", "relation": "crossed", "target": "rock", "confidence": 0.9}
            ],
        }
    if "found" in record.summary:
        return {
            "entities": [
                {"name": "kalak", "type": "character"},
                {"name": "petronante", "type": "creature", "aliases": ["the creature"]},
            ],
            "relations": [
                {
                    "source": "Kalak",
                    "relation": "found",
                    "target": "petronante",
                    "confidence": 0.8,
                }
            ],
        }
    return {"entities": [], "relations": []}


def _store(tmp_path):
    return GraphStore(tmp_path / "graph")


def test_normalize_name_and_parse_types():
    assert normalize_name("  Kalák, o Rei! ") == "kalak o rei"
    assert normalize_name("A-B_c") == "a b c"
    assert parse_types(" Decision , ,Lesson ") == {"decision", "lesson"}


def test_build_creates_projection_with_provenance(tmp_path):
    tape = _tape(tmp_path)
    store = _store(tmp_path)
    result = build_graph(tape, store, fake_extractor, extractor_name="fake")

    assert result["ok"] is True
    assert result["extracted"] == 2  # only the two durable decisions
    entities = {e.name.lower(): e for e in store.entities()}
    assert {"kalak", "rock", "petronante"} <= set(entities)
    relations = store.relations()
    assert {r.relation for r in relations} == {"crossed", "found"}
    assert all(r.memory_id in {"M0001", "M0002"} for r in relations)
    assert entities["kalak"].id == entities["kalak"].id
    mentions = store.mentions()
    assert {m.memory_id for m in mentions} == {"M0001", "M0002"}
    assert store.meta()["extractor"] == "fake"


def test_entities_dedupe_by_normalized_name(tmp_path):
    tape = _tape(tmp_path)
    store = _store(tmp_path)
    build_graph(tape, store, fake_extractor, extractor_name="fake")

    kalak_ids = [e.id for e in store.entities() if normalize_name(e.name) == "kalak"]
    assert len(kalak_ids) == 1
    assert {r.source for r in store.relations()} == {kalak_ids[0]}


def test_extract_types_filter_skips_turns_and_attachments(tmp_path):
    tape = _tape(tmp_path)
    store = _store(tmp_path)
    build_graph(tape, store, fake_extractor, extractor_name="fake")

    assert store.extracted_ids("fake/v1") == {"M0001", "M0002"}
    assert not any(m.memory_id in {"M0003", "M0004"} for m in store.mentions())


def test_build_is_idempotent_per_extractor_tag(tmp_path):
    tape = _tape(tmp_path)
    store = _store(tmp_path)
    first = build_graph(tape, store, ExtractorSpec(fake_extractor, "v1"), extractor_name="fake")
    second = build_graph(tape, store, ExtractorSpec(fake_extractor, "v1"), extractor_name="fake")

    assert first["extracted"] == 2
    assert second["extracted"] == 0
    assert second["skipped"] == 2
    assert len(store.entities()) == first["counts"]["entities"]

    third = build_graph(tape, store, ExtractorSpec(fake_extractor, "v2"), extractor_name="fake")
    assert third["extracted"] == 2  # a new extractor version re-extracts


def test_rebuild_discards_the_old_projection(tmp_path):
    tape = _tape(tmp_path)
    store = _store(tmp_path)
    build_graph(tape, store, fake_extractor, extractor_name="fake")
    assert store.entities()

    rebuilt = build_graph(
        tape, store, lambda record: {"entities": [], "relations": []},
        rebuild=True, extractor_name="empty",
    )
    assert rebuilt["counts"]["entities"] == 0
    assert store.entities() == []


def test_failed_extractor_is_recorded_and_retried(tmp_path):
    tape = _tape(tmp_path)
    store = _store(tmp_path)

    def broken(record):
        raise RuntimeError("boom")

    result = build_graph(tape, store, broken, extractor_name="broken")
    assert result["failed"] == 2
    assert len(store.failed_rows()) == 2
    assert store.extracted_ids("broken/v1") == set()

    retried = build_graph(tape, store, fake_extractor, extractor_name="fake")
    assert retried["extracted"] == 2


def test_resolver_hook_merges_entities(tmp_path):
    tape = _tape(tmp_path)
    store = _store(tmp_path)
    build_graph(tape, store, fake_extractor, extractor_name="fake")
    existing = next(e.id for e in store.entities() if normalize_name(e.name) == "kalak")

    class Resolver:
        def resolve(self, spec):
            return existing if normalize_name(spec["name"]) == "kallak" else ""

    tape.append(MemoryRecord(type="decision", summary="Kallak spoke"))
    result = build_graph(
        tape, store, fake_extractor, extractor_name="fake", resolver=Resolver()
    )
    assert result["extracted"] == 1
    assert len([e for e in store.entities() if normalize_name(e.name) == "kallak"]) == 0


def test_traversal_path_and_evidence(tmp_path):
    tape = _tape(tmp_path)
    store = _store(tmp_path)
    build_graph(tape, store, fake_extractor, extractor_name="fake")
    index = store.index()
    kalak = index.resolve("Kalak")
    rock = index.resolve("rock")
    petronante = index.resolve("petronante")

    assert kalak and rock and petronante
    neighbors = index.neighbors(kalak, depth=1)
    assert {other for _rel, other, _conf in neighbors} == {rock, petronante}
    trail = index.path(rock, petronante, max_depth=2)
    assert trail is not None and len(trail) == 2
    scores = index.evidence_ids([rock], depth=2)
    assert scores.get("M0001") == 0.9
    assert index.neighbors(kalak, depth=1, min_confidence=0.85)[0][0].relation == "crossed"


def test_explain_returns_memory_and_entities(tmp_path):
    tape = _tape(tmp_path)
    store = _store(tmp_path)
    build_graph(tape, store, fake_extractor, extractor_name="fake")
    relation = next(r for r in store.relations() if r.relation == "crossed")

    explained = explain_relation(store, tape, relation.id)
    assert explained["ok"] is True
    assert explained["source"]["name"] == "Kalak"
    assert explained["target"]["name"] == "rock"
    assert explained["memory"]["id"] == "M0001"
    assert explained["memory"]["summary"] == "Kalak crossed the rock"

    assert explain_relation(store, tape, "R9999")["ok"] is False


def test_status_reports_pending_for_tag(tmp_path):
    tape = _tape(tmp_path)
    store = _store(tmp_path)
    build_graph(tape, store, ExtractorSpec(fake_extractor, "v1"), extractor_name="fake")

    status = graph_status(store, tape, extractor_tag="fake/v1")
    assert status["built"] is True
    assert status["pending"] == 0
    status_v2 = graph_status(store, tape, extractor_tag="fake/v2")
    assert status_v2["pending"] == 2


def test_build_never_writes_to_the_tape(tmp_path):
    tape = _tape(tmp_path)
    before = (tmp_path / "tape.jsonl").read_bytes()
    build_graph(tape, _store(tmp_path), fake_extractor, extractor_name="fake", rebuild=True)
    assert (tmp_path / "tape.jsonl").read_bytes() == before


def test_store_files_are_append_only_jsonl(tmp_path):
    tape = _tape(tmp_path)
    store = _store(tmp_path)
    build_graph(tape, store, fake_extractor, extractor_name="fake")

    for name in ("entities.jsonl", "relations.jsonl", "mentions.jsonl", "extracted.jsonl"):
        lines = (store.directory / name).read_text(encoding="utf-8").splitlines()
        assert lines and all(json.loads(line) for line in lines)
    meta = json.loads((store.directory / "meta.json").read_text(encoding="utf-8"))
    assert meta["counts"]["entities"] >= 3
    assert sorted(meta["extract_types"]) == sorted(DURABLE_TYPES)
