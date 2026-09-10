"""macOS Keychain storage for the DeepSeek API key.

Uses the system ``security`` tool so the key never lives in a plain file.
"""

from __future__ import annotations

import subprocess

SERVICE = "memory-machine"
ACCOUNT = "api_key"
_SECURITY = "/usr/bin/security"


def get_api_key() -> str:
    try:
        result = subprocess.run(
            [_SECURITY, "find-generic-password", "-s", SERVICE, "-a", ACCOUNT, "-w"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return ""


def set_api_key(key: str) -> bool:
    key = (key or "").strip()
    if not key:
        return False
    try:
        result = subprocess.run(
            [_SECURITY, "add-generic-password", "-s", SERVICE, "-a", ACCOUNT, "-w", key, "-U"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0
    except Exception:
        return False


def delete_api_key() -> bool:
    try:
        result = subprocess.run(
            [_SECURITY, "delete-generic-password", "-s", SERVICE, "-a", ACCOUNT],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0
    except Exception:
        return False
