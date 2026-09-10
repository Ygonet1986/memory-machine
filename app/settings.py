"""Application settings for the Memory Machine desktop app.

Settings are stored OUTSIDE the source tree, under the user's Application
Support directory. The API key is never committed to the repository.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

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
}


def settings_path() -> Path:
    return APP_DIR / "settings.json"


def load_settings() -> dict[str, Any]:
    data: dict[str, Any] = dict(DEFAULTS)
    path = settings_path()
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data.update(loaded)
        except (json.JSONDecodeError, OSError):
            pass
    return data


def save_settings(settings: dict[str, Any]) -> None:
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
