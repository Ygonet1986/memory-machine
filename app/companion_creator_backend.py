"""Creator backend for the desktop app (C5b): one façade over the core.

Thin, Qt-free wrapper used by the creator dialog: relationships, templates,
create/copy, timeline, revision diff, draft editing and publish/retire. All
validation, transactions and publication stay in the core modules.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from memory_machine.companion_creator import CompanionCreator
from memory_machine.companion_gallery import (
    copy_relationship,
    create_from_template,
    deletion_impact,
    life_diff,
    life_timeline,
    list_relationships,
    list_templates,
    retire_event,
)
from memory_machine.companion_life_admission import admit_life
from memory_machine.companion_persona import CompanionPersona
from memory_machine.companion_session import CompanionSession

from .settings import load_settings

TEMPLATES = Path(__file__).resolve().parents[1]


class CreatorBackend:
    def __init__(self, *, base: str | Path | None = None,
                 repo_root: str | Path | None = None,
                 client: Any = None) -> None:
        settings = load_settings()
        self._base = Path(base if base is not None
                          else settings["memory_root"]).expanduser()
        self._repo = Path(repo_root) if repo_root is not None else TEMPLATES
        self._client = client

    # ---------------------------------------------------------- listings

    def templates(self) -> list[dict[str, Any]]:
        return list_templates(self._repo)

    def relationships(self) -> list[dict[str, Any]]:
        return list_relationships(self._base)

    def root_of(self, person: str, character: str,
                continuity: str = "main") -> Path:
        return CompanionSession(self._base, person, character,
                                continuity).root

    # ------------------------------------------------------------ create

    def create(self, person: str, character: str, slug: str, *,
               continuity: str = "main") -> dict[str, Any]:
        try:
            result = create_from_template(
                self._base, person, character, slug, continuity=continuity,
                repo_root=self._repo)
        except ValueError as error:
            return {"ok": False, "error": str(error)}
        return result

    def copy(self, person: str, source: str, new_character: str, *,
             continuity: str = "main", self_id: str = "lia") -> dict[str, Any]:
        try:
            result = copy_relationship(
                self._base, person, source, new_character,
                continuity=continuity, self_id=self_id)
        except ValueError as error:
            return {"ok": False, "error": str(error)}
        return result

    # -------------------------------------------------------------- open

    def open(self, person: str, character: str, *,
             continuity: str = "main") -> dict[str, Any]:
        root = self.root_of(person, character, continuity)
        persona = CompanionPersona(root).load()
        if persona is None:
            return {"ok": False, "error": "relationship has no approved persona"}
        creator = CompanionCreator(root)
        current = creator.load_current()
        draft = creator.load_draft()
        return {
            "ok": True,
            "root": str(root),
            "persona": persona,
            "life_version": current["life_version"] if current else 0,
            "events": len(current["events"]) if current else 0,
            "has_draft": draft is not None,
            "draft_version": draft["life_version"] if draft else 0,
        }

    # ------------------------------------------------------------ review

    def timeline(self, person: str, character: str, *,
                 continuity: str = "main") -> dict[str, Any]:
        creator = CompanionCreator(self.root_of(person, character, continuity))
        doc = creator.load_draft() or creator.load_current()
        if doc is None:
            return {"ok": False, "error": "no life document"}
        return {"ok": True, "source": "draft" if creator.load_draft() else "current",
                "entries": life_timeline(doc)}

    def diff(self, person: str, character: str, *,
             continuity: str = "main") -> dict[str, Any]:
        creator = CompanionCreator(self.root_of(person, character, continuity))
        current = creator.load_current()
        draft = creator.load_draft()
        if current is None or draft is None:
            return {"ok": False, "error": "both a current version and a draft "
                                          "are required for a revision diff"}
        return {"ok": True, "diff": life_diff(current, draft)}

    # ------------------------------------------------------------- draft

    def draft(self, person: str, character: str, *,
              continuity: str = "main") -> dict[str, Any]:
        creator = CompanionCreator(self.root_of(person, character, continuity))
        draft = creator.load_draft()
        if draft is None:
            current = creator.load_current()
            if current is None:
                return {"ok": False, "error": "no life document"}
            draft = json.loads(json.dumps(current))
            draft["life_version"] = current["life_version"] + 1
            draft["status"] = "draft"
            draft["approved_at"] = ""
            draft["approved_by"] = ""
            for event in draft["events"]:
                event["life_version"] = draft["life_version"]
        return {"ok": True, "draft": draft}

    def save_draft(self, person: str, character: str, doc: dict[str, Any],
                   *, continuity: str = "main") -> dict[str, Any]:
        creator = CompanionCreator(self.root_of(person, character, continuity))
        try:
            return creator.save_draft(doc)
        except ValueError as error:
            return {"ok": False, "error": str(error)}

    def approve(self, person: str, character: str, doc: dict[str, Any], *,
                continuity: str = "main",
                approved_by: str = "owner") -> dict[str, Any]:
        root = self.root_of(person, character, continuity)
        creator = CompanionCreator(root)
        stamped = json.loads(json.dumps(doc))
        stamped["status"] = "approved"
        stamped["approved_at"] = datetime.now(timezone.utc).isoformat()
        stamped["approved_by"] = approved_by
        try:
            result = creator.approve(stamped)
        except ValueError as error:
            return {"ok": False, "error": str(error)}
        published = admit_life(root)
        result["published"] = published
        return result

    def retire(self, person: str, character: str, event_id: str, *,
               continuity: str = "main") -> dict[str, Any]:
        try:
            return retire_event(self.root_of(person, character, continuity),
                                event_id)
        except ValueError as error:
            return {"ok": False, "error": str(error)}

    def impact(self, person: str, character: str, event_id: str, *,
               continuity: str = "main") -> dict[str, Any]:
        try:
            return deletion_impact(self.root_of(person, character, continuity),
                                   event_id)
        except ValueError as error:
            return {"ok": False, "error": str(error)}
