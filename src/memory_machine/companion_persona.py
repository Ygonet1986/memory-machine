"""Pure, deterministic Companion character sheet validation and rendering."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from .companion_memory import CompanionMemory
from .secrets import assert_clean
from .tape import MemoryRecord

_FIELDS = {"name", "version", "language", "voice", "values", "boundaries", "bio"}
_MAX_TEXT = 500


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > _MAX_TEXT:
        raise ValueError(f"{label} must have 1 to {_MAX_TEXT} characters")
    if any(ord(char) < 32 for char in value):
        raise ValueError(f"{label} must be a single line")
    text = value.strip()
    assert_clean(text)
    return text


def _items(value: Any, label: str, minimum: int, maximum: int) -> list[str]:
    if not isinstance(value, list) or not minimum <= len(value) <= maximum:
        raise ValueError(f"{label} requires {minimum} to {maximum} items")
    return [_text(item, label) for item in value]


def validate_sheet(sheet: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalize an approved-sheet candidate; reject unknown fields."""
    if not isinstance(sheet, dict) or sheet.keys() != _FIELDS:
        raise ValueError("sheet fields must match the Companion persona schema")
    version = sheet["version"]
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise ValueError("version must be an integer >= 1")
    if sheet["language"] != "pt-BR":
        raise ValueError("language must be pt-BR")
    return {
        "name": _text(sheet["name"], "name"),
        "version": version,
        "language": "pt-BR",
        "voice": _text(sheet["voice"], "voice"),
        "values": _items(sheet["values"], "values", 1, 8),
        "boundaries": _items(sheet["boundaries"], "boundaries", 1, 8),
        "bio": _items(sheet["bio"], "bio", 3, 12),
    }


def render_persona_prompt(sheet: dict[str, Any]) -> str:
    """Render one system-prompt block without reading or writing a root."""
    spec = validate_sheet(sheet)
    lines = [
        f"Personagem: {spec['name']} (versão v{spec['version']}; idioma pt-BR).",
        "Você é uma personagem de IA; seja honesta sobre sua natureza e suas limitações.",
        f"Voz: {spec['voice']}",
        "Valores:",
        *(f"- {item}" for item in spec["values"]),
        "Limites:",
        *(f"- {item}" for item in spec["boundaries"]),
        "Biografia ficcional:",
        *(f"- {item}" for item in spec["bio"]),
        "Memórias ficcionais e histórias não são fatos da vida real da pessoa.",
        "Use apenas memórias com origem identificada; não invente eventos compartilhados.",
        "Respeite pausas e a autonomia da pessoa, sem culpa ou exclusividade.",
    ]
    return "\n".join(lines)


def _write_json(path: Path, value: dict[str, Any]) -> None:
    """Replace one JSON document atomically, without leaving a partial file."""
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


class CompanionPersona:
    """Approved character revisions within one explicitly selected Companion root."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.memory = CompanionMemory(self.root)
        self.persona_dir = self.root / "persona"

    def load(self) -> dict[str, Any] | None:
        path = self.persona_dir / "current.json"
        if not path.exists():
            return None
        return validate_sheet(json.loads(path.read_text(encoding="utf-8")))

    def facts(self) -> list[MemoryRecord]:
        current = self.load()
        if current is None:
            return []
        version = f"v{current['version']}"
        return [
            record for record in self.memory.active()
            if record.type == "persona"
            and record.origin == {"kind": "persona_revision", "version": version}
        ]

    @staticmethod
    def _record(fact: str, version: int) -> MemoryRecord:
        revision = f"v{version}"
        return MemoryRecord(
            type="persona", summary=fact, author="joint", source=f"persona#{revision}",
            origin={"kind": "persona_revision", "version": revision},
        )

    def create(self, sheet: dict[str, Any]) -> list[MemoryRecord]:
        spec = validate_sheet(sheet)
        current = self.load()
        if current is not None:
            if current == spec:
                return self.facts()
            raise ValueError("persona already exists; use revise for a new version")
        if spec["version"] != 1 or (self.persona_dir / "history" / "v1.json").exists():
            raise ValueError("a new persona must start at v1 without existing history")
        records = [
            self.memory.add_candidate(
                {"type": "persona", "summary": fact, "approved_version": "v1"},
                author="joint",
            )
            for fact in spec["bio"]
        ]
        _write_json(self.persona_dir / "history" / "v1.json", spec)
        _write_json(self.persona_dir / "current.json", spec)
        return records

    def revise(self, changes: dict[str, Any]) -> list[MemoryRecord]:
        current = self.load()
        if current is None:
            raise ValueError("create the persona before revising")
        if not isinstance(changes, dict) or not changes or "version" in changes:
            raise ValueError("changes must omit version and contain at least one field")
        if "name" in changes and changes["name"] != current["name"]:
            raise ValueError("a character name belongs to its root")
        next_sheet = validate_sheet({**current, **changes, "version": current["version"] + 1})
        path = self.persona_dir / "history" / f"v{next_sheet['version']}.json"
        if path.exists():
            raise ValueError("revision already exists")
        old_facts = self.facts()
        if len(old_facts) != len(current["bio"]):
            raise ValueError("active persona facts do not match the approved revision")
        new_facts: list[MemoryRecord] = []
        for index, old in enumerate(old_facts):
            if index < len(next_sheet["bio"]):
                replacement = self._record(next_sheet["bio"][index], next_sheet["version"])
            else:
                replacement = self._record(
                    f"Fato retirado da biografia na versão v{next_sheet['version']}.",
                    next_sheet["version"],
                )
                replacement.status = "superseded"
            new_facts.append(self.memory.supersede(old.id, replacement))
        for fact in next_sheet["bio"][len(old_facts):]:
            new_facts.append(self.memory.add_candidate(
                {"type": "persona", "summary": fact,
                 "approved_version": f"v{next_sheet['version']}"},
                author="joint",
            ))
        _write_json(path, next_sheet)
        _write_json(self.persona_dir / "current.json", next_sheet)
        return [record for record in new_facts if record.status == "active"]
