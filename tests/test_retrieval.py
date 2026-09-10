from memory_machine.retrieval import bm25, cosine, rank, tokenize


def test_tokenize_filters_stopwords_and_short():
    assert tokenize("the database is up") == ["database"]


def test_rank_orders_by_relevance():
    docs = [
        "PostgreSQL is the primary database",
        "Redis is an in-memory cache",
        "gardening tomatoes in summer",
    ]
    hits = rank("which database should we use", docs)
    assert hits
    assert hits[0][0] == 0


def test_rank_no_match_returns_empty():
    assert rank("zzzzzz", ["hello world", "another doc"]) == []


def test_bm25_zero_without_overlap():
    assert bm25("xyz", ["abc def"]) == [0.0]


def test_cosine():
    assert cosine([1, 0], [1, 0]) == 1.0
    assert cosine([1, 0], [0, 1]) == 0.0
    assert cosine([], [1]) == 0.0
