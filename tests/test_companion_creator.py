"""C2: creator backend — draft, preview, approval transaction, isolation."""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path

import pytest

from memory_machine.companion_creator import STAGING_NAME, CompanionCreator

ROOT = Path(__file__).resolve().parents[1]


def _template(slug: str = "lia") -> dict:
    path = ROOT / "personas" / slug / "life" / "v1.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _as_draft(doc: dict, events: int = 1) -> dict:
    draft = copy.deepcopy(doc)
    draft["status"] = "draft"
    draft["approved_at"] = ""
    draft["approved_by"] = ""
    draft["events"] = draft["events"][:events]
    kept = {event["event_id"] for event in draft["events"]}
    for event in draft["events"]:
        event["status"] = "draft"
        event["approved_at"] = ""
        event["approved_by"] = ""
        event["causes"] = [i for i in event["causes"] if i in kept]
        event["effects"] = [i for i in event["effects"] if i in kept]
    return draft


def _as_version(doc: dict, version: int) -> dict:
    updated = copy.deepcopy(doc)
    updated["life_version"] = version
    for event in updated["events"]:
        event["life_version"] = version
    return updated


def _files(root: Path) -> dict[str, bytes]:
    return {str(path.relative_to(root)): path.read_bytes()
            for path in root.rglob("*") if path.is_file()}


def test_draft_roundtrip_and_clear(tmp_path):
    creator = CompanionCreator(tmp_path)
    draft = _as_draft(_template())
    result = creator.save_draft(draft)
    assert result["ok"] is True and result["events"] == 1
    loaded = creator.load_draft()
    assert loaded is not None and loaded["status"] == "draft"
    assert loaded["events"][0]["summary"] == draft["events"][0]["summary"]
    assert creator.clear_draft() is True
    assert creator.load_draft() is None
    assert creator.clear_draft() is False


def test_save_draft_rejects_invalid_docs(tmp_path):
    creator = CompanionCreator(tmp_path)
    approved = _template()
    with pytest.raises(ValueError, match="status 'draft'"):
        creator.save_draft(approved)
    secret = _as_draft(_template())
    secret["events"][0]["summary"] = "sk-abcdefghijklmnopqrstuvwx"
    with pytest.raises(Exception, match="secret"):
        creator.save_draft(secret)
    other = _as_draft(_template())
    other["world"]["continuity_id"] = "outra"
    with pytest.raises(ValueError, match="continuity_id"):
        creator.save_draft(other)
    unknown = _as_draft(_template())
    unknown["extra"] = 1
    with pytest.raises(ValueError, match="fields"):
        creator.save_draft(unknown)


def test_approve_publishes_snapshot_and_clears_draft(tmp_path):
    creator = CompanionCreator(tmp_path)
    creator.save_draft(_as_draft(_template()))
    result = creator.approve(_template())
    assert result["ok"] is True and result["idempotent"] is False
    assert result["life_version"] == 1 and result["events"] == 6
    assert len(result["plan"]) == 6
    assert all(item["would_publish"] for item in result["plan"])
    assert (tmp_path / "synthetic_life" / "current.json").exists()
    assert (tmp_path / "synthetic_life" / "history" / "v1.json").exists()
    assert creator.load_draft() is None
    assert creator.history_versions() == [1]
    current = creator.load_current()
    assert current is not None and current["status"] == "approved"
    loaded = creator.load_version(1)
    assert loaded == current
    assert creator.load_version(9) is None


def test_approve_is_idempotent_and_conflict_safe(tmp_path):
    creator = CompanionCreator(tmp_path)
    creator.approve(_template())
    before = _files(tmp_path)
    again = creator.approve(_template())
    assert again["idempotent"] is True
    assert _files(tmp_path) == before

    changed = _template()
    changed["events"][0]["summary"] = "Outro resumo."
    with pytest.raises(ValueError, match="different content"):
        creator.approve(changed)


def test_approve_requires_increasing_version(tmp_path):
    creator = CompanionCreator(tmp_path)
    creator.approve(_as_version(_template(), 2))
    with pytest.raises(ValueError, match="must increase"):
        creator.approve(_template())


def test_approve_without_draft_or_with_draft_only(tmp_path):
    creator = CompanionCreator(tmp_path)
    with pytest.raises(ValueError, match="no draft"):
        creator.approve()
    creator.save_draft(_as_draft(_template()))
    with pytest.raises(ValueError, match="only an approved"):
        creator.approve()


def test_mid_failure_recovers_to_a_consistent_state(tmp_path, monkeypatch):
    from memory_machine import companion_creator as module

    creator = CompanionCreator(tmp_path)
    real_replace = os.replace
    state = {"fired": False}

    def flaky_replace(src, dst):
        if (not state["fired"]
                and Path(dst).name == "current.json"
                and Path(dst).parent == creator.life_dir
                and Path(src).parent.name == STAGING_NAME):
            state["fired"] = True
            raise OSError("boom")
        return real_replace(src, dst)

    monkeypatch.setattr(module.os, "replace", flaky_replace)
    with pytest.raises(OSError, match="boom"):
        creator.approve(_template())
    monkeypatch.setattr(module.os, "replace", real_replace)

    assert creator.journal_path.exists() or creator.staging_path.exists()
    recovered = creator.recover()
    assert recovered["recovered"] is True
    current = creator.load_current()
    assert current is not None and current["life_version"] == 1
    assert not creator.journal_path.exists()
    assert not creator.staging_path.exists()


def test_recover_handles_journal_states(tmp_path):
    creator = CompanionCreator(tmp_path)
    creator.approve(_template())
    staged = creator.staging_path
    staged.mkdir(parents=True)
    creator.write_json_atomic(staged / "current.json",
                        _as_version(_template(), 2))
    creator.write_json_atomic(staged / "history_v2.json",
                        _as_version(_template(), 2))
    creator.write_json_atomic(creator.journal_path, {"life_version": 2})

    assert creator.recover()["recovered"] is True
    assert creator.load_current()["life_version"] == 2
    assert creator.history_versions() == [1, 2]

    creator.write_json_atomic(creator.journal_path, {"life_version": 2})
    assert creator.recover()["recovered"] is True
    assert not creator.journal_path.exists()

    creator.write_json_atomic(creator.journal_path, {"life_version": 9})
    with pytest.raises(RuntimeError, match="unrecoverable"):
        creator.recover()


def test_reads_do_not_write_or_migrate(tmp_path):
    creator = CompanionCreator(tmp_path)
    before = _files(tmp_path)
    assert creator.load_current() is None
    assert creator.load_draft() is None
    assert creator.history_versions() == []
    assert creator.load_version(1) is None
    plan = creator.preview(_template())
    assert plan["events"] == 6
    assert _files(tmp_path) == before


def test_preview_labels_drafts_as_not_publishable(tmp_path):
    creator = CompanionCreator(tmp_path)
    plan = creator.preview(_as_draft(_template()))
    assert plan["events"] == 1
    assert plan["records"][0]["would_publish"] is False
    assert plan["records"][0]["origin"]["kind"] == "synthetic_life_event"
    assert plan["records"][0]["source"].startswith("life#1#life-")


def test_roots_are_isolated(tmp_path):
    lia = CompanionCreator(tmp_path / "a", self_id="lia")
    tomas = CompanionCreator(tmp_path / "b", self_id="tomas")
    lia.approve(_template("lia"))
    tomas.approve(_template("tomas"))
    assert len(lia.load_current()["events"]) == 6
    assert len(tomas.load_current()["events"]) == 5
    assert not (tmp_path / "a" / "synthetic_life" / "history" / "v1.json").read_text(
        encoding="utf-8") == (tmp_path / "b" / "synthetic_life" / "history"
                              / "v1.json").read_text(encoding="utf-8")
    with pytest.raises(ValueError, match="unknown id"):
        lia.approve(_template("tomas"))
