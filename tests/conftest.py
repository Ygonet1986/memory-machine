import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
for p in (str(SRC), str(ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)


@pytest.fixture(autouse=True)
def _isolate_keychain(monkeypatch):
    """Never touch the real macOS Keychain from tests."""
    try:
        from app import settings as settings_mod

        monkeypatch.setattr(settings_mod.keychain, "get_api_key", lambda: "")
        monkeypatch.setattr(settings_mod.keychain, "set_api_key", lambda key: True)
        monkeypatch.setattr(settings_mod.keychain, "delete_api_key", lambda: True)
    except Exception:
        pass
