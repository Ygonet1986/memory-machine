import json

from memory_machine.graph import GraphStore
from memory_machine.graph_recall import GraphRecall


def _base_graph(tmp_path):
    store = GraphStore(tmp_path / "graph")
    store.add_entity("Kalak", "person", "M0001", entity_id="E0001")
    store.add_entity("rochedo", "place", "M0001", entity_id="E0002")
    store.add_entity("petronante", "creature", "M0002", entity_id="E0003")
    store.add_relation("E0001", "cross", "E0002", "M0001", 0.9, relation_id="R0001")
    store.add_relation("E0001", "find", "E0003", "M0002", 0.8, relation_id="R0004")
    store.add_mention("M0003", "E0001", 0.7)
    return store


def _event_only_graph(tmp_path):
    store = GraphStore(tmp_path / "graph")
    store.add_entity("Kalak", "person", "M0001", entity_id="E0001")
    store.add_entity("rochedo", "place", "M0001", entity_id="E0002")
    store.add_entity("cross (M0001)", "event", "M0001", entity_id="E0004")
    store.add_relation(
        "E0004", "agent", "E0001", "M0001", 0.95, kind="event", relation_id="R0002"
    )
    store.add_relation(
        "E0004", "object", "E0002", "M0001", 0.95, kind="event", relation_id="R0003"
    )
    return store


def _chain_graph(tmp_path):
    store = GraphStore(tmp_path / "graph")
    ids = {}
    for index, name in enumerate(["A", "B", "C", "D", "E"], start=1):
        ids[name] = f"E{index:04d}"
        store.add_entity(name, "concept", "M0000", entity_id=ids[name])
    pairs = [("A", "B"), ("B", "C"), ("C", "D"), ("D", "E")]
    for position, (left, right) in enumerate(pairs, start=1):
        store.add_relation(
            ids[left],
            "link",
            ids[right],
            f"M00{9 + position}",
            0.9,
            relation_id=f"R00{9 + position}",
        )
    return store


class FakeEmbedder:
    def __init__(self, table):
        self.table = table

    def embed(self, texts):
        return [self.table.get(text, [0.0, 0.0]) for text in texts]


def test_query_resolution_ignores_unknown_words(tmp_path):
    recall = GraphRecall(_base_graph(tmp_path).index(), depth=2)

    result = recall.recall("por que escolhemos Kalak para o rochedo?")

    assert result.seeds == ["E0001", "E0002"]
    assert "R0001" == result.evidence[0].relation_ids[0]
    assert result.evidence[0].memory_id == "M0001"


def test_unknown_entity_returns_empty(tmp_path):
    recall = GraphRecall(_base_graph(tmp_path).index(), depth=2)

    result = recall.recall("zzz nao existe")

    assert result.seeds == []
    assert result.evidence == []
    assert result.metrics()["graph_seed_entities"] == 0


def test_alias_resolves_entity(tmp_path):
    store = _base_graph(tmp_path)
    store.add_alias("E0001", "the king", "M0003")
    recall = GraphRecall(store.index(), depth=2)

    result = recall.recall("the king")

    assert result.seeds == ["E0001"]


def test_mention_only_evidence(tmp_path):
    recall = GraphRecall(_base_graph(tmp_path).index(), depth=2)

    result = recall.recall("Kalak")

    mention = next(item for item in result.evidence if item.memory_id == "M0003")
    assert mention.via == "mention"
    assert mention.score == 0.7


def test_event_is_one_semantic_hop(tmp_path):
    recall = GraphRecall(_event_only_graph(tmp_path).index(), depth=1)

    result = recall.recall("Kalak")

    assert result.seeds == ["E0001"]
    assert [item.memory_id for item in result.evidence] == ["M0001"]
    assert sorted(result.evidence[0].relation_ids) == ["R0002", "R0003"]
    assert result.evidence[0].paths[0].semantic_depth == 1


def test_adversarial_depth_two_never_reaches_the_fifth_node(tmp_path):
    recall = GraphRecall(_chain_graph(tmp_path).index(), depth=2)

    result = recall.recall("A")

    memories = {item.memory_id for item in result.evidence}
    assert {"M0010", "M0011"} <= memories
    assert "M0013" not in memories
    assert "M0014" not in memories


def test_depth_limits_are_respected(tmp_path):
    graph = _chain_graph(tmp_path).index()

    depth_three = GraphRecall(graph, depth=3).recall("A")
    depth_four = GraphRecall(graph, depth=4).recall("A")

    assert "M0012" in {item.memory_id for item in depth_three.evidence}
    assert "M0013" not in {item.memory_id for item in depth_three.evidence}
    assert "M0013" in {item.memory_id for item in depth_four.evidence}


def test_relation_provenance_maps_to_memory(tmp_path):
    index = _base_graph(tmp_path).index()
    recall = GraphRecall(index, depth=2)

    result = recall.recall("Kalak")

    for item in result.evidence:
        for relation_id in item.relation_ids:
            assert index.relations[relation_id].memory_id == item.memory_id


def test_parallel_relations_become_two_evidences(tmp_path):
    store = _base_graph(tmp_path)
    store.add_relation("E0001", "watch", "E0003", "M0009", 0.7, relation_id="R0009")
    recall = GraphRecall(store.index(), depth=1)

    result = recall.recall("Kalak")

    assert "M0009" in {item.memory_id for item in result.evidence}


def test_same_memory_multiple_relations_is_deduped(tmp_path):
    store = _base_graph(tmp_path)
    store.add_relation("E0001", "guard", "E0002", "M0001", 0.6, relation_id="R0010")
    recall = GraphRecall(store.index(), depth=1)

    result = recall.recall("Kalak")

    m0001 = [item for item in result.evidence if item.memory_id == "M0001"]
    assert len(m0001) == 1
    assert "R0001" in m0001[0].relation_ids and "R0010" in m0001[0].relation_ids


def test_top_k_trims_evidence(tmp_path):
    store = _base_graph(tmp_path)
    for index in range(5, 12):
        store.add_relation("E0001", "touch", "E0003", f"M00{index}", 0.5, relation_id=f"R00{index}")
    recall = GraphRecall(store.index(), depth=1, top_k=3)

    result = recall.recall("Kalak")

    assert len(result.evidence) == 3


def test_paths_are_explainable(tmp_path):
    recall = GraphRecall(_base_graph(tmp_path).index(), depth=2)

    result = recall.recall("Kalak")
    label = result.evidence[0].label
    path = result.evidence[0].paths[0]

    assert "Kalak" in label and "rochedo" in label
    assert path.nodes and path.relations
    assert path.score <= 1.0


def test_metrics_are_recorded(tmp_path):
    recall = GraphRecall(_base_graph(tmp_path).index(), depth=2)

    metrics = recall.recall("Kalak").metrics()

    assert set(metrics) == {
        "graph_seed_entities",
        "graph_paths_considered",
        "graph_paths_selected",
        "graph_unique_memories",
        "graph_recall_ms",
    }
    assert metrics["graph_seed_entities"] == 1
    assert metrics["graph_paths_considered"] >= 1


def test_embedding_fallback_seeds_entities(tmp_path):
    index = _base_graph(tmp_path).index()
    embedder = FakeEmbedder(
        {"hero": [0.98, 0.2], "Kalak person": [1.0, 0.0], "rochedo place": [0.0, 1.0]}
    )
    recall = GraphRecall(index, embedder=embedder, depth=2)

    result = recall.recall("hero")

    assert result.seeds == ["E0001"]
    assert result.evidence


def test_deterministic_match_wins_over_embedding(tmp_path):
    index = _base_graph(tmp_path).index()
    embedder = FakeEmbedder({"Kalak": [0.98, 0.2], "Kalak person": [0.0, 1.0]})
    recall = GraphRecall(index, embedder=embedder, depth=2)

    assert recall.recall("Kalak").seeds == ["E0001"]


def test_index_paths_returns_direct_and_via_event(tmp_path):
    index = _base_graph(tmp_path).index()

    trails = index.paths("E0001", "E0002", max_depth=3, limit=5)

    assert any(len(trail) == 1 for trail in trails)


def test_paths_method_in_event_only_graph(tmp_path):
    index = _event_only_graph(tmp_path).index()

    trails = index.paths("E0001", "E0002", max_depth=3, limit=5)

    assert trails and len(trails[0]) == 2
    assert {relation.relation for relation in trails[0]} == {"agent", "object"}


def test_corrupt_relation_line_is_ignored(tmp_path):
    store = _base_graph(tmp_path)
    with (store.directory / "relations.jsonl").open("a", encoding="utf-8") as handle:
        handle.write("not json at all\n")
    recall = GraphRecall(store.index(), depth=2)

    result = recall.recall("Kalak")

    assert result.evidence


def test_empty_graph_returns_empty(tmp_path):
    recall = GraphRecall(GraphStore(tmp_path / "graph").index(), depth=2)

    result = recall.recall("anything")

    assert result.seeds == [] and result.evidence == []


def test_cli_query_and_path(tmp_path, capsys):
    import argparse

    from memory_machine import cli
    from memory_machine.config import Config
    from memory_machine.coordinator import Machine

    _base_graph(tmp_path)
    Machine(tmp_path, config=Config(graph_enabled=True), client=None)

    query_args = argparse.Namespace(
        root=str(tmp_path), action="query", target="Kalak", target_b="",
        extractor="", rebuild=False, depth=0, top_k=0,
    )
    assert cli.cmd_graph(query_args) == 0
    query_out = json.loads(capsys.readouterr().out)
    assert query_out["ok"] is True
    assert query_out["entities"][0]["name"] == "Kalak"
    assert query_out["evidence"][0]["memory_id"] == "M0001"
    assert query_out["evidence"][0]["path_details"][0]["memory_id"] == "M0001"

    path_args = argparse.Namespace(
        root=str(tmp_path), action="path", target="Kalak", target_b="rochedo",
        extractor="", rebuild=False, depth=0, top_k=0,
    )
    assert cli.cmd_graph(path_args) == 0
    path_out = json.loads(capsys.readouterr().out)
    assert path_out["ok"] is True
    assert path_out["source"]["id"] == "E0001"
    assert path_out["evidence"] == ["M0001"]
    assert path_out["paths"][0]["detail"][0]["relation"] == "cross"
