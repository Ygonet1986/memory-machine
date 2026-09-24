"""Atomic publication (priority 1): approval + admission in one operation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from memory_machine import companion_life_admission as admission_mod
from memory_machine.companion_creator import CompanionCreator
from memory_machine.companion_gallery import create_from_template, retire_event
from memory_machine.companion_life_admission import (
    PUBLICATION_JOURNAL, publish_life, recover_publication,
)
from memory_machine.companion_memory import CompanionMemory

ROOT = Path(__file__).resolve().parents[1]


def _life(slug: str = "lia") -> dict:
    path = ROOT / "personas" / slug / "life" / "v1.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _files(root: Path) -> dict[str, bytes]:
    return {str(path.relative_to(root)): path.read_bytes()
            for path in root.rglob("*") if path.is_file()}


def test_publish_is_atomic_and_idempotent(tmp_path):
    result = publish_life(tmp_path, _life())
    assert result["ok"] is True and result["recovered"] is False
    assert result["life_version"] == 1
    creator = CompanionCreator(tmp_path)
    assert creator.load_current()["life_version"] == 1
    assert len(CompanionMemory(tmp_path).tape.read()) == 6
    assert not (tmp_path / "synthetic_life" / PUBLICATION_JOURNAL).exists()
    before = _files(tmp_path)

    again = publish_life(tmp_path, _life())
    assert again["idempotent"] is True
    assert _files(tmp_path) == before


def test_crash_between_halves_is_recoverable(tmp_path, monkeypatch):
    calls = {"n": 0}
    real_admit = admission_mod.admit_life

    def flaky_admit(root, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom between halves")
        return real_admit(root, **kwargs)

    monkeypatch.setattr(admission_mod, "admit_life", flaky_admit)
    with pytest.raises(RuntimeError, match="between halves"):
        publish_life(tmp_path, _life())
    monkeypatch.setattr(admission_mod, "admit_life", real_admit)

    journal = tmp_path / "synthetic_life" / PUBLICATION_JOURNAL
    assert journal.exists()
    assert CompanionCreator(tmp_path).load_current()["life_version"] == 1
    assert CompanionMemory(tmp_path).tape.read() == []

    recovered = recover_publication(tmp_path)
    assert recovered["recovered"] is True
    assert len(CompanionMemory(tmp_path).tape.read()) == 6
    assert not journal.exists()
    assert recover_publication(tmp_path)["recovered"] is False


def test_recover_completes_a_journal_written_before_approval(tmp_path):
    creator = CompanionCreator(tmp_path)
    creator.write_json_atomic(
        tmp_path / "synthetic_life" / PUBLICATION_JOURNAL,
        {"document": _life()})
    assert creator.load_current() is None

    result = recover_publication(tmp_path)
    assert result["recovered"] is True
    assert creator.load_current()["life_version"] == 1
    assert len(CompanionMemory(tmp_path).tape.read()) == 6


def test_retire_and_create_use_the_atomic_path(tmp_path):
    created = create_from_template(tmp_path, "p1", "lia", "lia")
    root = Path(created["root"])
    assert created["published"]["admitted"]
    assert not (root / "synthetic_life" / PUBLICATION_JOURNAL).exists()

    calls = {"n": 0}
    real_admit = admission_mod.admit_life

    def flaky_admit(inner_root, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom during retire")
        return real_admit(inner_root, **kwargs)

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(admission_mod, "admit_life", flaky_admit)
    try:
        with pytest.raises(RuntimeError, match="during retire"):
            retire_event(root, "life-0002")
    finally:
        monkeypatch.undo()
    assert (root / "synthetic_life" / PUBLICATION_JOURNAL).exists()

    recover_publication(root)
    assert not (root / "synthetic_life" / PUBLICATION_JOURNAL).exists()
    reloaded = CompanionMemory(root)
    active = [record for record in reloaded.tape.read()
              if record.status == "active"
              and record.origin.get("kind") == "synthetic_life_event"]
    assert len(active) == 5


def test_backend_recovers_tomas_roots_and_pending_journals(tmp_path, monkeypatch):
    from app import companion_creator_backend as creator_mod
    from app import settings as settings_mod

    monkeypatch.setattr(settings_mod, "APP_DIR", tmp_path)
    settings_mod.save_settings({
        "api_key": "x", "model": "deepseek-v4-flash",
        "base_url": "https://api.deepseek.com",
        "memory_root": str(tmp_path / "data"),
    })
    backend = creator_mod.CreatorBackend(base=tmp_path / "data")
    created = backend.create("p2", "tomas-root", "tomas")
    assert created["ok"] is True
    assert len(created["published"]["admitted"]) == 5

    state = backend.open("p2", "tomas-root")
    assert state["ok"] is True
    assert state["life_version"] == 1 and state["events"] == 5

    retired = backend.retire("p2", "tomas-root", "life-0002")
    assert retired["ok"] is True and retired["life_version"] == 2

    root = backend.root_of("p2", "tomas-root")
    creator = CompanionCreator(root, self_id="tomas")
    pending = json.loads(json.dumps(_life("tomas")))
    pending["life_version"] = 3
    for event in pending["events"]:
        event["life_version"] = 3
    creator.write_json_atomic(
        root / "synthetic_life" / PUBLICATION_JOURNAL,
        {"document": pending})
    reopened = backend.open("p2", "tomas-root")
    assert reopened["life_version"] == 3
    assert not (root / "synthetic_life" / PUBLICATION_JOURNAL).exists()
