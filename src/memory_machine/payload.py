"""Budgeted evidence rehydration (v0.9).

The memory agents decide *which* memories matter (the annotation note); this
module delivers *what those memories actually say* to the assistant, under a
character budget. The payload is **recall-local**: it is returned with the
recall result and never merged into the persistent whiteboard, so the working
memory stays bounded while the assistant can reason over the facts.

Content is deterministic (no extra LLM call): the memory's header, summary and
why, truncated only when the budget forces it — the summary is preserved whole
whenever possible and the ``why`` is cut first. Rollups (``derived_from``) are
rehydrated from their archived sources instead of a second copy.
"""

from __future__ import annotations

from typing import Any, Iterable

DEFAULT_BUDGET = 4000
DEFAULT_MIN_ITEM = 200


def _segments(text: str) -> list[str]:
    import re

    parts = re.split(r"(?<=[.!?])\s+|\n+", text)
    return [part.strip() for part in parts if part.strip()]


def fact_window(text: str, question: str, allocation: int) -> str:
    """Question-matched window of a long text under a character allocation.

    Deterministic: segments are scored by question-token coverage; the best
    segment expands left/right until the allocation fills. Falls back to the
    head when nothing matches or the allocation is too small.
    """
    if allocation <= 0 or not text:
        return text[: max(0, allocation)]
    segments = _segments(text)
    if not segments or sum(len(s) + 1 for s in segments) <= allocation:
        return text[:allocation]
    q_tokens = {t for t in _tokens(question) if len(t) > 2}
    scores = [
        len(q_tokens & {t for t in _tokens(segment) if len(t) > 2}) for segment in segments
    ]
    best = max(range(len(scores)), key=lambda i: (scores[i], -i))
    chosen = [best]
    used = len(segments[best])
    left, right = best - 1, best + 1
    while True:
        candidates = []
        if left >= 0:
            candidates.append((scores[left], 0, left))
        if right < len(segments):
            candidates.append((scores[right], 1, right))
        if not candidates:
            break
        candidates.sort(key=lambda item: (-item[0], item[1]))
        advanced = False
        for _score, side, index in candidates:
            cost = len(segments[index]) + 3  # " … "
            if used + cost <= allocation:
                if side == 0:
                    chosen.insert(0, index)
                    left -= 1
                else:
                    chosen.append(index)
                    right += 1
                used += cost
                advanced = True
                break
        if not advanced:
            break
    window = " … ".join(segments[i] for i in chosen)
    return window


def _tokens(text: str) -> list[str]:
    from .retrieval import tokenize

    return tokenize(text or "")


def _allocations(sizes: list[int], weights: list[float], budget: int, min_item_chars: int) -> list[int]:
    """Reserve a floor per item, then water-fill the rest by weight up to size.

    Guarantees ``sum(alloc) <= budget`` and ``alloc[i] <= sizes[i]``; the budget
    is fully used when the content is larger than it.
    """
    n = len(sizes)
    if n == 0:
        return []
    if budget <= 0:  # unlimited
        return list(sizes)
    allocations = [min(min_item_chars, sizes[i]) for i in range(n)]
    remaining = budget - sum(allocations)
    if remaining < 0:
        # Even the floors do not fit: take what fits in relevance order.
        order = sorted(range(n), key=lambda i: -weights[i])
        allocations = [0] * n
        remaining = budget
        for i in order:
            take = min(sizes[i], remaining)
            allocations[i] = take
            remaining -= take
            if remaining <= 0:
                break
        return allocations
    active = [i for i in range(n) if allocations[i] < sizes[i]]
    while remaining > 0 and active:
        total_weight = sum(weights[i] for i in active) or 1.0
        proposals = {i: remaining * weights[i] / total_weight for i in active}
        capped = [i for i in active if proposals[i] >= sizes[i] - allocations[i]]
        if capped:
            for i in capped:
                give = sizes[i] - allocations[i]
                allocations[i] += give
                remaining -= give
                active.remove(i)
            continue
        for i in active:
            give = int(proposals[i])
            allocations[i] += give
            remaining -= give
        for i in active:
            if remaining <= 0:
                break
            room = sizes[i] - allocations[i]
            if room > 0:
                allocations[i] += 1
                remaining -= 1
        break
    return allocations


def _header(record: Any) -> str:
    """Compact provenance header; carries the most precise timestamp available."""
    stamp = (record.created_at or "")[:16].replace("T", " ")
    return f"[{record.id} | {record.type} | {stamp}]"


def _full_text(record: Any, records: dict[str, Any]) -> tuple[str, str]:
    """The untruncated text of one item and its source kind."""
    header = _header(record)
    if record.derived_from:
        sources = [records[s] for s in record.derived_from if s in records]
        body = (
            "\n".join(f"- {s.summary}: {s.why}" for s in sources)
            if sources
            else f"{record.summary}\n{record.why}"
        )
        return header + "\n" + body, "rehydrated"
    return header + "\n" + record.summary + "\n" + record.why, "direct"


def _truncate(record: Any, full: str, allocation: int) -> tuple[str, bool]:
    """Cut ``why`` before ``summary``: preserve the summary when possible."""
    if len(full) <= allocation:
        return full, False
    header = _header(record)
    if record.derived_from:
        allowed = max(0, allocation - len(header) - 1)
        body = full[len(header) + 1 :][:allowed]
        return header + "\n" + body, True
    text = header + "\n" + record.summary
    room_for_why = allocation - len(text) - 1
    if room_for_why >= 0:
        return text + "\n" + record.why[:room_for_why], True
    allowed = max(0, allocation - len(header) - 1)
    return header + "\n" + record.summary[:allowed], True


def build_evidence_payload(
    records: dict[str, Any],
    annotations: Iterable[Any],
    *,
    budget: int = DEFAULT_BUDGET,
    min_item_chars: int = DEFAULT_MIN_ITEM,
    question: str = "",
    window: bool = False,
) -> list[dict[str, Any]]:
    """Build the budgeted evidence payload for the annotated memories.

    ``records`` must include archived records (rollup sources live there), and
    ``annotations`` are the kept annotations (``memory_id``, ``note``,
    ``relevance``).
    """
    items: list[tuple[Any, Any]] = []
    for annotation in annotations:
        record = records.get(getattr(annotation, "memory_id", ""))
        if record is None:
            continue
        items.append((annotation, record))
    if not items:
        return []
    items.sort(
        key=lambda pair: (
            -(float(getattr(pair[0], "relevance", 0.0) or 0.0)),
            pair[1].id,
        )
    )
    weights = [max(0.01, float(getattr(a, "relevance", 0.0) or 0.0)) for a, _r in items]
    rendered = [_full_text(record, records) for _a, record in items]
    sizes = [len(text) for text, _source in rendered]
    allocations = _allocations(sizes, weights, budget, min_item_chars)

    payload: list[dict[str, Any]] = []
    for (annotation, record), (full, source), allocation in zip(items, rendered, allocations):
        text, truncated = _truncate(record, full, allocation)
        if window and truncated and question and allocation > 0:
            header = _header(record)
            room = allocation - len(header) - 1
            if record.derived_from:
                body = full[len(header) + 1 :] if full.startswith(header) else full
                if room >= 120:
                    text = header + "\n" + fact_window(body, question, room)
            else:
                summary = record.summary or ""
                room -= len(summary) + 1
                if room >= 120:
                    body = fact_window(record.why or "", question, room)
                    text = header + "\n" + summary + "\n" + body if body else text
        payload.append(
            {
                "memory_id": record.id,
                "relevance": round(float(getattr(annotation, "relevance", 0.0) or 0.0), 3),
                "note": getattr(annotation, "note", ""),
                "evidence": text,
                "source": source,
                "derived_from": list(record.derived_from),
                "allocated_chars": allocation,
                "used_chars": len(text),
                "truncated": truncated,
            }
        )
    return payload


def payload_as_context(payload: list[dict[str, Any]]) -> str:
    """Render the payload as the assistant's extra context."""
    blocks = [str(item.get("evidence") or "") for item in payload if item.get("evidence")]
    return "\n\n".join(blocks)


def payload_chars(payload: list[dict[str, Any]]) -> int:
    return sum(int(item.get("used_chars") or 0) for item in payload)
