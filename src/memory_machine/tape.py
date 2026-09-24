"""The persistent tape: an append-only sequence of memory records.

Each memory record has a stable identity (``M0001``, ``M0002``, ...) and
represents a durable fact about a project: a decision, lesson, preference,
bugfix or build note. Records are immutable once written; supersession is
expressed by a later record referencing the old one, never by mutating it.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .secrets import assert_clean

PROJECT_TYPES = {"decision", "lesson", "preference", "bugfix", "build"}

ID_RE = re.compile(r"^M(\d+)$")


def format_id(num: int) -> str:
    return f"M{num:04d}"


def parse_id(memory_id: str) -> int:
    m = ID_RE.match(memory_id.strip())
    if not m:
        raise ValueError(f"invalid memory id: {memory_id!r}")
    return int(m.group(1))


def default_views(record: "MemoryRecord") -> list[str]:
    """Deterministic organizational projections of a record (no duplication)."""
    views: list[str] = []
    if record.created_at:
        views.append(f"time/{record.created_at[:7]}")
    if record.type:
        views.append(f"type/{record.type}")
    if record.source:
        views.append(f"source/{record.source.split('#', 1)[0]}")
    return views


@dataclass
class MemoryRecord:
    type: str
    summary: str
    why: str = ""
    files: list[str] = field(default_factory=list)
    id: str = ""
    created_at: str = ""
    status: str = "active"
    source: str = ""
    derived_from: list[str] = field(default_factory=list)
    views: list[str] = field(default_factory=list)
    source_span: tuple[int, int] = ()
    source_document: str = ""
    trilepsia: dict[str, Any] = field(default_factory=dict)
    origin: dict[str, Any] = field(default_factory=dict)
    author: str = ""
    event_time: str = ""
    supersedes: str = ""

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "id": self.id,
            "type": self.type,
            "summary": self.summary,
            "why": self.why,
            "files": self.files,
            "created_at": self.created_at,
            "status": self.status,
            "source": self.source,
            "derived_from": self.derived_from,
            "views": self.views,
        }
        if self.source_document:
            d["source_document"] = self.source_document
        if self.source_span:
            d["source_span"] = [int(self.source_span[0]), int(self.source_span[1])]
        if self.trilepsia:
            d["trilepsia"] = self.trilepsia
        if self.origin:
            d["origin"] = self.origin
        if self.author:
            d["author"] = self.author
        if self.event_time:
            d["event_time"] = self.event_time
        if self.supersedes:
            d["supersedes"] = self.supersedes
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MemoryRecord":
        span = data.get("source_span")
        if isinstance(span, (list, tuple)) and len(span) == 2:
            span = (int(span[0]), int(span[1]))
        else:
            span = ()
        return cls(
            id=str(data.get("id") or ""),
            type=str(data.get("type") or ""),
            summary=str(data.get("summary") or ""),
            why=str(data.get("why") or ""),
            files=list(data.get("files") or []),
            created_at=str(data.get("created_at") or ""),
            status=str(data.get("status") or "active"),
            source=str(data.get("source") or ""),
            derived_from=list(data.get("derived_from") or []),
            views=list(data.get("views") or []),
            source_span=span,
            source_document=str(data.get("source_document") or ""),
            trilepsia=dict(data.get("trilepsia") or {}),
            origin=dict(data.get("origin") or {}),
            author=str(data.get("author") or ""),
            event_time=str(data.get("event_time") or ""),
            supersedes=str(data.get("supersedes") or ""),
        )

    def text(self) -> str:
        """Compact textual representation used for agent context."""
        files = ", ".join(self.files) if self.files else "-"
        return f"[{self.id}] [{self.type}] {self.summary} (why: {self.why or '-'}; files: {files})"


class Tape:
    """Append-only JSONL storage for memory records."""

    def __init__(self, path: Path):
        self.path = path

    def exists(self) -> bool:
        return self.path.exists()

    @property
    def highwater_path(self) -> Path:
        return self.path.with_name(self.path.name + ".highwater")

    def _highwater(self) -> int:
        try:
            return max(0, int(self.highwater_path.read_text(encoding="ascii").strip()))
        except (OSError, ValueError):
            return 0

    def _reserve_highwater(self, value: int) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="ascii", dir=self.path.parent,
                prefix=f".{self.highwater_path.name}.", delete=False,
            ) as fh:
                temp_path = Path(fh.name)
                fh.write(f"{value}\n")
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(temp_path, self.highwater_path)
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)

    def _read_all(self) -> list[MemoryRecord]:
        if not self.path.exists():
            return []
        out: list[MemoryRecord] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(MemoryRecord.from_dict(json.loads(line)))
            except (json.JSONDecodeError, KeyError):
                continue
        return out

    def read(self) -> list[MemoryRecord]:
        return self._read_all()

    def last(self) -> MemoryRecord | None:
        records = self._read_all()
        return records[-1] if records else None

    def max_id_num(self) -> int:
        best = 0
        for rec in self._read_all():
            if rec.id:
                try:
                    best = max(best, parse_id(rec.id))
                except ValueError:
                    pass
        return best

    def append(self, record: MemoryRecord, memory_id: str | None = None) -> MemoryRecord:
        """Append a record, assigning a stable id if none is provided."""
        if memory_id:
            record.id = memory_id
        elif not record.id:
            record.id = format_id(self.max_id_num() + 1)
        if not record.created_at:
            record.created_at = datetime.now(timezone.utc).isoformat()
        for view in default_views(record):
            if view not in record.views:
                record.views.append(view)
        assert_clean(record.text())
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")
        return record

    def read_range(self, start_num: int, end_num: int) -> list[MemoryRecord]:
        return [r for r in self._read_all() if start_num <= parse_id(r.id) <= end_num]

    def _rewrite(self, records: list[MemoryRecord]) -> None:
        self.path.write_text(
            "".join(json.dumps(r.to_dict(), ensure_ascii=False) + "\n" for r in records),
            encoding="utf-8",
        )

    def _rewrite_atomic(self, records: list[MemoryRecord]) -> None:
        """Replace the tape in one step for Companion administrative operations."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self.path.parent,
                prefix=f".{self.path.name}.", delete=False,
            ) as fh:
                temp_path = Path(fh.name)
                for record in records:
                    fh.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(temp_path, self.path)
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)

    def supersede(self, memory_id: str, replacement: MemoryRecord) -> tuple[MemoryRecord, list[str]]:
        """Add a correction and deactivate its source and derived descendants.

        This explicit operation is called by Companion; legacy append/status
        operations retain their existing behavior.
        """
        records = self._read_all()
        previous = next((r for r in records if r.id == memory_id), None)
        if previous is None or previous.status not in {"active", "archived"}:
            raise ValueError(f"no eligible memory to supersede: {memory_id}")
        if replacement.id or replacement.supersedes or memory_id in replacement.derived_from:
            raise ValueError("replacement must be a fresh record with a separate supersession edge")
        if replacement.type != previous.type:
            raise ValueError("a correction preserves the record kind")
        replacement.id = format_id(self.max_id_num() + 1)
        replacement.supersedes = memory_id
        if not replacement.created_at:
            replacement.created_at = datetime.now(timezone.utc).isoformat()
        for view in default_views(replacement):
            if view not in replacement.views:
                replacement.views.append(view)
        assert_clean(replacement.text())
        affected = {memory_id}
        while True:
            new = {r.id for r in records if affected.intersection(r.derived_from)}
            if new.issubset(affected):
                break
            affected.update(new)
        for record in records:
            if record.id in affected:
                record.status = "superseded"
        self._rewrite_atomic([*records, replacement])
        return replacement, sorted(affected)

    def delete(self, memory_id: str) -> bool:
        """Remove a record by id. Returns True if it existed."""
        records = self._read_all()
        before = len(records)
        records = [r for r in records if r.id != memory_id]
        if len(records) == before:
            return False
        self._rewrite(records)
        return True

    def delete_many(self, memory_ids: list[str]) -> int:
        """Remove several records in a single rewrite. Returns the count."""
        ids = set(memory_ids)
        records = self._read_all()
        kept = [r for r in records if r.id not in ids]
        removed = len(records) - len(kept)
        if removed:
            self._rewrite(kept)
        return removed

    def delete_cascade(self, memory_id: str) -> list[str]:
        """Erase a record, source turns, derivatives and dependent corrections.

        The local high-water mark reserves removed IDs before replacing the
        tape; a future append cannot attach a stale reference to a reused ID.
        Legacy single-record delete remains unchanged.
        """
        records = self._read_all()
        if not any(record.id == memory_id for record in records):
            return []
        by_id = {record.id: record for record in records}
        removed = {memory_id}
        while True:
            children = {
                record.id for record in records
                if removed.intersection(record.derived_from) or record.supersedes in removed
            }
            source_turns = {
                parent_id
                for record in records if record.id in removed
                for parent_id in record.derived_from
                if parent_id in by_id and by_id[parent_id].type in {"question", "reply"}
            }
            expanded = children | source_turns
            if expanded.issubset(removed):
                break
            removed.update(expanded)
        self._reserve_highwater(self.max_id_num())
        self._rewrite_atomic([record for record in records if record.id not in removed])
        return sorted(removed)

    def set_status(self, memory_id: str, status: str) -> bool:
        """Set a record's status (active/archived/superseded). Returns True if found."""
        records = self._read_all()
        for r in records:
            if r.id == memory_id:
                r.status = status
                self._rewrite(records)
                return True
        return False

    def set_status_many(self, memory_ids: list[str], status: str) -> int:
        """Set the status of several records in a single rewrite. Returns the count."""
        ids = set(memory_ids)
        records = self._read_all()
        changed = 0
        for r in records:
            if r.id in ids:
                r.status = status
                changed += 1
        if changed:
            self._rewrite(records)
        return changed

    def __len__(self) -> int:
        return len(self._read_all())
