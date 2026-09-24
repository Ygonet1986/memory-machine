"""Creator gallery and review helpers (C5a).

Read-only listings (templates, relationships), timeline and revision diff,
plus two explicit operations: retiring an approved event (a new approved
version that supersedes it on the tape) and copying a relationship into a
brand-new root that inherits no conversations.
"""

from __future__ import annotations

import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .companion_creator import CompanionCreator
from .companion_life import time_sort_key, validate_life
from .companion_life_admission import admit_life
from .companion_memory import CompanionMemory
from .companion_session import CompanionSession


_TOKEN_RE = re.compile(r"[a-zà-ÿ0-9]+")
_STOPWORDS = {"para", "uma", "com", "sobre", "entre", "depois", "antes"}


def _tokens(text: str) -> set[str]:
    return {token for token in _TOKEN_RE.findall((text or "").casefold())
            if len(token) >= 4 and token not in _STOPWORDS}


def list_templates(repo_root: Path) -> list[dict[str, Any]]:
    """Character templates available in the repository (persona + life)."""
    personas = Path(repo_root) / "personas"
    if not personas.is_dir():
        return []
    rows: list[dict[str, Any]] = []
    for folder in sorted(personas.iterdir()):
        if not folder.is_dir():
            continue
        persona_versions = sorted(
            int(path.stem[1:]) for path in folder.glob("v*.json")
            if path.stem[1:].isdigit())
        life_dir = folder / "life"
        life_versions = sorted(
            int(path.stem[1:]) for path in life_dir.glob("v*.json")
            if path.stem[1:].isdigit()) if life_dir.is_dir() else []
        if persona_versions or life_versions:
            rows.append({"slug": folder.name,
                         "persona_versions": persona_versions,
                         "life_versions": life_versions})
    return rows


def list_relationships(base: Path) -> list[dict[str, Any]]:
    """Existing relationships under ``<base>/companion/<p>/<c>/<k>/``."""
    root = Path(base) / "companion"
    rows: list[dict[str, Any]] = []
    if not root.is_dir():
        return rows
    for person in sorted(p for p in root.iterdir() if p.is_dir()):
        for character in sorted(p for p in person.iterdir() if p.is_dir()):
            for continuity in sorted(p for p in character.iterdir() if p.is_dir()):
                current = continuity / "persona" / "current.json"
                if not current.exists():
                    continue
                sheet = json.loads(current.read_text(encoding="utf-8"))
                life = continuity / "synthetic_life" / "current.json"
                life_version = 0
                if life.exists():
                    life_version = int(json.loads(
                        life.read_text(encoding="utf-8")).get("life_version") or 0)
                rows.append({
                    "person": person.name,
                    "character": character.name,
                    "continuity": continuity.name,
                    "name": str(sheet.get("name") or character.name),
                    "persona_version": int(sheet.get("version") or 0),
                    "life_version": life_version,
                })
    return rows


def life_timeline(doc: dict[str, Any], *, self_id: str = "lia") -> list[dict[str, Any]]:
    """Events ordered by partial time with display fields (read-only)."""
    normalized = validate_life(doc, self_id=self_id)
    events = sorted(normalized["events"],
                    key=lambda event: (time_sort_key(event["event_time"]),
                                       event["event_id"]))
    return [{
        "event_id": event["event_id"],
        "title": event["title"],
        "summary": event["summary"],
        "event_time": event["event_time"],
        "time_precision": event["time_precision"],
        "place": event["place"],
        "status": event["status"],
        "causes": list(event["causes"]),
        "effects": list(event["effects"]),
        "participants": [item["id"] for item in event["participants"]],
        "generator": event["provenance"]["generator"],
    } for event in events]


def life_diff(old: dict[str, Any], new: dict[str, Any], *,
              self_id: str = "lia") -> dict[str, Any]:
    """Field-level difference between two life versions (read-only)."""
    before = validate_life(old, self_id=self_id)
    after = validate_life(new, self_id=self_id)
    old_events = {event["event_id"]: event for event in before["events"]}
    new_events = {event["event_id"]: event for event in after["events"]}
    added = sorted(set(new_events) - set(old_events))
    removed = sorted(set(old_events) - set(new_events))
    changed: dict[str, list[str]] = {}
    for event_id in sorted(set(old_events) & set(new_events)):
        fields = [key for key in old_events[event_id]
                  if key != "life_version"
                  and old_events[event_id][key] != new_events[event_id][key]]
        if fields:
            changed[event_id] = fields
    return {
        "old_version": before["life_version"],
        "new_version": after["life_version"],
        "added": added,
        "removed": removed,
        "changed": changed,
    }


def retire_event(root: Path, event_id: str, *, self_id: str = "lia",
                 continuity_id: str = "main",
                 approved_by: str = "owner") -> dict[str, Any]:
    """Retire one approved event: a new approved version supersedes it."""
    creator = CompanionCreator(root, self_id=self_id,
                               continuity_id=continuity_id)
    current = creator.load_current()
    if current is None:
        raise ValueError("no approved life version in this root")
    target = next((event for event in current["events"]
                   if event["event_id"] == event_id), None)
    if target is None:
        raise ValueError(f"unknown event: {event_id}")
    if target["status"] == "retired":
        raise ValueError(f"event already retired: {event_id}")
    updated = json.loads(json.dumps(current))
    updated["life_version"] = current["life_version"] + 1
    for event in updated["events"]:
        event["life_version"] = updated["life_version"]
        if event["event_id"] == event_id:
            event["status"] = "retired"
            event["approved_at"] = ""
            event["approved_by"] = ""
    updated["approved_at"] = datetime.now(timezone.utc).isoformat()
    updated["approved_by"] = approved_by
    creator.approve(updated)
    published = admit_life(root, self_id=self_id,
                           continuity_id=continuity_id)
    return {"ok": True, "retired": event_id,
            "life_version": updated["life_version"], "published": published}


def deletion_impact(root: Path, event_id: str, *, self_id: str = "lia",
                    continuity_id: str = "main") -> dict[str, Any]:
    """What removing one published event would touch (read-only)."""
    creator = CompanionCreator(root, self_id=self_id,
                               continuity_id=continuity_id)
    current = creator.load_current()
    if current is None:
        raise ValueError("no approved life version in this root")
    memory = CompanionMemory(root)
    records = memory.tape.read()
    record = next(
        (item for item in records
         if item.source == f"life#{current['life_version']}#{event_id}"), None)
    target = {"record_id": record.id if record else "",
              "active": bool(record and record.status == "active"),
              "summary": record.summary if record else ""}
    derived: list[str] = []
    if record is not None:
        derived = [item.id for item in records
                   if record.id in item.derived_from]
    mentions: list[str] = []
    if record is not None:
        needle = _tokens(record.summary)
        if len(needle) >= 3:
            needed = max(3, len(needle) // 2)
            mentions = [
                item.id for item in records
                if item.id != record.id and item.status == "active"
                and len(needle & _tokens(f"{item.summary} {item.why}")) >= needed
            ]
    return {"event_id": event_id, "life_version": current["life_version"],
            "target": target, "derived": derived, "mentions": mentions}


def copy_relationship(base: Path, person_id: str, source_character: str,
                      new_character: str, *, continuity: str = "main",
                      self_id: str = "lia", publish: bool = True) -> dict[str, Any]:
    """Copy persona + life into a fresh root that inherits no conversations."""
    source = CompanionSession(base, person_id, source_character,
                              continuity).root
    target = CompanionSession(base, person_id, new_character, continuity).root
    if not (source / "persona" / "current.json").exists():
        raise ValueError("source relationship has no approved persona")
    if target.exists():
        raise ValueError("target relationship already exists")
    copies = [(source / "persona" / "current.json",
               target / "persona" / "current.json")]
    copies += [(path, target / "persona" / "history" / path.name)
               for path in sorted((source / "persona" / "history").glob("v*.json"))]
    life_current = source / "synthetic_life" / "current.json"
    if life_current.exists():
        copies.append((life_current, target / "synthetic_life" / "current.json"))
    copies += [(path, target / "synthetic_life" / "history" / path.name)
               for path in sorted((source / "synthetic_life" / "history").glob("v*.json"))]
    for src_path, dst_path in copies:
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_path, dst_path)
    published: dict[str, Any] | None = None
    if publish and (target / "synthetic_life" / "current.json").exists():
        published = admit_life(target, self_id=self_id,
                               continuity_id=continuity)
    return {"ok": True, "root": str(target), "published": published}
