"""Cross-session memory: session metadata and cross-session search.

Sessions live under ``<base>/sessions/<id>/``. Each session keeps a small
``session.json`` with its summary. Cross-session search scans the other
sessions' tapes with BM25 and returns the most relevant memories, so a new
session can recall decisions made in previous ones.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from .retrieval import rank
from .tape import Tape


def sessions_dir_for(root: Path) -> Path | None:
    """Return the sessions dir when ``root`` is a session store, else None."""
    root = Path(root)
    return root.parent if root.parent.name == "sessions" else None


def session_meta_path(root: Path) -> Path:
    return Path(root) / "session.json"


def load_session_meta(root: Path) -> dict[str, Any]:
    p = session_meta_path(root)
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def save_session_meta(root: Path, *, session_id: str, summary: str = "") -> dict[str, Any]:
    meta = load_session_meta(root)
    now = datetime.now().isoformat()
    meta.setdefault("id", session_id)
    meta.setdefault("created_at", now)
    meta["updated_at"] = now
    if summary:
        meta["summary"] = summary
    path = session_meta_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return meta


def list_sessions(sessions_dir: Path) -> list[dict[str, Any]]:
    if not sessions_dir.exists():
        return []
    out: list[dict[str, Any]] = []
    for d in sorted(sessions_dir.iterdir()):
        if not d.is_dir():
            continue
        meta = load_session_meta(d)
        tape = d / "tape.jsonl"
        records = 0
        if tape.exists():
            records = sum(1 for line in tape.read_text(encoding="utf-8").splitlines() if line.strip())
        out.append({"id": d.name, **meta, "records": records})
    out.sort(key=lambda s: s.get("updated_at") or s.get("created_at") or "", reverse=True)
    return out


def search_sessions(
    sessions_dir: Path,
    query: str,
    *,
    exclude_id: str = "",
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Search the other sessions' tapes (BM25) and return the top memories."""
    if not sessions_dir.exists():
        return []
    candidates: list[tuple[str, Any]] = []
    for d in sorted(sessions_dir.iterdir()):
        if not d.is_dir() or d.name == exclude_id:
            continue
        tape_path = d / "tape.jsonl"
        if not tape_path.exists():
            continue
        for r in Tape(tape_path).read():
            if r.status == "active":
                candidates.append((d.name, r))
    if not candidates:
        return []
    docs = [f"{r.summary} {r.why}" for _, r in candidates]
    hits: list[dict[str, Any]] = []
    for i, score in rank(query, docs, limit=limit):
        sid, r = candidates[i]
        hits.append(
            {
                "session_id": sid,
                "memory_id": r.id,
                "type": r.type,
                "summary": r.summary,
                "why": r.why,
                "score": round(score, 3),
            }
        )
    return hits
