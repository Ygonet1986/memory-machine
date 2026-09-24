"""Headless Companion backend for the desktop app (pure Python, no Qt).

Owns one relationship root
(``<memory_root>/companion/<person>/<character>/<continuity>``), the approved
persona, the "what I remember" operations (list, correct, delete) and one chat
turn through ``CompanionEngine``. Kept Qt-free so CI can test it headlessly.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from memory_machine.companion_engine import CompanionEngine
from memory_machine.companion_memory import CompanionMemory
from memory_machine.companion_persona import CompanionPersona
from memory_machine.companion_session import CompanionSession
from memory_machine.llm import LLMClient
from memory_machine.tape import MemoryRecord

from .settings import load_settings


def template_path() -> Path:
    """Resolve the Lia v1 template inside a PyInstaller bundle or the repo."""
    frozen = getattr(sys, "_MEIPASS", "")
    if frozen:
        candidate = Path(frozen) / "personas" / "lia" / "v1.json"
        if candidate.exists():
            return candidate
    return Path(__file__).resolve().parents[1] / "personas" / "lia" / "v1.json"


CHAT_TYPES = ("person_report", "episode", "story", "hypothesis")


class CompanionBackend:
    """One relationship (person x character x continuity) over the core."""

    def __init__(
        self,
        person_id: str = "local",
        character_id: str = "lia",
        continuity_id: str = "main",
        *,
        client: Any = None,
        base: str | Path | None = None,
    ) -> None:
        settings = load_settings()
        self._settings = settings
        self._client = client
        self._base = Path(base if base is not None
                          else settings["memory_root"]).expanduser()
        self.session = CompanionSession(
            self._base, person_id, character_id, continuity_id
        )

    # ------------------------------------------------------------- helpers

    def _memory(self) -> CompanionMemory:
        return CompanionMemory(self.session.root)

    def _persona(self) -> CompanionPersona:
        return CompanionPersona(self.session.root)

    def _llm(self) -> Any:
        if self._client is None:
            settings = self._settings
            self._client = LLMClient(
                settings["base_url"], settings["api_key"], settings["model"]
            )
        return self._client

    @staticmethod
    def _row(record: MemoryRecord) -> dict[str, Any]:
        return {
            "memory_id": record.id,
            "type": record.type,
            "summary": record.summary,
            "origin": dict(record.origin or {}),
            "author": record.author,
            "event_time": record.event_time,
            "created_at": record.created_at,
        }

    # -------------------------------------------------------------- persona

    def persona(self) -> dict[str, Any] | None:
        return self._persona().load()

    def approve_persona(self, template: str | Path | None = None) -> dict[str, Any]:
        path = Path(template) if template is not None else template_path()
        try:
            sheet = json.loads(Path(path).read_text(encoding="utf-8"))
            records = self._persona().create(sheet)
        except (ValueError, OSError) as error:
            return {"ok": False, "error": str(error)}
        return {
            "ok": True,
            "sheet": self._persona().load(),
            "records": [record.id for record in records],
        }

    # ---------------------------------------------------------------- panel

    def memories(self) -> list[dict[str, Any]]:
        return [
            self._row(record) for record in self._memory().active()
            if record.type in CHAT_TYPES
        ]

    def correct(self, memory_id: str, new_summary: str) -> dict[str, Any]:
        text = (new_summary or "").strip()
        if not text:
            return {"ok": False, "error": "empty correction"}
        memory = self._memory()
        old = next(
            (record for record in memory.tape.read()
             if record.id == memory_id and record.status == "active"),
            None,
        )
        if old is None:
            return {"ok": False, "error": f"no active memory: {memory_id}"}
        replacement = MemoryRecord(
            type=old.type, summary=text,
            author=old.author or "person", event_time=old.event_time,
        )
        try:
            record = memory.supersede(memory_id, replacement)
        except ValueError as error:
            return {"ok": False, "error": str(error)}
        return {"ok": True, "record": self._row(record),
                "replaced": memory_id}

    def delete(self, memory_id: str) -> dict[str, Any]:
        removed = self._memory().delete(memory_id)
        if not removed:
            return {"ok": False, "error": f"unknown memory: {memory_id}"}
        return {"ok": True, "removed": removed}

    # ----------------------------------------------------------------- chat

    def turn(self, message: str, *, save: bool = True) -> dict[str, Any]:
        engine = CompanionEngine(self.session, self._llm())
        try:
            result = engine.reply(message, save=save)
        except ValueError as error:
            return {"ok": False, "error": str(error)}
        result["ok"] = True
        return result
