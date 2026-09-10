import json

from app import websearch


class _FakeResp:
    def __init__(self, data):
        self._data = data

    def read(self):
        return json.dumps(self._data).encode()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_format_results():
    results = [{"title": "t", "url": "http://u", "snippet": "s"}]
    text = websearch.format_results(results)
    assert "t" in text
    assert "http://u" in text
    assert "s" in text


def test_format_results_empty():
    assert websearch.format_results([]) == ""


def test_search_parses_abstract_and_topics(monkeypatch):
    data = {
        "AbstractText": "The answer",
        "AbstractSource": "Wiki",
        "AbstractURL": "http://x",
        "RelatedTopics": [{"Text": "rel topic", "FirstURL": "http://r"}],
    }
    monkeypatch.setattr(websearch.urllib.request, "urlopen", lambda *a, **k: _FakeResp(data))
    results = websearch.search("q")
    assert results[0]["snippet"] == "The answer"
    assert results[1]["title"] == "rel topic"


def test_search_empty_query():
    assert websearch.search("   ") == []


def test_search_error_returns_empty(monkeypatch):
    def boom(*a, **k):
        raise Exception("down")

    monkeypatch.setattr(websearch.urllib.request, "urlopen", boom)
    assert websearch.search("q") == []
