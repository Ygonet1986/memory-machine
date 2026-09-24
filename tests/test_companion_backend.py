"""F4a: headless Companion backend (persona approval, panel ops, turns)."""

from __future__ import annotations

import json
import re

from fakes import FakeClient, text
from memory_machine.companion_memory import CompanionMemory
from memory_machine.tape import MemoryRecord

from app import companion_backend as companion_mod
from app import settings as settings_mod

MESSAGE = "estou compondo uma música para minha irmã"


def _setup(tmp_path, monkeypatch, handler=None):
    monkeypatch.setattr(settings_mod, "APP_DIR", tmp_path)
    settings_mod.save_settings({
        "api_key": "x",
        "model": "deepseek-v4-flash",
        "base_url": "https://api.deepseek.com",
        "memory_root": str(tmp_path / "data"),
    })
    client = FakeClient(handler) if handler is not None else None
    return companion_mod.CompanionBackend(client=client)


def _handler(conversation_reply: str):
    def handler(messages, temperature):
        system = text(messages, "system")
        if "You are a memory agent" in system:
            found = dict.fromkeys(re.findall(r"\[(M\d{4})\]", system))
            return json.dumps({
                "understanding": "test", "digest": "test",
                "annotations": [
                    {"memory_id": memory_id, "note": "relevante",
                     "relevance": 0.9} for memory_id in found
                ],
                "coverage": "complete", "missing": [],
            })
        return conversation_reply

    return handler


def test_approve_persona_then_idempotent(tmp_path, monkeypatch):
    backend = _setup(tmp_path, monkeypatch)
    assert backend.persona() is None

    first = backend.approve_persona()
    assert first["ok"] is True
    assert first["sheet"]["name"] == "Lia"
    assert len(first["records"]) == 4
    assert backend.persona()["version"] == 1

    second = backend.approve_persona()
    assert second["ok"] is True
    assert second["records"] == first["records"]
    assert backend.memories() == []


def test_memories_lists_only_chat_types(tmp_path, monkeypatch):
    backend = _setup(tmp_path, monkeypatch)
    backend.approve_persona()
    memory = CompanionMemory(backend.session.root)
    memory.tape.append(MemoryRecord(
        type="person_report", summary="gosta de compor", source="u1",
        origin={"kind": "turn", "turn_ids": ["u1"]},
    ))
    memory.tape.append(MemoryRecord(
        type="question", summary="oi", why="oi", source="companion#t1",
    ))
    rows = backend.memories()
    assert [row["type"] for row in rows] == ["person_report"]
    assert rows[0]["origin"]["turn_ids"] == ["u1"]


def test_correct_supersedes_same_type(tmp_path, monkeypatch):
    backend = _setup(tmp_path, monkeypatch)
    backend.approve_persona()
    memory = CompanionMemory(backend.session.root)
    old = memory.tape.append(MemoryRecord(
        type="person_report", summary="música para a irmã", author="person",
    ))

    result = backend.correct(old.id, "música para a mãe")

    assert result["ok"] is True
    assert result["replaced"] == old.id
    rows = backend.memories()
    assert [row["summary"] for row in rows] == ["música para a mãe"]
    assert rows[0]["type"] == "person_report"
    statuses = {r.id: r.status for r in memory.tape.read()}
    assert statuses[old.id] == "superseded"
    assert statuses[result["record"]["memory_id"]] == "active"
    assert backend.correct(old.id, "outra")["ok"] is False


def test_delete_cascade_discloses_removed(tmp_path, monkeypatch):
    backend = _setup(tmp_path, monkeypatch)
    backend.approve_persona()
    memory = CompanionMemory(backend.session.root)
    parent = memory.tape.append(MemoryRecord(
        type="person_report", summary="segredo"))
    child = memory.tape.append(MemoryRecord(
        type="episode", summary="segredo discutido", derived_from=[parent.id],
    ))

    result = backend.delete(parent.id)

    assert result["ok"] is True
    assert set(result["removed"]) == {parent.id, child.id}
    assert backend.memories() == []
    assert backend.delete(parent.id)["ok"] is False


def test_turn_saves_then_save_off_keeps_bytes(tmp_path, monkeypatch):
    proposal = {"type": "person_report", "summary": "compõe para a irmã",
                "quote": "compondo uma música para minha irmã",
                "source": "person"}
    reply = ("Que bom. Como está a letra?\n"
             + json.dumps({"used": [], "memories": [proposal]}))
    backend = _setup(tmp_path, monkeypatch, _handler(reply))
    backend.approve_persona()

    saved = backend.turn(MESSAGE, save=True)
    assert saved["ok"] is True
    assert saved["saved"]["records"]
    memory = CompanionMemory(backend.session.root)
    assert any(record.type == "question" for record in memory.tape.read())
    assert [row["summary"] for row in backend.memories()] == ["compõe para a irmã"]

    before = {str(path.relative_to(backend.session.root)): path.read_bytes()
              for path in backend.session.root.rglob("*") if path.is_file()}
    quiet = backend.turn("e agora?", save=False)
    assert quiet["ok"] is True
    assert quiet["saved"] is None
    after = {str(path.relative_to(backend.session.root)): path.read_bytes()
             for path in backend.session.root.rglob("*") if path.is_file()}
    assert after == before


def test_template_path_honours_frozen_bundle(tmp_path, monkeypatch):
    fake = tmp_path / "personas" / "lia" / "v1.json"
    fake.parent.mkdir(parents=True)
    fake.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(companion_mod.sys, "_MEIPASS", str(tmp_path),
                        raising=False)
    assert companion_mod.template_path() == fake
    monkeypatch.delattr(companion_mod.sys, "_MEIPASS", raising=False)
    assert companion_mod.template_path().name == "v1.json"
    assert companion_mod.template_path().parent.name == "lia"


def test_turn_without_persona_is_an_error(tmp_path, monkeypatch):
    backend = _setup(tmp_path, monkeypatch, _handler("nunca"))
    result = backend.turn("oi", save=True)
    assert result["ok"] is False
    assert "persona" in result["error"]
