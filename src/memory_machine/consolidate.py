"""Whiteboard consolidation: shrink the working memory without losing continuity.

When the whiteboard grows past its budget, consolidation:
  1. persists the accumulated working state (context, pending, annotations) as
     a memory record on the tape, so nothing essential is lost long-term;
  2. replaces the bulky fields with a compact summary that keeps the work
     going.

A deterministic fallback is used when no LLM client is available.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .groups import Manifest, add_memory
from .tape import MemoryRecord, Tape
from .whiteboard import Whiteboard

DEFAULT_MAX_SUMMARY = 2000
DEFAULT_MAX_DUMP = 8000

CONSOLIDATOR_PROMPT = """You are the consolidator agent. The memory agents have \
filled the shared whiteboard with reminders; the whiteboard has grown too large \
to keep as-is. Your job is to reduce it to a compact continuation note without \
losing anything essential.

Preserve: the subject, the objective, open decisions, pending items, and any \
"Remembered" memory ids that are still relevant. Be terse and structured. Do \
not invent new facts; do not drop a memory id that still matters.

Work state:

{state}"""


def _state_dump(whiteboard: Whiteboard) -> str:
    return whiteboard.render()


def _deterministic_summary(whiteboard: Whiteboard, max_summary: int) -> str:
    lines: list[str] = []
    if whiteboard.subject:
        lines.append(f"Subject: {whiteboard.subject}")
    if whiteboard.objective:
        lines.append(f"Objective: {whiteboard.objective}")
    for p in whiteboard.pending:
        lines.append(f"Pending: {p}")
    for a in whiteboard.annotations:
        lines.append(f"Remembered {a.memory_id}: {a.note}")
    text = "\n".join(lines)
    return text[:max_summary]


def _consolidator_summary(whiteboard: Whiteboard, client: Any, *, max_summary: int, temperature: float) -> str:
    messages = [
        {"role": "system", "content": CONSOLIDATOR_PROMPT},
        {"role": "user", "content": _state_dump(whiteboard)},
    ]
    content = client.complete(messages, temperature=temperature)
    return content.strip()[:max_summary]


def consolidate_whiteboard(
    whiteboard: Whiteboard,
    *,
    client: Any = None,
    tape: Tape | None = None,
    manifest: Manifest | None = None,
    model: str = "",
    max_summary: int = DEFAULT_MAX_SUMMARY,
    max_dump: int = DEFAULT_MAX_DUMP,
    temperature: float = 0.0,
) -> dict[str, Any]:
    """Consolidate a whiteboard in place. Returns a summary of what happened.

    When ``tape`` and ``manifest`` are provided, the working state is persisted
    as a memory record before the whiteboard is shrunk (lossless continuity).
    """
    if client is not None:
        summary = _consolidator_summary(whiteboard, client, max_summary=max_summary, temperature=temperature)
    else:
        summary = _deterministic_summary(whiteboard, max_summary=max_summary)

    persisted: list[dict[str, Any]] = []
    dump = _state_dump(whiteboard)[:max_dump]
    if tape is not None and manifest is not None and dump:
        rec = MemoryRecord(
            type="memory",
            summary=f"Consolidated whiteboard: {whiteboard.subject or '(untitled)'}",
            why=dump,
        )
        rec, _group, _agent, _created = add_memory(tape, manifest, rec, model=model)
        persisted.append(rec.to_dict())

    stamp = datetime.now(timezone.utc).isoformat()
    whiteboard.consolidated_from = stamp
    whiteboard.context = [summary]
    whiteboard.pending = []
    whiteboard.annotations = []
    whiteboard.touch()

    return {
        "ok": True,
        "summary": summary,
        "persisted": persisted,
        "consolidated_from": stamp,
        "whiteboard": whiteboard,
    }
