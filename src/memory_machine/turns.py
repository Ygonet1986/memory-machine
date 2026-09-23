"""Turn slots: the user's message and the assistant's reply as tape records.

Turn slots are a labeled exception (like attachments): the turn text is
intentionally memorized so the tape holds both sides of the conversation -
a ``question`` record for what the user said and a ``reply`` record for what
was answered, paired by ``derived_from`` and deduped by source
(``opencode#<message id>``).

The record schema is unchanged (no new fields). Slots are written only when a
caller explicitly asks; the opencode plugin gates the calls behind
``MEMORY_MACHINE_TURN_SLOTS=1`` (off by default), so the default write path
and the active admission window stay untouched.
"""

from __future__ import annotations

from typing import Any

from .groups import Manifest, add_memory
from .secrets import SecretError
from .tape import MemoryRecord, Tape

SLOT_TYPES = ("question", "reply")
SUMMARY_LIMIT = 200


def slot_summary(text: str, limit: int = SUMMARY_LIMIT) -> str:
    """Single-line summary for a slot record (bounded)."""
    flat = " ".join((text or "").split())
    if len(flat) <= limit:
        return flat
    return flat[: limit - 1] + "…"


def slot_source(message_id: str) -> str:
    return f"opencode#{message_id}" if message_id else ""


def _find_by_source(tape: Tape, source: str) -> MemoryRecord | None:
    if not source:
        return None
    for record in tape.read():
        if record.source == source:
            return record
    return None


def add_turn_slot(
    tape: Tape,
    manifest: Manifest,
    *,
    slot: str,
    text: str,
    message_id: str = "",
    pair_message_id: str = "",
    model: str = "",
) -> dict[str, Any]:
    """Append one turn slot (``question`` or ``reply``) to the tape.

    Deduped by ``source``: the same opencode message id never produces two
    records. A ``reply`` whose paired question is already on the tape gets
    ``derived_from=[question id]``; an orphan reply is allowed and explicit.
    Secret-like content refuses the write (same gate as every record).
    """
    if slot not in SLOT_TYPES:
        return {"ok": False, "error": f"unknown slot type: {slot!r}"}
    body = (text or "").strip()
    if not body:
        return {"ok": False, "error": "empty slot text"}
    source = slot_source(message_id)
    existing = _find_by_source(tape, source)
    if existing is not None:
        return {"ok": True, "deduped": True, "slot": slot,
                "record": existing.to_dict()}
    derived: list[str] = []
    if slot == "reply" and pair_message_id:
        question = _find_by_source(tape, slot_source(pair_message_id))
        if question is not None:
            derived.append(question.id)
    record = MemoryRecord(type=slot, summary=slot_summary(body), why=body,
                          source=source, derived_from=derived)
    try:
        record, group, agent, created = add_memory(tape, manifest, record,
                                                   model=model)
    except SecretError as error:
        return {"ok": False, "error": str(error), "slot": slot}
    return {"ok": True, "slot": slot, "record": record.to_dict(),
            "group": group.id, "agent": agent.id, "new_agent": created,
            "paired": derived}
