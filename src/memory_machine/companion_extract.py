"""Validate a proposed Companion memory before it enters the tape.

This is the deterministic admission contract for candidates produced by a
future extractor. It does not infer facts from free text or promote hypotheses.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any

from .tape import MemoryRecord

COMPANION_TYPES = {"person_report", "episode", "persona", "story", "hypothesis"}
AUTHORS = {
    "person_report": "person",
    "episode": "joint",
    "persona": "joint",
    "story": "joint",
    "hypothesis": "system",
}


def _timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError
        return parsed
    except (ValueError, AttributeError) as exc:
        raise ValueError("a timezone-aware ISO timestamp is required") from exc


def candidate_record(
    proposal: dict[str, Any],
    *,
    author: str,
    turn_id: str = "",
    source_text: str = "",
    source_memory_id: str = "",
    event_time: str = "",
) -> MemoryRecord:
    """Build one typed record from a sourced proposal.

    The caller verifies that `source_memory_id` is an actual turn slot in
    the same root. The quote proves a literal anchor, not semantic truth.
    """
    kind = proposal.get("type")
    if kind not in COMPANION_TYPES:
        raise ValueError("unknown Companion memory type")
    if author != AUTHORS[kind]:
        raise ValueError(f"invalid author for {kind}")
    summary = str(proposal.get("summary") or "").strip()
    if not summary or len(summary) > 1000:
        raise ValueError("summary must have 1 to 1000 characters")
    if event_time:
        _timestamp(event_time)

    if kind == "persona":
        revision = str(proposal.get("approved_version") or "").strip()
        if not revision:
            raise ValueError("persona requires an approved version")
        return MemoryRecord(
            type=kind, summary=summary, author=author, event_time=event_time,
            source=f"persona#{revision}",
            origin={"kind": "persona_revision", "version": revision},
        )

    if not turn_id or not source_memory_id:
        raise ValueError(f"{kind} requires a source turn")
    quote = str(proposal.get("quote") or "").strip()
    if not quote or quote not in source_text:
        raise ValueError("a literal quote from the source turn is required")
    origin: dict[str, Any] = {"kind": "turn", "turn_ids": [turn_id], "quote": quote}
    if kind == "story":
        event_id = str(proposal.get("event_id") or "").strip()
        if not event_id:
            raise ValueError("story requires an event ID")
        origin["kind"] = "story_event"
        origin["event_id"] = event_id
    if kind == "hypothesis":
        raw = proposal.get("confidence")
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            raise ValueError("hypothesis requires numeric confidence")
        confidence = float(raw)
        if not math.isfinite(confidence) or not 0 <= confidence <= 1:
            raise ValueError("hypothesis confidence must be in [0, 1]")
        review_at = str(proposal.get("review_at") or "")
        if not review_at:
            raise ValueError("hypothesis requires a review date")
        _timestamp(review_at)
        origin["confidence"] = confidence
        origin["review_at"] = review_at
    return MemoryRecord(
        type=kind, summary=summary, author=author, event_time=event_time,
        source=turn_id, origin=origin, derived_from=[source_memory_id],
    )
