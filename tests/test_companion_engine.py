"""F3a: headless engine core (recall layers, trailer protocol, save-off)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from fakes import FakeClient, text
from memory_machine.companion_engine import CompanionEngine
from memory_machine.companion_persona import CompanionPersona
from memory_machine.companion_session import CompanionSession
from memory_machine.groups import ensure_group, load_manifest, save_manifest
from memory_machine.tape import MemoryRecord, parse_id

PERSONA = Path(__file__).resolve().parents[1] / "personas" / "lia" / "v1.json"


def _setup(tmp_path):
    session = CompanionSession(tmp_path, "p1", "lia", "main")
    ids: dict[str, str] = {}

    def setup(store):
        CompanionPersona(store.root).create(
            json.loads(PERSONA.read_text(encoding="utf-8"))
        )
        records = [
            MemoryRecord(type="person_report", summary="gosta de compor",
                         source="u1",
                         origin={"kind": "turn", "turn_ids": ["u1"]}),
            MemoryRecord(type="episode", summary="compuseram uma melodia juntos",
                         source="u2",
                         origin={"kind": "turn", "turn_ids": ["u2"]}),
            MemoryRecord(type="story", summary="biblioteca imaginária visitada",
                         origin={"kind": "story_event", "event_id": "e1"}),
            MemoryRecord(type="hypothesis",
                         summary="talvez prefira perguntas curtas", source="u3",
                         origin={"kind": "turn", "turn_ids": ["u3"],
                                 "confidence": 0.6,
                                 "review_at": "2026-10-24T00:00:00+00:00"}),
        ]
        manifest = load_manifest(store.root / "manifest.json")
        for record in records:
            appended = store.tape.append(record)
            ensure_group(manifest, parse_id(appended.id))
            ids[record.type] = appended.id
        save_manifest(manifest, store.root / "manifest.json")

    session.run_turn(setup, save=True)
    return session, ids


def _handler(conversation_reply: str):
    def handler(messages, temperature):
        system = text(messages, "system")
        if "You are a memory agent" in system:
            found = dict.fromkeys(re.findall(r"\[(M\d{4})\]", system))
            return json.dumps({
                "understanding": "test group", "digest": "test",
                "annotations": [
                    {"memory_id": memory_id, "note": "relevante agora",
                     "relevance": 0.9} for memory_id in found
                ],
                "coverage": "complete", "missing": [],
            })
        return conversation_reply

    return handler


def _conversation_call(client):
    for messages in client.calls:
        system = text(messages, "system")
        if "Personagem: Lia" in system:
            return messages
    raise AssertionError("no conversation call")


def test_engine_layers_trailer_and_used(tmp_path):
    session, ids = _setup(tmp_path)
    report = ids["person_report"]
    reply = ("Você me contou que gosta de compor. Como está isso agora?\n"
             f'{{"used": ["{report}"], "memories": []}}')
    client = FakeClient(_handler(reply))
    engine = CompanionEngine(session, client)

    result = engine.reply("como está a composição?")

    assert result["violations"] == []
    assert result["reply"] == "Você me contou que gosta de compor. Como está isso agora?"
    assert [item["memory_id"] for item in result["used"]] == [report]
    assert report in result["provided"]
    assert ids["story"] in result["provided"]
    assert result["calls"] == len(client.calls) == 2

    messages = _conversation_call(client)
    user = text(messages, "user")
    assert "Relatos da pessoa" in user
    assert "Episódios de conversas reais" in user
    assert "Histórias imaginadas (ficção; nunca fatos da vida real)" in user
    assert "Hipóteses tentativas" in user
    assert "Personagem: Lia" in text(messages, "system")
    assert "Regras de memória" in text(messages, "system")


def test_persona_cards_are_not_provided(tmp_path):
    session, ids = _setup(tmp_path)
    client = FakeClient(_handler('ok\n{"used": [], "memories": []}'))
    engine = CompanionEngine(session, client)
    result = engine.reply("oi")
    persona = CompanionPersona(session.root)
    persona_ids = {record.id for record in persona.facts()}
    assert persona_ids
    assert not persona_ids.intersection(result["provided"])


def test_unknown_used_is_a_violation(tmp_path):
    session, _ids = _setup(tmp_path)
    client = FakeClient(_handler('ok\n{"used": ["M9999"], "memories": []}'))
    result = CompanionEngine(session, client).reply("oi")
    assert result["used"] == []
    assert result["violations"] == [{"kind": "unknown_used", "ids": ["M9999"]}]


def test_missing_trailer_is_a_violation(tmp_path):
    session, _ids = _setup(tmp_path)
    client = FakeClient(_handler("resposta sem trailer"))
    result = CompanionEngine(session, client).reply("oi")
    assert result["violations"] == [{"kind": "missing_trailer"}]
    assert result["reply"] == "resposta sem trailer"


def test_proposed_memories_pass_through(tmp_path):
    session, _ids = _setup(tmp_path)
    proposal = {"type": "episode", "summary": "conversamos sobre música",
                "quote": "como está a composição?", "source": "person"}
    client = FakeClient(_handler(
        'claro\n{"used": [], "memories": [' + json.dumps(proposal) + ']}'
    ))
    result = CompanionEngine(session, client).reply("como está a composição?")
    assert result["proposed"] == [proposal]


def test_save_off_writes_zero_bytes_to_real_root(tmp_path):
    session, _ids = _setup(tmp_path)
    before = {str(path.relative_to(session.root)): path.read_bytes()
              for path in session.root.rglob("*") if path.is_file()}
    proposal = {"type": "person_report", "summary": "tema novo",
                "quote": "oi", "source": "person"}
    client = FakeClient(_handler(
        'ok\n{"used": [], "memories": [' + json.dumps(proposal) + ']}'
    ))
    result = CompanionEngine(session, client).reply("oi")
    assert result["saved"] is None
    after = {str(path.relative_to(session.root)): path.read_bytes()
             for path in session.root.rglob("*") if path.is_file()}
    assert after == before


def test_budget_drops_extra_cards(tmp_path):
    session, ids = _setup(tmp_path)
    client = FakeClient(_handler('ok\n{"used": [], "memories": []}'))
    result = CompanionEngine(session, client, budget=1).reply("oi")
    assert result["provided"]
    assert result["dropped"]
    assert ids["person_report"] in result["provided"]


def test_missing_persona_fails(tmp_path):
    session = CompanionSession(tmp_path, "p2", "lia", "main")
    client = FakeClient(_handler("nunca chamado"))
    with pytest.raises(ValueError, match="no approved persona"):
        CompanionEngine(session, client).reply("oi")
    assert client.calls == []


def test_deterministic_output(tmp_path):
    session, ids = _setup(tmp_path)
    report = ids["person_report"]
    reply = f'ok\n{{"used": ["{report}"], "memories": []}}'
    first = CompanionEngine(session, FakeClient(_handler(reply))).reply("oi")
    second = CompanionEngine(session, FakeClient(_handler(reply))).reply("oi")
    assert first == second
