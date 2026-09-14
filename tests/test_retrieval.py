from memory_machine.retrieval import bm25, chunk_spans, chunk_text, cosine, rank, tokenize


def test_tokenize_filters_stopwords_and_short():
    assert tokenize("the database is up") == ["database"]


def test_chunk_spans_offsets_are_contiguous_and_cover_stripped_text():
    text = "word " * 500
    spans = chunk_spans(text, size=600, overlap=100)
    assert spans
    assert spans[0][0] == 0
    assert spans[-1][1] == len(text.strip())
    assert all(end >= start for start, end, _ in spans)
    assert all(end - start <= 600 for start, end, _ in spans)
    for (_, prev_end, _), (start, _, _) in zip(spans, spans[1:]):
        assert start == prev_end - 100


def test_chunk_spans_match_chunk_text_byte_for_byte():
    text = "alpha beta gamma " * 250
    assert [t for _, _, t in chunk_spans(text, size=600, overlap=100)] == chunk_text(
        text, size=600, overlap=100
    )


def test_chunk_spans_empty_and_short():
    assert chunk_spans("") == []
    assert chunk_spans("   ") == []
    assert chunk_spans("short") == [(0, 5, "short")]


def test_chunk_text_still_delegates():
    text = ("a" * 900) + "end"
    assert chunk_text(text, size=600, overlap=100) == [
        t for _, _, t in chunk_spans(text, size=600, overlap=100)
    ]


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
