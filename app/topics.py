"""Topic store: each topic owns its own tape, named by its creation date/time.

A topic is a self-contained project root (its own tape, manifest, whiteboard
and context). Topics are identified by when they were created; an optional
human label may be attached. Memory agents are created per topic as that
topic's tape grows. Topics live under ``<memory_root>/topics/<id>/`` and are
indexed in ``<memory_root>/topics.json``.
"""

from __future__ import annotations

import json
import shutil
from datetime import date, datetime
from pathlib import Path
from typing import Any


def topics_dir(base: Path) -> Path:
    return base / "topics"


def index_path(base: Path) -> Path:
    return base / "topics.json"


def load_index(base: Path) -> dict[str, Any]:
    path = index_path(base)
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                data.setdefault("active", "")
                data.setdefault("topics", [])
                return data
        except (json.JSONDecodeError, OSError):
            pass
    return {"active": "", "topics": []}


def save_index(base: Path, index: dict[str, Any]) -> None:
    path = index_path(base)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")


def list_topics(base: Path) -> list[dict[str, Any]]:
    topics = load_index(base)["topics"]
    topics.sort(key=lambda t: t.get("created_at", ""), reverse=True)
    return topics


def active_id(base: Path) -> str:
    return load_index(base).get("active", "")


def topic_root(base: Path, topic_id: str) -> Path:
    return topics_dir(base) / topic_id


def get_topic(base: Path, topic_id: str) -> dict[str, Any] | None:
    for t in list_topics(base):
        if t["id"] == topic_id:
            return t
    return None


def create_topic(base: Path, label: str = "") -> dict[str, Any]:
    index = load_index(base)
    now = datetime.now()
    created_at = now.isoformat()
    name = now.strftime("%Y-%m-%d %H:%M")

    slug = now.strftime("%Y%m%d-%H%M%S")
    existing = {t["id"] for t in index["topics"]}
    final = slug
    n = 2
    while final in existing:
        final = f"{slug}-{n}"
        n += 1

    tdir = topics_dir(base) / final
    tdir.mkdir(parents=True, exist_ok=True)

    topic = {
        "id": final,
        "name": name,
        "label": (label or "").strip(),
        "summary": "",
        "created_at": created_at,
        "last_active": created_at,
    }
    index["topics"].append(topic)
    index["active"] = final
    save_index(base, index)
    return topic


def set_active(base: Path, topic_id: str) -> bool:
    index = load_index(base)
    if any(t["id"] == topic_id for t in index["topics"]):
        index["active"] = topic_id
        save_index(base, index)
        return True
    return False


def set_label(base: Path, topic_id: str, label: str) -> dict[str, Any] | None:
    index = load_index(base)
    for t in index["topics"]:
        if t["id"] == topic_id:
            t["label"] = (label or "").strip()
            save_index(base, index)
            return t
    return None


def set_summary(base: Path, topic_id: str, summary: str) -> dict[str, Any] | None:
    index = load_index(base)
    for t in index["topics"]:
        if t["id"] == topic_id:
            t["summary"] = (summary or "").strip()
            save_index(base, index)
            return t
    return None


def today_topic(base: Path) -> dict[str, Any] | None:
    today = date.today().isoformat()
    for t in list_topics(base):
        if (t.get("created_at") or "").startswith(today):
            return t
    return None


def most_recent_topic(base: Path) -> dict[str, Any] | None:
    """Return the topic with the most recent activity (or creation)."""
    topics = list_topics(base)
    if not topics:
        return None
    topics.sort(key=lambda t: t.get("last_active") or t.get("created_at") or "", reverse=True)
    return topics[0]


def touch_activity(base: Path, topic_id: str) -> dict[str, Any] | None:
    index = load_index(base)
    for t in index["topics"]:
        if t["id"] == topic_id:
            t["last_active"] = datetime.now().isoformat()
            save_index(base, index)
            return t
    return None


def delete_topic(base: Path, topic_id: str) -> dict[str, Any]:
    index = load_index(base)
    removed = get_topic(base, topic_id)
    if removed is None:
        return {"ok": False, "error": "topic not found"}

    shutil.rmtree(topic_root(base, topic_id), ignore_errors=True)

    index["topics"] = [t for t in index["topics"] if t["id"] != topic_id]
    if index["active"] == topic_id:
        index["active"] = index["topics"][0]["id"] if index["topics"] else ""
    save_index(base, index)
    return {"ok": True, "removed": removed, "active": index["active"]}


def display_name(topic: dict[str, Any]) -> str:
    return topic.get("label") or topic.get("name") or topic["id"]
