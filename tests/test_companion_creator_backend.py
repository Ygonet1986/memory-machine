"""C5b: the app's creator façade (create, review, draft, approve, retire)."""

from __future__ import annotations

from pathlib import Path

from memory_machine.companion_memory import CompanionMemory

from app import companion_creator_backend as creator_mod
from app import settings as settings_mod


def _backend(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_mod, "APP_DIR", tmp_path)
    settings_mod.save_settings({
        "api_key": "x", "model": "deepseek-v4-flash",
        "base_url": "https://api.deepseek.com",
        "memory_root": str(tmp_path / "data"),
    })
    return creator_mod.CreatorBackend(base=tmp_path / "data")


def test_create_open_and_timeline(tmp_path, monkeypatch):
    backend = _backend(tmp_path, monkeypatch)
    assert backend.relationships() == []
    slugs = {row["slug"] for row in backend.templates()}
    assert {"lia", "tomas"} <= slugs

    created = backend.create("p1", "ana", "lia")
    assert created["ok"] is True
    assert len(created["published"]["admitted"]) == 6

    state = backend.open("p1", "ana")
    assert state["ok"] is True
    assert state["persona"]["name"] == "Lia"
    assert state["life_version"] == 1 and state["events"] == 6
    assert state["has_draft"] is False

    rows = backend.relationships()
    assert [row["character"] for row in rows] == ["ana"]

    timeline = backend.timeline("p1", "ana")
    assert timeline["ok"] is True and timeline["source"] == "current"
    assert timeline["entries"][0]["event_id"] == "life-0001"
    assert timeline["entries"][-1]["event_id"] == "life-0006"

    tape = CompanionMemory(backend.root_of("p1", "ana")).tape
    stories = [record for record in tape.read() if record.type == "story"]
    assert len(stories) == 6
    assert all(record.origin.get("kind") == "synthetic_life_event"
               for record in stories)


def test_create_rejects_duplicates_and_unknown_templates(tmp_path, monkeypatch):
    backend = _backend(tmp_path, monkeypatch)
    assert backend.create("p1", "ana", "lia")["ok"] is True
    duplicate = backend.create("p1", "ana", "lia")
    assert duplicate["ok"] is False and "already exists" in duplicate["error"]
    unknown = backend.create("p1", "bia", "nao-existe")
    assert unknown["ok"] is False and "unknown template" in unknown["error"]


def test_copy_inherits_no_conversations(tmp_path, monkeypatch):
    backend = _backend(tmp_path, monkeypatch)
    backend.create("p1", "ana", "lia")
    root = backend.root_of("p1", "ana")
    tape = CompanionMemory(root).tape
    from memory_machine.tape import MemoryRecord

    tape.append(MemoryRecord(type="question", summary="segredo",
                             why="segredo", source="companion#t1"))

    copied = backend.copy("p1", "ana", "ana-b")
    assert copied["ok"] is True
    other = CompanionMemory(Path(copied["root"]))
    assert all(record.type not in {"question", "reply"}
               for record in other.tape.read())
    assert len([record for record in other.tape.read()
                if record.origin.get("kind") == "synthetic_life_event"]) == 6


def test_draft_edit_diff_approve_and_retire(tmp_path, monkeypatch):
    backend = _backend(tmp_path, monkeypatch)
    backend.create("p1", "ana", "lia")

    draft = backend.draft("p1", "ana")["draft"]
    assert draft["life_version"] == 2 and draft["status"] == "draft"
    draft["events"][0]["summary"] = "Resumo revisado."
    saved = backend.save_draft("p1", "ana", draft)
    assert saved["ok"] is True

    diff = backend.diff("p1", "ana")
    assert diff["ok"] is True
    assert diff["diff"]["changed"]["life-0001"] == ["summary"]

    approved = backend.approve("p1", "ana", draft)
    assert approved["ok"] is True and approved["life_version"] == 2
    assert len(approved["published"]["admitted"]) == 6
    assert approved["published"]["superseded"]

    impact = backend.impact("p1", "ana", "life-0002")
    assert impact["event_id"] == "life-0002"
    assert impact["target"]["active"] is True

    retired = backend.retire("p1", "ana", "life-0002")
    assert retired["ok"] is True and retired["life_version"] == 3
    again = backend.retire("p1", "ana", "life-0002")
    assert again["ok"] is False and "already retired" in again["error"]

    tape = CompanionMemory(backend.root_of("p1", "ana")).tape
    active = [record for record in tape.read()
              if record.status == "active"
              and record.origin.get("kind") == "synthetic_life_event"]
    assert len(active) == 5
    assert all("life-0002" not in record.source for record in active)


def test_open_without_persona_reports_error(tmp_path, monkeypatch):
    backend = _backend(tmp_path, monkeypatch)
    state = backend.open("p1", "fantasma")
    assert state["ok"] is False and "persona" in state["error"]
