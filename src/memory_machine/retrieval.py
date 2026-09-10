"""Retrieval: lexical BM25 scoring plus optional embeddings.

Default retrieval is deterministic BM25 (no dependencies). If an
OpenAI-compatible embeddings model is configured, callers can use
:class:`Embedder` for semantic similarity; otherwise BM25 is used.
"""

from __future__ import annotations

import json
import math
import re
import urllib.error
import urllib.request
from collections import Counter
from typing import Any

STOPWORDS = {
    "the", "and", "for", "are", "was", "what", "did", "we", "about", "using",
    "with", "that", "our", "this", "you", "how", "why", "not", "can", "all",
    "from", "have", "has", "will", "would", "should", "there", "they", "your",
}


def tokenize(text: str) -> list[str]:
    toks = re.findall(r"[a-z0-9_]+", (text or "").lower())
    return [t for t in toks if len(t) > 2 and t not in STOPWORDS]


def bm25(query: str, docs: list[str], *, k1: float = 1.5, b: float = 0.75) -> list[float]:
    """BM25 relevance of each doc for the query (0.0 when no term matches)."""
    if not docs:
        return []
    tokenized = [tokenize(d) for d in docs]
    n = len(tokenized)
    avgdl = sum(len(d) for d in tokenized) / n if n else 0.0
    df: Counter[str] = Counter()
    for d in tokenized:
        for t in set(d):
            df[t] += 1
    q = tokenize(query)
    scores: list[float] = []
    for d in tokenized:
        dl = len(d)
        tf = Counter(d)
        s = 0.0
        for t in q:
            if t not in tf:
                continue
            idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
            denom = tf[t] + k1 * (1 - b + b * (dl / avgdl if avgdl else 0.0))
            s += idf * (tf[t] * (k1 + 1)) / denom
        scores.append(s)
    return scores


def rank(query: str, docs: list[str], *, limit: int = 10) -> list[tuple[int, float]]:
    """Return ``(index, score)`` for the top matching docs, best first."""
    scores = bm25(query, docs)
    order = sorted(range(len(docs)), key=lambda i: -scores[i])
    out: list[tuple[int, float]] = []
    for i in order:
        if scores[i] <= 0:
            break
        out.append((i, scores[i]))
        if len(out) >= limit:
            break
    return out


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


class Embedder:
    """Minimal OpenAI-compatible embeddings client (optional)."""

    def __init__(self, base_url: str, api_key: str, model: str, *, timeout: int = 60):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        url = f"{self.base_url}/embeddings"
        payload = {"model": self.model, "input": texts}
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.HTTPError, urllib.error.URLError, OSError):
            return []
        try:
            return [item["embedding"] for item in data["data"]]
        except (KeyError, TypeError):
            return []


def rank_semantic(
    query: str,
    docs: list[str],
    embedder: Embedder | None,
    *,
    limit: int = 10,
) -> list[tuple[int, float]]:
    """Rank docs by embeddings when available, otherwise fall back to BM25."""
    if embedder is None:
        return rank(query, docs, limit=limit)
    vectors = embedder.embed([query, *docs])
    if len(vectors) != len(docs) + 1:
        return rank(query, docs, limit=limit)
    qv, dvs = vectors[0], vectors[1:]
    scored = [(i, cosine(qv, dv)) for i, dv in enumerate(dvs)]
    scored.sort(key=lambda x: -x[1])
    return [(i, s) for i, s in scored[:limit] if s > 0]
