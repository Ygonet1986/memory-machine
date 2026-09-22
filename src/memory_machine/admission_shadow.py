"""Shadow instrumentation for evidence admission (v1).

Records, for every recall, the signals an admission controller would need to
decide which candidates deserve the payload budget -- without changing any
answer. Disabled unless ``MEMORY_MACHINE_ADMISSION_SHADOW=1``.

Privacy: the log never contains question text, summaries, ``why`` text or
notes. It stores IDs, hashes and derived metrics only (overlaps, IDF coverage,
matched identifier/date tokens, character costs, counterfactual decisions).

Determinism: no LLM calls; every field is computed from the recall inputs.

Output: ``MEMORY_MACHINE_ADMISSION_SHADOW_PATH`` when set, otherwise
``<session root>/admission_shadow.jsonl`` (one JSON object per line).
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .retrieval import tokenize

ENV_FLAG = "MEMORY_MACHINE_ADMISSION_SHADOW"
ENV_PATH = "MEMORY_MACHINE_ADMISSION_SHADOW_PATH"

# Documented counterfactual baseline for event-log candidates: the v2 primary
# candidacy rule (rank-1 with score >= 0.90 x best). It is recorded, never
# applied.
EVENT_RULE_MARGIN = 0.90

_ENTITY_RE = re.compile(
    r"\b(?:[A-Z]{1,5}-?\d{2,}"          # M0017, RFC-2119
    r"|v?\d+\.\d+(?:\.\d+)?"             # v2.1, 3.14.1
    r"|[\w./-]+\.(?:py|js|ts|tsx|json|jsonl|md|csv|yaml|yml|toml|sh|go|rs|java|c|cc|cpp|h|txt))\b"
)
_DATE_RE = re.compile(r"\b(?:\d{4}-\d{2}-\d{2}|\d{2}/\d{2}/\d{4})\b")

_warned = False


def enabled() -> bool:
    return os.environ.get(ENV_FLAG, "").strip() == "1"


def output_path(root: Path) -> Path:
    override = os.environ.get(ENV_PATH, "").strip()
    if override:
        return Path(override)
    return Path(root) / "admission_shadow.jsonl"


def _warn(message: str) -> None:
    global _warned
    if not _warned:
        _warned = True
        print(f"admission shadow: {message}", file=sys.stderr)


def _field(candidate: Any, name: str, default: Any = None) -> Any:
    if isinstance(candidate, dict):
        return candidate.get(name, default)
    return getattr(candidate, name, default)


def _candidate_text(record: Any) -> str:
    summary = str(getattr(record, "summary", "") or "")
    why = str(getattr(record, "why", "") or "")
    return f"{summary} {why}"


def _idf(corpus_tokens: list[list[str]]) -> dict[str, float]:
    total = len(corpus_tokens)
    df: dict[str, int] = {}
    for tokens in corpus_tokens:
        for token in set(tokens):
            df[token] = df.get(token, 0) + 1
    return {token: math.log((total + 1) / (count + 1)) + 1.0 for token, count in df.items()}


def _lexical_overlap(question_tokens: list[str], doc_tokens: list[str]) -> float:
    if not question_tokens:
        return 0.0
    return round(len(set(question_tokens) & set(doc_tokens)) / len(set(question_tokens)), 4)


def _rare_term_coverage(question_tokens: list[str], doc_tokens: list[str],
                        idf: dict[str, float]) -> float:
    unique = set(question_tokens)
    if not unique:
        return 0.0
    total = sum(idf.get(token, 1.0) for token in unique)
    if total <= 0:
        return 0.0
    covered = sum(idf.get(token, 1.0) for token in unique & set(doc_tokens))
    return round(covered / total, 4)


def _matches(pattern: re.Pattern[str], question: str, doc_text: str) -> list[str]:
    return sorted(set(pattern.findall(question)) & set(pattern.findall(doc_text)))


def _candidate_entry(*, origin: str, record: Any, memory_id: str, rank: int,
                     score: float, question: str, question_tokens: list[str],
                     doc_text: str, idf: dict[str, float], chars: int,
                     in_payload: bool, counterfactual: bool) -> dict[str, Any]:
    doc_tokens = tokenize(doc_text)
    return {
        "origin": origin,
        "memory_id": memory_id,
        "rank": rank,
        "score": round(float(score or 0.0), 4),
        "type": str(getattr(record, "type", "") or ""),
        "lexical_overlap": _lexical_overlap(question_tokens, doc_tokens),
        "rare_term_coverage": _rare_term_coverage(question_tokens, doc_tokens, idf),
        "entity_matches": _matches(_ENTITY_RE, question, doc_text),
        "date_matches": _matches(_DATE_RE, question, doc_text),
        "chars_if_admitted": int(chars),
        "in_payload": bool(in_payload),
        "counterfactual_admitted": bool(counterfactual),
    }


def build_record(*, question: str, session_id: str,
                 annotations: Iterable[Any], records: Iterable[Any],
                 payload: list[dict[str, Any]] | None,
                 event_hits: list[dict[str, Any]] | None,
                 cached: bool = False, ts: str | None = None) -> dict[str, Any]:
    """Build one shadow record from recall inputs; no content leaves as text."""
    record_list = list(records)
    by_id = {getattr(record, "id", ""): record for record in record_list}
    payload_items = list(payload or [])
    by_payload = {str(item.get("memory_id") or ""): item for item in payload_items}

    question_tokens = tokenize(question)
    corpus_tokens = [tokenize(_candidate_text(record)) for record in record_list]
    idf = _idf(corpus_tokens)

    active: list[dict[str, Any]] = []
    for rank, annotation in enumerate(annotations, start=1):
        memory_id = str(_field(annotation, "memory_id", "") or "")
        record = by_id.get(memory_id)
        if record is None:
            continue
        in_payload = memory_id in by_payload
        chars = (int(by_payload[memory_id].get("used_chars") or 0) if in_payload
                 else len(_candidate_text(record)))
        active.append(_candidate_entry(
            origin="active", record=record, memory_id=memory_id, rank=rank,
            score=float(_field(annotation, "relevance", 0.0) or 0.0),
            question=question, question_tokens=question_tokens,
            doc_text=_candidate_text(record), idf=idf, chars=chars,
            in_payload=in_payload, counterfactual=in_payload))

    hits = list(event_hits or [])
    best_hit = max((float(hit.get("score") or 0.0) for hit in hits), default=0.0)
    event_log: list[dict[str, Any]] = []
    for rank, hit in enumerate(hits, start=1):
        memory_id = str(hit.get("memory_id") or "")
        doc_text = f"{hit.get('summary') or ''} {hit.get('why') or ''}"
        score = float(hit.get("score") or 0.0)
        admitted = rank == 1 and best_hit > 0 and score >= EVENT_RULE_MARGIN * best_hit
        entry = _candidate_entry(
            origin="event_log", record=hit, memory_id=memory_id, rank=rank,
            score=score, question=question, question_tokens=question_tokens,
            doc_text=doc_text, idf=idf, chars=len(doc_text),
            in_payload=False, counterfactual=admitted)
        entry["source_session"] = str(hit.get("session_id") or "")
        event_log.append(entry)

    return {
        "v": 1,
        "ts": ts or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "session_id": session_id,
        "cached": bool(cached),
        "policy": ("active=in-payload; "
                   f"event_log=rank1-and-score>={EVENT_RULE_MARGIN:.2f}xbest"),
        "question": {
            "sha256": hashlib.sha256(question.encode("utf-8")).hexdigest()[:16],
            "chars": len(question),
            "tokens": len(question_tokens),
        },
        "corpus_records": len(record_list),
        "payload_items": len(payload_items),
        "payload_chars": sum(int(item.get("used_chars") or 0) for item in payload_items),
        "active": active,
        "event_log": event_log,
    }


def record(*, root: Path, question: str, session_id: str,
           annotations: Iterable[Any], records: Iterable[Any],
           payload: list[dict[str, Any]] | None = None,
           event_hits: list[dict[str, Any]] | None = None,
           cached: bool = False, ts: str | None = None) -> dict[str, Any] | None:
    """Append one shadow record; never raises, never changes the caller."""
    try:
        entry = build_record(
            question=question, session_id=session_id, annotations=annotations,
            records=records, payload=payload, event_hits=event_hits,
            cached=cached, ts=ts)
        path = output_path(root)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
        return entry
    except Exception as error:  # pragma: no cover - defensive by design
        _warn(f"skipped a record ({type(error).__name__})")
        return None
