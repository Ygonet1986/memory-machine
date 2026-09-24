"""AI life generation: one call per request, drafts only, explicit approval."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fakes import FakeClient
from memory_machine.companion_creator import CompanionCreator
from memory_machine.companion_generation import (
    GENERATION_PROMPT_TAG, generate_draft,
)
from memory_machine.companion_memory import CompanionMemory
from memory_machine.companion_persona import CompanionPersona

from app import companion_creator_backend as creator_mod
from app import settings as settings_mod

ROOT = Path(__file__).resolve().parents[1]
PERSONA = ROOT / "personas" / "lia" / "v1.json"

EVENTS = [
    {"title": "Mudança", "summary": "Foi morar numa vila de pescadores.",
     "event_time": "2009", "time_precision": "year", "place": "Vila"},
    {"title": "Violão", "summary": "Ganhou um violão antigo do vizinho.",
     "event_time": "2010-04", "time_precision": "month", "place": "Vila"},
    {"title": "Caderno", "summary": "Começou um caderno de letras.",
     "event_time": "2012", "time_precision": "year", "place": "Vila"},
    {"title": "Biblioteca", "summary": "Passou tardes na biblioteca do porto.",
     "event_time": "2014-07", "time_precision": "month", "place": "Porto"},
    {"title": "Canção", "summary": "Terminou a primeira canção.",
     "event_time": "2016-02", "time_precision": "month", "place": "Vila"},
]


def _sheet() -> dict:
    return json.loads(PERSONA.read_text(encoding="utf-8"))


def _reply(events):
    return json.dumps({"events": events}, ensure_ascii=False)


def test_generate_draft_validates_and_records_provenance(tmp_path):
    creator = CompanionCreator(tmp_path)
    creator.approve(json.loads(
        (ROOT / "personas" / "lia" / "life" / "v1.json").read_text()))
    current = creator.load_current()
    client = FakeClient(lambda messages, temperature: _reply(EVENTS))

    draft = generate_draft(client, _sheet(), current, self_id="lia",
                           model="deepseek-v4-flash", seed="s1")

    assert len(client.calls) == 1
    assert draft["status"] == "draft"
    assert draft["life_version"] == current["life_version"] + 1
    ids = [event["event_id"] for event in draft["events"]]
    assert ids[0] == "life-0007"
    assert ids == [f"life-{index:04d}" for index in range(7, 12)]
    provenance = draft["events"][0]["provenance"]
    assert provenance["generator"] == "generated"
    assert provenance["prompt"] == GENERATION_PROMPT_TAG
    assert provenance["model"] == "deepseek-v4-flash"
    assert provenance["seed"] == "s1"
    assert draft["events"][0]["participants"] == [{"id": "lia", "role": ""}]
    assert draft["events"][0]["approved_at"] == ""


def test_generate_draft_rejects_bad_output(tmp_path):
    client = FakeClient(lambda messages, temperature: "sem json aqui")
    with pytest.raises(ValueError, match="JSON"):
        generate_draft(client, _sheet(), None, self_id="lia")
    client = FakeClient(lambda messages, temperature: _reply(EVENTS[:3]))
    with pytest.raises(ValueError, match="fewer than 5"):
        generate_draft(client, _sheet(), None, self_id="lia")
    broken = [dict(EVENTS[0]) for _ in range(5)]
    broken[0]["summary"] = ""
    client = FakeClient(lambda messages, temperature: _reply(broken))
    with pytest.raises(ValueError, match="title and a summary"):
        generate_draft(client, _sheet(), None, self_id="lia")


def _backend(tmp_path, monkeypatch, handler):
    monkeypatch.setattr(settings_mod, "APP_DIR", tmp_path)
    settings_mod.save_settings({
        "api_key": "x", "model": "deepseek-v4-flash",
        "base_url": "https://api.deepseek.com",
        "memory_root": str(tmp_path / "data"),
    })
    return creator_mod.CreatorBackend(base=tmp_path / "data",
                                      client=FakeClient(handler))


def test_backend_generation_budget_draft_and_approval(tmp_path, monkeypatch):
    backend = _backend(tmp_path, monkeypatch,
                       lambda messages, temperature: _reply(EVENTS))
    created = backend.create("p1", "ana", "lia")
    assert created["ok"] is True
    root = backend.root_of("p1", "ana")
    before_tape = (root / "tape.jsonl").read_bytes()
    before_current = (root / "synthetic_life" / "current.json").read_bytes()

    first = backend.generate_life("p1", "ana", seed="s1")
    assert first["ok"] is True and first["events"] == 5
    assert first["generations_used"] == 1
    assert (root / "synthetic_life" / "draft.json").exists()
    assert (root / "tape.jsonl").read_bytes() == before_tape
    assert (root / "synthetic_life" / "current.json").read_bytes() == \
        before_current

    second = backend.generate_life("p1", "ana")
    assert second["ok"] is True and second["generations_used"] == 2
    third = backend.generate_life("p1", "ana")
    assert third["ok"] is False and "budget" in third["error"]

    draft = backend.draft("p1", "ana")["draft"]
    approved = backend.approve("p1", "ana", draft)
    assert approved["ok"] is True
    assert len(approved["published"]["admitted"]) == 5
    assert len(approved["published"]["superseded"]) == 6

    tape = CompanionMemory(root).tape
    active = [record for record in tape.read()
              if record.status == "active"]
    generated = [record for record in active
                 if (record.origin or {}).get("life_version") == 2]
    assert len(generated) == 5
    assert any("violão antigo" in record.summary for record in generated)

    again = backend.generate_life("p1", "ana")
    assert again["ok"] is True and again["generations_used"] == 1


def test_backend_generation_requires_persona(tmp_path, monkeypatch):
    backend = _backend(tmp_path, monkeypatch,
                       lambda messages, temperature: _reply(EVENTS))
    result = backend.generate_life("p1", "fantasma")
    assert result["ok"] is False and "persona" in result["error"]


def test_generated_draft_can_be_saved_and_reloaded(tmp_path, monkeypatch):
    backend = _backend(tmp_path, monkeypatch,
                       lambda messages, temperature: _reply(EVENTS))
    backend.create("p1", "ana", "lia")
    assert backend.generate_life("p1", "ana")["ok"] is True

    draft = backend.draft("p1", "ana")["draft"]
    draft["events"][0]["title"] = "Mudança para a vila"
    assert backend.save_draft("p1", "ana", draft)["ok"] is True
    reloaded = backend.draft("p1", "ana")["draft"]
    assert reloaded["events"][0]["title"] == "Mudança para a vila"
    assert reloaded["events"][0]["provenance"]["generator"] == "generated"

    persona = CompanionPersona(backend.root_of("p1", "ana")).load()
    assert persona["name"] == "Lia"
