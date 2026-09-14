from memory_machine.graph import GraphStore
from memory_machine.graph_resolve import GraphResolver


class FakeEmbedder:
    """Deterministic embeddings: text -> vector table."""

    def __init__(self, table):
        self.table = table

    def embed(self, texts):
        return [self.table.get(text, [0.0, 0.0]) for text in texts]


def _store(tmp_path):
    store = GraphStore(tmp_path / "graph")
    store.add_entity("petronante", "creature", "M0001", entity_id="E0001")
    return store


def test_exact_and_alias_resolution_are_deterministic(tmp_path):
    store = _store(tmp_path)
    store.add_alias("E0001", "the creature", "M0001")
    resolver = GraphResolver()
    resolver.bind(store.index())

    exact = resolver.resolve({"name": "Petronante"})
    assert exact.entity_id == "E0001" and exact.method == "exact"

    alias = resolver.resolve({"name": "The Creature"})
    assert alias.entity_id == "E0001" and alias.method == "alias"


def test_without_embedder_unknown_name_is_new(tmp_path):
    store = _store(tmp_path)
    resolver = GraphResolver()
    resolver.bind(store.index())

    result = resolver.resolve({"name": "criatura"})
    assert result.entity_id == "" and result.method == "new"


def _resolve_with_score(score, tmp_path):
    store = _store(tmp_path)
    vector = [score, (1.0 - score * score) ** 0.5]
    resolver = GraphResolver(
        embedder=FakeEmbedder(
            {"criatura": vector, "petronante creature": [1.0, 0.0]}
        ),
        auto=0.90,
        hypothesis=0.60,
    )
    resolver.bind(store.index())
    return resolver.resolve({"name": "criatura"})


def test_high_confidence_merges_via_embedding(tmp_path):
    result = _resolve_with_score(0.95, tmp_path)
    assert result.entity_id == "E0001"
    assert result.method == "embedding"
    assert result.hypothesis is False
    assert result.confidence >= 0.90


def test_mid_confidence_is_a_hypothesis(tmp_path):
    result = _resolve_with_score(0.75, tmp_path)
    assert result.entity_id == ""
    assert result.hypothesis is True
    assert result.other_id == "E0001"
    assert result.method == "hypothesis"


def test_low_confidence_is_a_new_entity(tmp_path):
    result = _resolve_with_score(0.30, tmp_path)
    assert result.entity_id == "" and result.hypothesis is False


def test_optional_llm_hook_can_promote_a_hypothesis(tmp_path):
    store = _store(tmp_path)

    class Yes:
        def decide(self, name, candidate):
            return True

    resolver = GraphResolver(
        embedder=FakeEmbedder(
            {"criatura": [0.75, 0.6614], "petronante creature": [1.0, 0.0]}
        ),
        llm=Yes(),
    )
    resolver.bind(store.index())

    result = resolver.resolve({"name": "criatura"})
    assert result.entity_id == "E0001" and result.method == "llm"


def test_embedding_failure_falls_back_to_new(tmp_path):
    store = _store(tmp_path)

    class Broken:
        def embed(self, texts):
            raise RuntimeError("ollama down")

    resolver = GraphResolver(embedder=Broken())
    resolver.bind(store.index())
    result = resolver.resolve({"name": "criatura"})
    assert result.entity_id == "" and result.method == "new"
