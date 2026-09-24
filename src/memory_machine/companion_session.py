"""Root isolation and save-off execution for Companion turns."""

from __future__ import annotations

import json
import re
import shutil
import tempfile
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Callable, TypeVar

from .companion_memory import CompanionMemory

_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_CONFIG_PATHS = {
    "tape_path", "manifest_path", "whiteboard_path", "context_path",
    "graph_path",
}
_Result = TypeVar("_Result")


def companion_root(
    base: Path, person_id: str, character_id: str, continuity_id: str,
) -> Path:
    """Resolve a relationship root from three opaque, safe path components."""
    for component in (person_id, character_id, continuity_id):
        if not _ID.fullmatch(component):
            raise ValueError("Companion IDs must be opaque path components")
    base = Path(base).expanduser().resolve()
    root = base / "companion" / person_id / character_id / continuity_id
    for component in (root, *list(root.parents)[:4]):
        if component.is_symlink():
            raise ValueError("Companion root cannot traverse a symlink")
    if not root.resolve().is_relative_to(base):
        raise ValueError("Companion root escapes its base")
    return root


def _check_local_files(root: Path) -> None:
    """Reject links and config paths that could escape a temporary clone."""
    if root.is_symlink() or any(parent.is_symlink() for parent in list(root.parents)[:4]):
        raise ValueError("Companion root cannot traverse a symlink")
    if not root.exists():
        return
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ValueError("Companion root contains a symlink")
    path = root / "config.json"
    if not path.exists():
        return
    config = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise ValueError("Companion configuration must be an object")
    for key in _CONFIG_PATHS:
        configured = config.get(key)
        if configured is None:
            continue
        if not isinstance(configured, str):
            raise ValueError(f"Companion {key} must stay inside its root")
        posix_path = PurePosixPath(configured)
        windows_path = PureWindowsPath(configured)
        if posix_path.root or windows_path.root or windows_path.drive:
            raise ValueError(f"Companion {key} must stay inside its root")
        if ".." in posix_path.parts or ".." in windows_path.parts:
            raise ValueError(f"Companion {key} must stay inside its root")


class CompanionSession:
    def __init__(
        self, base: Path, person_id: str, character_id: str, continuity_id: str,
    ):
        self.root = companion_root(base, person_id, character_id, continuity_id)

    def run_turn(
        self, callback: Callable[[CompanionMemory], _Result], *, save: bool,
    ) -> _Result:
        """Run one turn with a root-local adapter.

        In save-off mode the callback sees a disposable copy of prior memory.
        The canonical root is never passed to the callback. Callers must keep
        every turn-local writer under the supplied adapter's root.
        """
        _check_local_files(self.root)
        if save:
            self.root.mkdir(parents=True, exist_ok=True)
            return callback(CompanionMemory(self.root))
        with tempfile.TemporaryDirectory(prefix="companion-save-off-") as folder:
            temporary_root = Path(folder) / "relationship"
            if self.root.exists():
                shutil.copytree(self.root, temporary_root)
            else:
                temporary_root.mkdir()
            return callback(CompanionMemory(temporary_root))
