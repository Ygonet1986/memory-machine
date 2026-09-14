"""Application settings for the Memory Machine desktop app.

Settings live OUTSIDE the source tree, under Application Support. The DeepSeek
API key is stored in the macOS Keychain (see ``keychain.py``), never in the
settings file.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from . import keychain

APP_NAME = "Memory Machine"
APP_DIR = Path(os.path.expanduser("~/Library/Application Support/MemoryMachine"))

DEFAULTS: dict[str, Any] = {
    "api_key": "",
    "model": "deepseek-v4-flash",
    "base_url": "https://api.deepseek.com",
    "memory_root": str(APP_DIR / "data"),
    "multi_topic": False,
    "auto_topic": "day",
    "auto_idle_hours": 6,
    "web_search": "auto",
    "graph_enabled": False,
    "graph_recall_mode": "off",
}


def settings_path() -> Path:
    return APP_DIR / "settings.json"


def _read_file() -> dict[str, Any]:
    path = settings_path()
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                return loaded
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _write_file(data: dict[str, Any]) -> None:
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def load_settings() -> dict[str, Any]:
    data: dict[str, Any] = dict(DEFAULTS)
    data.update(_read_file())

    key = keychain.get_api_key()
    if not key and data.get("api_key"):
        # Migrate a legacy plaintext key into the Keychain.
        key = data["api_key"].strip()
        if key and keychain.set_api_key(key):
            data["api_key"] = ""
            _write_file({k: v for k, v in data.items() if k != "api_key"})
    data["api_key"] = key
    return data


def save_settings(settings: dict[str, Any]) -> None:
    data = {k: v for k, v in settings.items() if k != "api_key"}
    key = (settings.get("api_key") or "").strip()
    if key:
        keychain.set_api_key(key)
    _write_file(data)
