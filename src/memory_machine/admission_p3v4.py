"""Frozen admission candidate P3v4 (admission-synthetic-v4, commit 44c0124).

Shadow-only research code: computes the P3v4 decision for a lexical candidate
set so the product can log a counterfactual. It is **never** applied to the
payload; the product's real delivery is unchanged. Equivalence with
``eval/admission_synthetic_v4.py`` on the frozen synthetic fixture is
mandatory and tested (``tests/test_admission_p3v4.py``).

Exact rule (frozen):
- ``gain = 0.30*base + 0.20*rare + 0.15*entity + 0.15*temporal
  + 0.10*type_fit + 0.10*correction``
- smoothed-IDF ``rare``; path/key/version entity patterns; correction markers
- relative floor ``0.60 x best_gain``; ``rare >= 0.30``; redundancy Jaccard
  > 0.60 penalizes; budget 4000 chars; at most 2 deliveries
- supersession removal and the correction priority slot (slot 1, exempt from
  the redundancy penalty)
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any

from .retrieval import tokenize

BUDGET_CHARS = 4000
MAX_DELIVERIES = 2
RARE_FLOOR = 0.30
RELATIVE_FLOOR = 0.60
REDUNDANCY = 0.60
MIN_SUPERSEDE_OVERLAP = 2
CORRECTION_MARKERS = (
    "correction", "corrects", "corrected", "supersedes", "superseded",
    "replaces", "replaced", "deprecated", "obsolete", "no longer", "moved to",
)
ENTITY_RE = re.compile(
    r"\b(?:[A-Z]{1,5}-?\d{2,}|v?\d+\.\d+(?:\.\d+)?"
    r"|[\w./-]+\.(?:py|js|ts|json|jsonl|md|csv|yaml|yml|toml|sh))\b"
    r"|(?<![\w])/[a-z0-9][\w./-]*|[a-z0-9_]+:[a-z0-9_]+")
TYPE_CUES = {
    "decision": ("decided", "decision", "decide", "migrate"),
    "lesson": ("lesson", "learned"),
    "preference": ("preference", "prefers"),
    "build": ("shipped", "version", "pinned", "build"),
}


@dataclass
class Candidate:
    """One lexical candidate with its P3v4 decision (shadow only)."""

    memory_id: str
    rank: int
    score: float
    type: str
    created_at: str
    text: str
    # derived signals
    rare: float = 0.0
    entity: bool = False
    temporal: bool = False
    type_fit: float = 0.5
    correction: bool = False
    gain: float = 0.0
    removed_superseded: bool = False
    slot: int = 0
    delivered: bool = False
    chars: int = 0


def _field(record: Any, name: str, default: Any = "") -> Any:
    if isinstance(record, dict):
        return record.get(name, default)
    return getattr(record, name, default)


def _texts(corpus: list[Any]) -> list[str]:
    return [f"{_field(record, 'summary')} {_field(record, 'why')}".strip()
            for record in corpus]


def _idf_map(texts: list[str]) -> dict[str, float]:
    docs = [set(tokenize(text)) for text in texts]
    total = len(docs)
    df: dict[str, int] = {}
    for tokens in docs:
        for token in tokens:
            df[token] = df.get(token, 0) + 1
    return {token: math.log((total + 1) / (count + 1)) + 1.0
            for token, count in df.items()}


def _rare(question_tokens: set[str], doc_tokens: set[str],
          idf: dict[str, float]) -> float:
    if not question_tokens:
        return 0.0
    total = sum(idf.get(token, 1.0) for token in question_tokens)
    if total <= 0:
        return 0.0
    covered = sum(idf.get(token, 1.0) for token in question_tokens & doc_tokens)
    return covered / total


def _type_hint(question: str) -> str | None:
    tokens = set(tokenize(question))
    for rtype, cues in TYPE_CUES.items():
        if tokens & set(cues):
            return rtype
    return None


def _type_fit(hint: str | None, rtype: str) -> float:
    if hint is None:
        return 0.5
    return 1.0 if rtype == hint else 0.25


def _correction(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in CORRECTION_MARKERS)


def build_candidates(question: str, records: list[Any]) -> list[Candidate]:
    """Lexical top-5 candidates over the records (product BM25, positive)."""
    from .retrieval import bm25

    texts = _texts(records)
    if not texts:
        return []
    scores = bm25(question, texts)
    order = sorted(range(len(records)), key=lambda i: -scores[i])
    out: list[Candidate] = []
    for index in order:
        if scores[index] <= 0:
            break
        if len(out) >= 5:
            break
        record = records[index]
        out.append(Candidate(
            memory_id=str(_field(record, "id")),
            rank=len(out) + 1,
            score=float(scores[index]),
            type=str(_field(record, "type")),
            created_at=str(_field(record, "created_at")),
            text=texts[index]))
    return out


def decide(question: str, candidates: list[Candidate],
           corpus: list[Any]) -> list[Candidate]:
    """Score candidates and mark the P3v4 decision (delivery flags)."""
    if not candidates:
        return []
    best = candidates[0].score
    idf = _idf_map(_texts(corpus))
    question_tokens = set(tokenize(question))
    hint = _type_hint(question)
    question_entities = set(ENTITY_RE.findall(question))
    tokens_by_id: dict[str, set[str]] = {}
    for candidate in candidates:
        doc_tokens = set(tokenize(candidate.text))
        tokens_by_id[candidate.memory_id] = doc_tokens
        candidate.rare = _rare(question_tokens, doc_tokens, idf)
        candidate.entity = bool(question_entities & set(ENTITY_RE.findall(candidate.text)))
        candidate.correction = _correction(candidate.text)
        candidate.type_fit = _type_fit(hint, candidate.type)
        candidate.chars = len(candidate.text) + 8
    newest = max((candidate.created_at for candidate in candidates
                  if candidate.rare > 0), default="")
    for candidate in candidates:
        candidate.temporal = bool(candidate.rare > 0
                                  and candidate.created_at == newest)
        candidate.gain = (0.30 * (candidate.score / best) + 0.20 * candidate.rare
                          + 0.15 * (1.0 if candidate.entity else 0.0)
                          + 0.15 * (1.0 if candidate.temporal else 0.0)
                          + 0.10 * candidate.type_fit
                          + 0.10 * (1.0 if candidate.correction else 0.0))

    corrections = [c for c in candidates if c.correction]
    if corrections:
        for candidate in candidates:
            if candidate.correction:
                continue
            for correction in corrections:
                same_type = candidate.type == correction.type
                older = candidate.created_at < correction.created_at
                overlap = len(tokens_by_id[candidate.memory_id]
                              & tokens_by_id[correction.memory_id])
                if same_type and older and overlap >= MIN_SUPERSEDE_OVERLAP:
                    candidate.removed_superseded = True
                    break

    survivors = [c for c in candidates if not c.removed_superseded]
    survivors.sort(key=lambda c: (-c.gain, -c.score, c.rank))
    best_gain = survivors[0].gain if survivors else 0.0
    floor = RELATIVE_FLOOR * best_gain

    eligible = [c for c in survivors if c.rare >= RARE_FLOOR and c.gain >= floor]
    slot_one = None
    slot_corrections = [c for c in eligible if c.correction]
    if slot_corrections:
        slot_one = max(slot_corrections, key=lambda c: (c.gain, -c.rank))

    selected: list[Candidate] = []
    selected_tokens: set[str] = set()
    used = 0
    if slot_one is not None:
        slot_one.slot = 1
        slot_one.delivered = True
        selected.append(slot_one)
        selected_tokens |= tokens_by_id[slot_one.memory_id]
        used += slot_one.chars
    for candidate in survivors:
        if len(selected) >= MAX_DELIVERIES:
            break
        if candidate is slot_one:
            continue
        if candidate.rare < RARE_FLOOR or candidate.gain < floor:
            continue
        doc_tokens = tokens_by_id[candidate.memory_id]
        union = selected_tokens | doc_tokens
        jaccard = len(selected_tokens & doc_tokens) / len(union) if union else 0.0
        gain = candidate.gain
        if jaccard > REDUNDANCY:
            gain *= 1.0 - jaccard
        if gain < floor:
            continue
        if used + candidate.chars > BUDGET_CHARS:
            continue
        candidate.slot = len(selected) + 1
        candidate.delivered = True
        selected.append(candidate)
        selected_tokens |= doc_tokens
        used += candidate.chars
    return candidates


def delivered_ids(candidates: list[Candidate]) -> list[str]:
    """Delivered ids in selection order (slot 1 first)."""
    selected = [c for c in candidates if c.delivered]
    selected.sort(key=lambda c: c.slot)
    return [c.memory_id for c in selected]
