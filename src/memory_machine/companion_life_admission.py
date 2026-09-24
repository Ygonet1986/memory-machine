"""Synthetic-life admission (C3): publish an approved life to the tape.

One ``story`` record per approved event, sourced ``life#<version>#<event_id>``
with ``origin.kind="synthetic_life_event"`` and **no conversation turn**.
Versioning is a single batch: newly approved events are appended and every
older active synthetic-life record is superseded in the same atomic rewrite,
so a reload can never resurrect a retired version.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .companion_creator import CompanionCreator
from .companion_memory import CompanionMemory
from .groups import ensure_group, load_manifest, save_manifest
from .tape import MemoryRecord, parse_id

LIFE_KIND = "synthetic_life_event"


def _origin(event: dict[str, Any], doc: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": LIFE_KIND,
        "event_id": event["event_id"],
        "life_version": doc["life_version"],
        "continuity_id": doc["world"]["continuity_id"],
        "sheet_version": doc["sheet_version"],
    }


def admit_life(root: Path, *, self_id: str = "lia",
               continuity_id: str = "main") -> dict[str, Any]:
    """Publish the root's current approved life version to the tape."""
    root = Path(root)
    creator = CompanionCreator(root, self_id=self_id,
                               continuity_id=continuity_id)
    doc = creator.load_current()
    if doc is None:
        raise ValueError("no approved life version in this root")
    if doc["status"] != "approved":
        raise ValueError("only an approved life version can be admitted")
    version = doc["life_version"]

    memory = CompanionMemory(root)
    tape = memory.tape
    records = tape.read()
    existing = {record.source: record for record in records
                if record.source.startswith("life#")}

    admitted: list[MemoryRecord] = []
    skipped: list[str] = []
    for event in doc["events"]:
        if event["status"] != "approved":
            continue
        source = f"life#{version}#{event['event_id']}"
        origin = _origin(event, doc)
        previous = existing.get(source)
        if previous is not None:
            same = (previous.type == "story"
                    and previous.summary == event["summary"]
                    and previous.event_time == event["event_time"]
                    and (previous.origin or {}) == origin)
            if not same:
                raise ValueError(
                    f"living record {source} already exists with different "
                    "content")
            skipped.append(previous.id)
            continue
        admitted.append(MemoryRecord(
            type="story", summary=event["summary"], author="joint",
            source=source, origin=origin, event_time=event["event_time"],
        ))

    stale = [
        record.id for record in records
        if record.status == "active" and record.type == "story"
        and (record.origin or {}).get("kind") == LIFE_KIND
        and (record.origin or {}).get("life_version") != version
    ]
    if not admitted and not stale:
        return {"ok": True, "idempotent": True, "life_version": version,
                "admitted": [], "superseded": [], "skipped": sorted(skipped)}

    new_records = tape.publish_batch(admitted, supersede=stale)
    manifest = load_manifest(root / "manifest.json")
    for record in new_records:
        ensure_group(manifest, parse_id(record.id))
    save_manifest(manifest, root / "manifest.json")
    memory.invalidate_derived_state()
    return {
        "ok": True,
        "idempotent": False,
        "life_version": version,
        "admitted": [record.id for record in new_records],
        "superseded": sorted(stale),
        "skipped": sorted(skipped),
    }
