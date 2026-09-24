"""C4: labeled synthetic-life recall, its own budget and real `used`."""

from __future__ import annotations

import json
from pathlib import Path

from test_companion_engine import _conversation_call, _handler

from fakes import FakeClient
from memory_machine.companion_creator import CompanionCreator
from memory_machine.companion_engine import (
    IMPROV_LAYER, LIFE_LAYER, CompanionEngine,
)
from memory_machine.companion_life_admission import admit_life
from memory_machine.companion_memory import CompanionMemory
from memory_machine.companion_persona import CompanionPersona
from memory_machine.companion_session import CompanionSession
from memory_machine.groups import ensure_group, load_manifest, save_manifest
from memory_machine.tape import MemoryRecord, parse_id

ROOT = Path(__file__).resolve().parents[1]
PERSONA = ROOT / "personas" / "lia" / "v1.json"


def _life(slug: str) -> dict:
    path = ROOT / "personas" / slug / "life" / "v1.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _setup(base, person: str, character: str, slug: str):
    session = CompanionSession(base, person, character, "main")
    ids: dict[str, str] = {}

    def setup(store):
        CompanionPersona(store.root).create(
            json.loads(PERSONA.read_text(encoding="utf-8")))
        CompanionCreator(store.root, self_id=slug).approve(_life(slug))
        admit_life(store.root, self_id=slug)
        records = [
            MemoryRecord(type="person_report", summary="gosta de compor",
                         source="u1",
                         origin={"kind": "turn", "turn_ids": ["u1"]}),
            MemoryRecord(type="episode", summary="compuseram uma melodia",
                         source="u2",
                         origin={"kind": "turn", "turn_ids": ["u2"]}),
            MemoryRecord(type="story", summary="biblioteca imaginária",
                         origin={"kind": "story_event", "event_id": "e1"}),
            MemoryRecord(type="hypothesis", summary="talvez prefira jazz",
                         source="u3",
                         origin={"kind": "turn", "turn_ids": ["u3"],
                                 "confidence": 0.5,
                                 "review_at": "2026-10-24T00:00:00+00:00"}),
        ]
        manifest = load_manifest(store.root / "manifest.json")
        for record in records:
            appended = store.tape.append(record)
            ensure_group(manifest, parse_id(appended.id))
            ids[record.type] = appended.id
        save_manifest(manifest, store.root / "manifest.json")
        life_ids = [record.id for record in store.tape.read()
                    if (record.origin or {}).get("kind") == "synthetic_life_event"]
        ids["life"] = life_ids[0]
        ids["life_all"] = life_ids

    session.run_turn(setup, save=True)
    return session, ids


def test_life_and_improvised_story_have_separate_labels(tmp_path):
    session, ids = _setup(tmp_path, "p1", "lia", "lia")
    client = FakeClient(_handler('ok\n{"used": [], "memories": []}'))
    engine = CompanionEngine(session, client)
    result = engine.reply("me conta do seu passado")

    messages = _conversation_call(client)
    user = "\n".join(part["content"] for part in messages
                     if part["role"] == "user")
    assert f"### {LIFE_LAYER}" in user
    assert f"### {IMPROV_LAYER}" in user
    assert "vida aprovada v1 · life-" in user
    assert "se mudou com a família" in user
    assert "biblioteca imaginária" in user
    assert ids["life"] in result["provided"]
    persona_ids = {record.id for record in CompanionPersona(session.root).facts()}
    assert not persona_ids.intersection(result["provided"])


def test_policy_states_approved_character_past(tmp_path):
    session, _ids = _setup(tmp_path, "p1", "lia", "lia")
    client = FakeClient(_handler('ok\n{"used": [], "memories": []}'))
    CompanionEngine(session, client).reply("oi")
    system = "\n".join(part["content"]
                       for part in _conversation_call(client)
                       if part["role"] == "system")
    assert "Passado ficcional" in system


def test_used_life_event_is_real(tmp_path):
    session, ids = _setup(tmp_path, "p1", "lia", "lia")
    client = FakeClient(_handler(
        f'Lembro sim.\n{{"used": ["{ids["life"]}"], "memories": []}}'))
    result = CompanionEngine(session, client).reply("qual foi o festival?")
    assert [item["memory_id"] for item in result["used"]] == [ids["life"]]
    assert result["used"][0]["origin"]["kind"] == "synthetic_life_event"


def test_life_budget_is_separate(tmp_path):
    session, ids = _setup(tmp_path, "p1", "lia", "lia")
    client = FakeClient(_handler('ok\n{"used": [], "memories": []}'))
    tight = CompanionEngine(session, client, life_budget=1).reply("oi")
    life_provided = [memory_id for memory_id in tight["provided"]
                     if memory_id in ids["life_all"]]
    assert len(life_provided) == 1
    assert tight["dropped"]

    client = FakeClient(_handler('ok\n{"used": [], "memories": []}'))
    roomy = CompanionEngine(session, client, life_budget=10000).reply("oi")
    life_provided = [memory_id for memory_id in roomy["provided"]
                     if memory_id in ids["life_all"]]
    assert len(life_provided) == len(ids["life_all"]) == 6
    assert not roomy["dropped"]


def test_cross_root_id_collisions_stay_separate(tmp_path):
    base = tmp_path
    session_a, ids_a = _setup(base, "p1", "lia", "lia")
    session_b, ids_b = _setup(base, "p2", "tomas", "tomas")

    tape_a = {record.id for record in CompanionMemory(session_a.root).tape.read()}
    tape_b = {record.id for record in CompanionMemory(session_b.root).tape.read()}
    assert tape_a.intersection(tape_b)  # deliberate ID collision

    client = FakeClient(_handler(
        f'ok\n{{"used": ["{ids_a["life"]}"], "memories": []}}'))
    result = CompanionEngine(session_a, client).reply("me fale da sua vida")
    assert set(result["provided"]) <= tape_a
    assert not set(result["provided"]).intersection(
        tape_b - tape_a)
    assert result["used"][0]["memory_id"] == ids_a["life"]
    assert "vila à beira-mar" in result["used"][0]["summary"]

    user = "\n".join(part["content"]
                     for part in _conversation_call(client)
                     if part["role"] == "user")
    assert "montanha" not in user.casefold()
    assert "relógio" not in user.casefold()
