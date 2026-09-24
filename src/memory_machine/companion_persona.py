"""Pure, deterministic Companion character sheet validation and rendering."""

from __future__ import annotations

from typing import Any

from .secrets import assert_clean

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
