import json
import urllib.error

from memory_machine import llm as llm_mod


class _FakeResp:
    def read(self):
        return json.dumps(
            {"choices": [{"message": {"content": "ok", "reasoning_content": ""}}]}
        ).encode()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_retry_on_429_then_succeed(monkeypatch):
    calls = {"n": 0}

    def fake_urlopen(req, timeout=None, context=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise urllib.error.HTTPError(req.full_url, 429, "rate limited", {}, None)
        return _FakeResp()

    monkeypatch.setattr(llm_mod.urllib.request, "urlopen", fake_urlopen)

    client = llm_mod.LLMClient("https://x", "k", "m", retries=1, backoff=0)
    content, _ = client.complete_with_reasoning([{"role": "user", "content": "hi"}])
    assert content == "ok"
    assert calls["n"] == 2


def test_non_retryable_http_raises(monkeypatch):
    def fake_urlopen(req, timeout=None, context=None):
        raise urllib.error.HTTPError(req.full_url, 401, "unauthorized", {}, None)

    monkeypatch.setattr(llm_mod.urllib.request, "urlopen", fake_urlopen)

    client = llm_mod.LLMClient("https://x", "k", "m", retries=2, backoff=0)
    try:
        client.complete([{"role": "user", "content": "hi"}])
    except llm_mod.LLMError as e:
        assert "401" in str(e)
    else:
        raise AssertionError("expected LLMError")


def test_exhausts_retries(monkeypatch):
    calls = {"n": 0}

    def fake_urlopen(req, timeout=None, context=None):
        calls["n"] += 1
        raise urllib.error.HTTPError(req.full_url, 500, "boom", {}, None)

    monkeypatch.setattr(llm_mod.urllib.request, "urlopen", fake_urlopen)

    client = llm_mod.LLMClient("https://x", "k", "m", retries=2, backoff=0)
    try:
        client.complete([{"role": "user", "content": "hi"}])
    except llm_mod.LLMError:
        pass
    else:
        raise AssertionError("expected LLMError")
    assert calls["n"] == 3  # initial + 2 retries


class _StreamResp:
    def __init__(self, lines):
        self._lines = lines

    def __iter__(self):
        return iter(self._lines)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_stream_parses_deltas(monkeypatch):
    lines = [
        b'data: {"choices":[{"delta":{"content":null,"reasoning_content":"think"}}]}\n',
        b'data: {"choices":[{"delta":{"content":"hi","reasoning_content":null}}]}\n',
        b"data: [DONE]\n",
    ]
    monkeypatch.setattr(llm_mod.urllib.request, "urlopen", lambda *a, **k: _StreamResp(lines))

    client = llm_mod.LLMClient("https://x", "k", "m")
    deltas = list(client.stream([{"role": "user", "content": "x"}]))
    assert deltas == [("", "think"), ("hi", "")]
