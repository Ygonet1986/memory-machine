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

from .llm import extract_json_object
from .retrieval import rank
from .tape import MemoryRecord, Tape

# Structural views are metadata, not conceptual regions: they are excluded from
# co-occurrence expansion so that ``time/`` and ``type/`` do not act as hubs.
STRUCTURAL_PREFIXES = ("time/", "type/", "source/")


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


def rank_views(
    tape: Tape,
    query: str,
    *,
    limit: int = 5,
    prefixes: tuple[str, ...] | None = None,
) -> list[tuple[str, float]]:
    """Rank views by BM25 over their name + member summaries.

    ``prefixes`` restricts the candidates to views of certain dimensions
    (e.g. ``("topic/", "subject/")`` for semantic views).
    """
    records = {r.id: r for r in tape.read() if r.status == "active"}
    index = build_index(tape)
    views = [v for v in index if prefixes is None or v.startswith(prefixes)]
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


def related_views(
    tape: Tape,
    views: list[str],
    *,
    top_k: int = 5,
    exclude_prefixes: tuple[str, ...] = STRUCTURAL_PREFIXES,
) -> list[str]:
    """Views that co-occur with the given ones, ranked by co-occurrence count.

    Expansion candidates exclude structural views (``time/``, ``type/``,
    ``source/``), which co-occur with almost everything and would otherwise act
    as hubs. The selected views themselves are never returned.
    """
    selected = set(views)
    counts: dict[str, int] = {}
    for r in tape.read():
        if r.status != "active":
            continue
        if not (selected & set(r.views)):
            continue
        for v in r.views:
            if v in selected or v.startswith(exclude_prefixes):
                continue
            counts[v] = counts.get(v, 0) + 1
    ranked = sorted(counts.items(), key=lambda x: (-x[1], x[0]))
    return [v for v, _n in ranked[:top_k]]


VIEW_ROUTER_PROMPT = """You route a query to the regions (views) of a memory \
tape that may hold memories relevant to it. A view is an organizational \
projection over the tape (topic/<x>, subject/<x>, time/<month>, type/<kind>); a \
single memory can belong to several views at once.

Views and what they cover:

{views}

Current working context:

{whiteboard}

Query: {query}

Return ONLY JSON, nothing else:
{{"views":["topic/router","subject/memory-machine"],"confidence":0.0}}

Choose the {top_k} views most likely to contain memories relevant to the query \
and the current work. Prefer topic/ and subject/ views when they fit; include \
time/ or type/ views only when the query is about when or what kind. Be \
inclusive: include any view that could plausibly hold relevant memories, even \
if the wording differs (match by meaning, not just words). Return fewer only if \
fewer are plausible. confidence is a number from 0.0 (guess) to 1.0 (certain) \
for how well the selection covers what the query needs."""


def select_views_llm(
    tape: Tape,
    query: str,
    client: Any,
    *,
    whiteboard: Any = None,
    top_k: int = 5,
    max_views: int = 40,
    temperature: float = 0.0,
) -> tuple[list[str], float] | None:
    """Contextual view routing via one LLM call over the view digests.

    Returns ``(views, confidence)`` or ``None`` on failure (caller falls back).
    """
    if client is None:
        return None
    index = build_index(tape)
    if not index:
        return None
    records = {r.id: r for r in tape.read() if r.status == "active"}
    ordered = sorted(index.items(), key=lambda x: (-len(x[1]), x[0]))[:max_views]
    lines = [
        f"{view} ({len(ids)}): {_view_digest([records[i] for i in ids if i in records], max_items=6)[:220] or '(no summaries)'}"
        for view, ids in ordered
    ]
    board = ""
    if whiteboard is not None:
        board = whiteboard.render(include_annotations=False) if hasattr(whiteboard, "render") else str(whiteboard)
    messages = [
        {
            "role": "system",
            "content": VIEW_ROUTER_PROMPT.format(
                views="\n".join(lines),
                whiteboard=board or "(empty whiteboard)",
                query=query,
                top_k=top_k,
            ),
        },
        {"role": "user", "content": query},
    ]
    try:
        content = client.complete(messages, temperature=temperature)
    except Exception:
        return None

    obj = extract_json_object(content)
    known = {v for v, _ids in ordered}
    raw = obj.get("views") or []
    selected = [v for v in raw if isinstance(v, str) and v in known][:top_k]
    if not selected:
        return None
    try:
        confidence = float(obj.get("confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    return selected, max(0.0, min(1.0, confidence))
