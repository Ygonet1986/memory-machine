"""Companion creator backend (C2): draft, preview, approval, root snapshot.

Owns the life documents of one root (``synthetic_life/``): the recoverable
draft, the read-only preview of what an approval would publish, and the
root-local transaction that writes ``current.json`` + ``history/vN.json``.
Tape publication itself stays in C3. All writes are explicit; reads never
create or change files (Lia roots stay untouched without an approval act).
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from .companion_life import validate_life

STAGING_NAME = ".publish"
JOURNAL_NAME = "journal.json"


class CompanionCreator:
    """One root's synthetic-life drafts and approved snapshots."""

    def __init__(self, root: Path, *, self_id: str = "lia",
                 continuity_id: str = "main") -> None:
        self.root = Path(root)
        self.self_id = self_id
        self.continuity_id = continuity_id
        self.life_dir = self.root / "synthetic_life"

    # ------------------------------------------------------------- helpers

    @property
    def draft_path(self) -> Path:
        return self.life_dir / "draft.json"

    @property
    def current_path(self) -> Path:
        return self.life_dir / "current.json"

    @property
    def journal_path(self) -> Path:
        return self.life_dir / JOURNAL_NAME

    @property
    def staging_path(self) -> Path:
        return self.life_dir / STAGING_NAME

    def history_path(self, version: int) -> Path:
        return self.life_dir / "history" / f"v{version}.json"

    def _check_continuity(self, doc: dict[str, Any]) -> None:
        if doc["world"]["continuity_id"] != self.continuity_id:
            raise ValueError(
                "life world.continuity_id does not match this relationship")

    def _validated(self, doc: dict[str, Any]) -> dict[str, Any]:
        normalized = validate_life(doc, self_id=self.self_id)
        self._check_continuity(normalized)
        return normalized

    @staticmethod
    def _read(path: Path) -> dict[str, Any] | None:
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _write_json(path: Path, value: dict[str, Any]) -> None:
        """Atomic single-file write (fsync + replace)."""
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=path.parent,
                prefix=f".{path.name}.", delete=False,
            ) as handle:
                temp_path = Path(handle.name)
                json.dump(value, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, path)
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)

    # --------------------------------------------------------------- draft

    def load_draft(self) -> dict[str, Any] | None:
        self._recover()
        doc = self._read(self.draft_path)
        if doc is None:
            return None
        return self._validated(doc)

    def save_draft(self, doc: dict[str, Any]) -> dict[str, Any]:
        normalized = self._validated(doc)
        if normalized["status"] != "draft":
            raise ValueError("the creator draft must have status 'draft'")
        self._recover()
        self._write_json(self.draft_path, normalized)
        return {"ok": True, "events": len(normalized["events"]),
                "path": str(self.draft_path)}

    def clear_draft(self) -> bool:
        existed = self.draft_path.exists()
        self.draft_path.unlink(missing_ok=True)
        return existed

    # -------------------------------------------------------------- approve

    def load_current(self) -> dict[str, Any] | None:
        self._recover()
        doc = self._read(self.current_path)
        if doc is None:
            return None
        return self._validated(doc)

    def history_versions(self) -> list[int]:
        self._recover()
        history = self.life_dir / "history"
        if not history.is_dir():
            return []
        versions = []
        for path in sorted(history.glob("v*.json")):
            try:
                versions.append(int(path.stem[1:]))
            except ValueError:
                continue
        return sorted(versions)

    def load_version(self, version: int) -> dict[str, Any] | None:
        self._recover()
        path = self.history_path(version)
        if not path.exists():
            return None
        return self._validated(json.loads(path.read_text(encoding="utf-8")))

    def approve(self, doc: dict[str, Any] | None = None) -> dict[str, Any]:
        """Publish one approved life version under this root, atomically."""
        source = doc if doc is not None else self.load_draft()
        if source is None:
            raise ValueError("no draft to approve")
        normalized = self._validated(source)
        if normalized["status"] != "approved":
            raise ValueError("only an approved life version can be published")
        version = normalized["life_version"]
        current = self.load_current()
        if current is not None and current["life_version"] == version:
            if current == normalized:
                return {"ok": True, "idempotent": True, "life_version": version,
                        "events": len(normalized["events"])}
            raise ValueError(
                f"life version v{version} is already published with "
                "different content")
        if current is not None and version < current["life_version"]:
            raise ValueError(
                "life_version must increase (current is "
                f"v{current['life_version']})")

        staging = self.staging_path
        if staging.exists():
            shutil.rmtree(staging)
        staging.mkdir(parents=True)
        self._write_json(staging / "current.json", normalized)
        self._write_json(staging / f"history_v{version}.json", normalized)
        self._write_json(self.journal_path, {"life_version": version})
        self._apply_transaction(version)
        self.clear_draft()
        return {"ok": True, "idempotent": False, "life_version": version,
                "events": len(normalized["events"]),
                "plan": self.preview(normalized)["records"]}

    def _apply_transaction(self, version: int) -> None:
        history_target = self.history_path(version)
        history_target.parent.mkdir(parents=True, exist_ok=True)
        staged_history = self.staging_path / f"history_v{version}.json"
        if staged_history.exists():
            os.replace(staged_history, history_target)
        staged_current = self.staging_path / "current.json"
        if staged_current.exists():
            os.replace(staged_current, self.current_path)
        shutil.rmtree(self.staging_path, ignore_errors=True)
        self.journal_path.unlink(missing_ok=True)

    def recover(self) -> dict[str, Any]:
        """Re-apply a journaled publication interrupted mid-transaction."""
        return self._recover()

    def _recover(self) -> dict[str, Any]:
        journal = self._read(self.journal_path)
        if journal is None:
            if self.staging_path.exists():
                shutil.rmtree(self.staging_path, ignore_errors=True)
            return {"ok": True, "recovered": False}
        version = int(journal.get("life_version") or 0)
        if not version:
            raise RuntimeError("life journal is corrupted")
        if self.staging_path.exists():
            self._apply_transaction(version)
            return {"ok": True, "recovered": True, "life_version": version}
        current = self._read(self.current_path)
        if current is not None and int(current.get("life_version") or 0) == version:
            self.journal_path.unlink(missing_ok=True)
            return {"ok": True, "recovered": True, "life_version": version}
        raise RuntimeError("unrecoverable life transaction")

    # -------------------------------------------------------------- preview

    def preview(self, doc: dict[str, Any] | None = None) -> dict[str, Any]:
        """What an approval would publish, without writing anything."""
        source = doc if doc is not None else self.load_draft()
        if source is None:
            raise ValueError("nothing to preview")
        normalized = self._validated(source)
        records = []
        for event in normalized["events"]:
            records.append({
                "event_id": event["event_id"],
                "summary": event["summary"],
                "event_time": event["event_time"],
                "status": event["status"],
                "would_publish": event["status"] == "approved",
                "source": f"life#{normalized['life_version']}#{event['event_id']}",
                "origin": {
                    "kind": "synthetic_life_event",
                    "event_id": event["event_id"],
                    "life_version": normalized["life_version"],
                    "continuity_id": normalized["world"]["continuity_id"],
                    "sheet_version": normalized["sheet_version"],
                },
            })
        return {
            "ok": True,
            "life_version": normalized["life_version"],
            "status": normalized["status"],
            "events": len(records),
            "records": records,
        }
