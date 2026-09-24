"""Synthetic-life admission (C3): publish an approved life to the tape.

One ``story`` record per approved event, sourced ``life#<version>#<event_id>``
with ``origin.kind="synthetic_life_event"`` and **no conversation turn**.
Versioning is a single batch: newly approved events are appended and every
older active synthetic-life record is superseded in the same atomic rewrite,
so a reload can never resurrect a retired version.
"""

from __future__ import annotations

import json
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


PUBLICATION_JOURNAL = "publication.json"


def _journal_path(root: Path) -> Path:
    return Path(root) / "synthetic_life" / PUBLICATION_JOURNAL


def publish_life(root: Path, doc: dict[str, Any] | None = None, *,
                 self_id: str = "lia", continuity_id: str = "main") -> dict[str, Any]:
    """Approve a life version **and** admit it in one recoverable operation.

    A publication journal (carrying the document) is written first; the
    snapshot approval and the tape admission are both idempotent, so a crash
    between them is repaired by ``recover_publication``. A failure never
    leaves the root claiming a version whose events are missing.
    """
    root = Path(root)
    creator = CompanionCreator(root, self_id=self_id,
                               continuity_id=continuity_id)
    if doc is None:
        doc = creator.load_draft()
        if doc is None:
            raise ValueError("no life document to publish")
    normalized = creator._validated(doc)
    if normalized["status"] != "approved":
        raise ValueError("only an approved life version can be published")
    creator.write_json_atomic(_journal_path(root), {"document": normalized})
    return _finish_publication(root, creator, self_id, continuity_id,
                               recovered=False)


def _finish_publication(root: Path, creator: CompanionCreator, self_id: str,
                        continuity_id: str, *, recovered: bool) -> dict[str, Any]:
    journal = _journal_path(root)
    payload = json.loads(journal.read_text(encoding="utf-8"))
    document = payload["document"]
    approved = creator.approve(document)
    published = admit_life(root, self_id=self_id,
                           continuity_id=continuity_id)
    journal.unlink(missing_ok=True)
    return {
        "ok": True,
        "recovered": recovered,
        "idempotent": bool(approved.get("idempotent"))
        and bool(published.get("idempotent")),
        "life_version": int(document["life_version"]),
        "approved": approved,
        "published": published,
    }


def recover_publication(root: Path, *, self_id: str = "lia",
                        continuity_id: str = "main") -> dict[str, Any]:
    """Complete a publication interrupted between approval and admission."""
    root = Path(root)
    journal = _journal_path(root)
    if not journal.exists():
        return {"ok": True, "recovered": False}
    creator = CompanionCreator(root, self_id=self_id,
                               continuity_id=continuity_id)
    return _finish_publication(root, creator, self_id, continuity_id,
                               recovered=True)
