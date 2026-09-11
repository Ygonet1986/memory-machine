"""The persistent tape: an append-only sequence of memory records.

Each memory record has a stable identity (``M0001``, ``M0002``, ...) and
represents a durable fact about a project: a decision, lesson, preference,
bugfix or build note. Records are immutable once written; supersession is
expressed by a later record referencing the old one, never by mutating it.
"""

from __future__ import annotations

import json
import re
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

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "summary": self.summary,
            "why": self.why,
            "files": self.files,
            "created_at": self.created_at,
            "status": self.status,
            "source": self.source,
            "derived_from": self.derived_from,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MemoryRecord":
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

    def delete(self, memory_id: str) -> bool:
        """Remove a record by id. Returns True if it existed."""
        records = self._read_all()
        before = len(records)
        records = [r for r in records if r.id != memory_id]
        if len(records) == before:
            return False
        self._rewrite(records)
        return True

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
