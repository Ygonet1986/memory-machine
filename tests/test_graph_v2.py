import json

from memory_machine.config import Config
from memory_machine.coordinator import Machine
from memory_machine.graph import GraphStore
from memory_machine.graph_recall import GraphRecall, guard_evidence
from memory_machine.tape import MemoryRecord, Tape

from fakes import FakeClient

NO_ANNOTATIONS = '{"digest":"g","annotations":[],"coverage":"complete","missing":[]}'


def _hub_graph(tmp_path):
    """E0001 Kalak has one direct edge and a noisy path through a hub."""
    store = GraphStore(tmp_path / "graph")
    store.add_entity("Kalak", "person", "M0001", entity_id="E0001")
    store.add_entity("rochedo", "place", "M0001", entity_id="E0002")
    store.add_entity("petronante", "creature", "M0002", entity_id="E0003")
    store.add_entity("user", "person", "M0002", entity_id="E0004")
    store.add_relation("E0001", "cross", "E0002", "M0001", 0.9, relation_id="R0001")
    # noise: Kalak -> user -> petronante (the hub is the intermediate)
    store.add_relation("E0001", "knows", "E0004", "M0002", 0.8, relation_id="R0002")
    store.add_relation("E0004", "found", "E0003", "M0002", 0.8, relation_id="R0003")
    # give the hub enough degree to be a hub at threshold 2 (noisy siblings
    # only reachable by expanding FROM the hub)
    store.add_relation("E0004", "likes", "E0003", "M0003", 0.7, relation_id="R0004")
    return store


def test_hub_cap_records_edge_but_never_expands(tmp_path):
    index = _hub_graph(tmp_path).index()

    with_hub = GraphRecall(index, depth=2, hub_degree=2).recall("Kalak")
    without_hub = GraphRecall(index, depth=2, hub_degree=0).recall("Kalak")

    with_ids = {item.memory_id for item in with_hub.evidence}
    without_ids = {item.memory_id for item in without_hub.evidence}
    assert {"M0001", "M0002"} <= with_ids  # direct edge + edge INTO the hub
    assert "M0003" not in with_ids  # expansion from the hub never happens
    assert "M0003" in without_ids  # unguarded traversal reaches it


def test_seed_that_is_a_hub_is_not_expanded(tmp_path):
    index = _hub_graph(tmp_path).index()

    result = GraphRecall(index, depth=2, hub_degree=2).recall("user")

    assert result.evidence == [] or all(item.via == "mention" for item in result.evidence)


def test_guard_evidence_floor_and_cap(tmp_path):
    index = _hub_graph(tmp_path).index()
    evidence = GraphRecall(index, depth=2, hub_degree=0).recall("Kalak").evidence

    floored = guard_evidence(evidence, min_score=0.85, max_items=0)
    assert [item.memory_id for item in floored] == ["M0001"]

    capped = guard_evidence(evidence, min_score=0.0, max_items=1)
    assert len(capped) == 1
    assert capped[0].score >= evidence[-1].score


def _machine(tmp_path, mode, **flags):
    cfg = Config(
        capacity=50,
        router_enabled=False,
        graph_enabled=True,
        graph_recall_mode=mode,
        **flags,
    )
    machine = Machine(tmp_path, config=cfg, client=FakeClient(lambda m, t: NO_ANNOTATIONS))
    tape = Tape(tmp_path / "tape.jsonl")
    tape.append(MemoryRecord(type="decision", summary="Kalak crossed", why=""))
    tape.append(MemoryRecord(type="lesson", summary="Kalak knows the user", why=""))
    return machine


def _seed_store(machine):
    store = GraphStore(machine.root / machine.config.graph_path)
    store.add_entity("Kalak", "person", "M0001", entity_id="E0001")
    store.add_entity("rochedo", "place", "M0001", entity_id="E0002")
    store.add_entity("petronante", "creature", "M0002", entity_id="E0003")
    store.add_relation("E0001", "cross", "E0002", "M0001", 0.9, relation_id="R0001")
    store.add_relation("E0001", "found", "E0003", "M0002", 0.5, relation_id="R0002")
    return store


def test_guarded_mode_filters_low_score_and_caps(tmp_path):
    machine = _machine(
        tmp_path, "augment_guarded", graph_augment_min_score=0.85, graph_augment_max_items=1
    )
    _seed_store(machine)

    result = machine.recall("Kalak")

    assert result["graph_mode"] == "augment_guarded"
    assert {item["memory_id"] for item in result["annotations"]} == {"M0001"}
    assert {item["memory_id"] for item in result["graph_evidence"]} == {"M0001"}


def test_guarded_mode_leaves_plain_augment_untouched(tmp_path):
    machine = _machine(tmp_path, "augment")
    _seed_store(machine)

    result = machine.recall("Kalak")

    assert {item["memory_id"] for item in result["annotations"]} == {"M0001", "M0002"}


def test_guarded_mode_applies_ranking_weight(tmp_path):
    machine = _machine(
        tmp_path,
        "augment_guarded",
        graph_augment_min_score=0.0,
        graph_augment_max_items=0,
        graph_augment_weight=0.5,
    )
    _seed_store(machine)

    result = machine.recall("Kalak")

    by_id = {item["memory_id"]: item for item in result["annotations"]}
    assert by_id["M0001"]["relevance"] == 0.45  # 0.9 * 0.5, ranked below agents


def test_config_accepts_guarded_mode_and_flags():
    cfg = Config(
        graph_recall_mode="augment_guarded",
        graph_hub_degree=-3,
        graph_augment_min_score=2.0,
        graph_augment_max_items=-1,
        graph_resolver_candidates=0,
    )
    assert cfg.graph_recall_mode == "augment_guarded"
    assert cfg.graph_hub_degree == 0
    assert cfg.graph_augment_min_score == 1.0
    assert cfg.graph_augment_max_items == 0
    assert cfg.graph_resolver_candidates == 1
