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


class CountingEmbedder:
    def __init__(self, table):
        self.table = table
        self.calls = 0
        self.texts = 0

    def embed(self, texts):
        self.calls += 1
        self.texts += len(texts)
        return [self.table.get(text, [0.0, 0.0]) for text in texts]


def _cache_index(tmp_path):
    store = GraphStore(tmp_path / "graph")
    store.add_entity("petronante", "creature", "M0001", entity_id="E0001")
    store.add_entity("rochedo", "place", "M0002", entity_id="E0002")
    store.add_entity("kalak", "person", "M0003", entity_id="E0003")
    return store.index()


def test_vector_cache_removes_recomputation_without_changing_resolutions(tmp_path):
    table = {
        "criatura": [0.95, 0.31],
        "criatura2": [0.9, 0.4],
        "petronante creature": [1.0, 0.0],
        "rochedo place": [0.0, 1.0],
        "kalak person": [0.7, 0.7],
    }
    index = _cache_index(tmp_path)
    cached = GraphResolver(embedder=CountingEmbedder(table))
    cached.bind(index)
    first = cached.resolve({"name": "criatura"})
    texts_after_first = cached.embedder.texts
    second = cached.resolve({"name": "criatura2"})

    fresh = GraphResolver(embedder=CountingEmbedder(table))
    fresh.bind(index)
    first_fresh = fresh.resolve({"name": "criatura"})

    assert (first.entity_id, first.method) == (first_fresh.entity_id, first_fresh.method)
    # first resolution embeds the query + all candidate docs; the second only
    # needs the query because the docs are cached
    assert texts_after_first == 1 + 3
    assert cached.embedder.texts - texts_after_first == 1
    assert second.method in {"exact", "alias", "embedding", "hypothesis", "new"}


def test_resolve_batch_equals_single_and_uses_one_call(tmp_path):
    table = {
        "criatura": [0.95, 0.31],
        "criatura2": [0.9, 0.4],
        "criatura3": [0.2, 0.98],
        "petronante creature": [1.0, 0.0],
        "rochedo place": [0.0, 1.0],
        "kalak person": [0.7, 0.7],
    }
    index = _cache_index(tmp_path)
    specs = [
        {"name": "criatura"},
        {"name": "criatura2"},
        {"name": "criatura3"},
        {"name": "rochedo"},  # exact match: never reaches the embedder
    ]

    single = GraphResolver(embedder=CountingEmbedder(table))
    single.bind(index)
    singles = [single.resolve(spec) for spec in specs]

    batch = GraphResolver(embedder=CountingEmbedder(table))
    batch.bind(index)
    batched = batch.resolve_batch(specs)

    def fingerprint(resolution):
        return (
            resolution.entity_id,
            resolution.method,
            resolution.hypothesis,
            resolution.other_id,
            round(resolution.confidence, 6),
        )

    assert [fingerprint(r) for r in batched] == [fingerprint(r) for r in singles]
    assert batch.embedder.calls == 1  # every unknown name in one request
    assert single.embedder.calls == 3
