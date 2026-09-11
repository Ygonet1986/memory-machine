"""Memory views: multiple organizational projections over one canonical tape.

A record belongs to one canonical tape and may appear in several **views**
(time, type, source, topic, ...) without being duplicated. Views are a
rebuildable projection derived from the records' ``views`` tags — the tape
remains the single source of truth.

This is the foundation of the v0.5 multidimensional topology: storage (what
happened), organization (which views it belongs to) and attention (which views
are active) are separate concerns.
"""

from __future__ import annotations

from typing import Any

from .retrieval import rank
from .tape import MemoryRecord, Tape


def build_index(tape: Tape) -> dict[str, list[str]]:
    """Map each view to the ids of the active records that belong to it."""
    index: dict[str, list[str]] = {}
    for r in tape.read():
        if r.status != "active":
            continue
        for view in r.views:
            index.setdefault(view, []).append(r.id)
    return index


def list_views(tape: Tape) -> list[dict[str, Any]]:
    index = build_index(tape)
    return sorted(
        ({"view": view, "count": len(ids)} for view, ids in index.items()),
        key=lambda x: (-x["count"], x["view"]),
    )


def _view_digest(records: list[MemoryRecord], max_items: int = 10) -> str:
    return " | ".join(r.summary for r in records[:max_items] if r.summary)


def rank_views(tape: Tape, query: str, *, limit: int = 5) -> list[tuple[str, float]]:
    """Rank views by BM25 over their name + member summaries."""
    records = {r.id: r for r in tape.read() if r.status == "active"}
    index = build_index(tape)
    views = list(index.keys())
    if not views:
        return []
    docs = [
        f"{view} " + _view_digest([records[i] for i in index[view] if i in records])
        for view in views
    ]
    return [(views[i], score) for i, score in rank(query, docs, limit=limit)]


def records_in_views(tape: Tape, views: list[str]) -> list[MemoryRecord]:
    want = set(views)
    return [r for r in tape.read() if r.status == "active" and want & set(r.views)]


def ids_in_views(tape: Tape, views: list[str]) -> set[str]:
    return {r.id for r in records_in_views(tape, views)}
