"""C5a: gallery listings, timeline, diff, retire, impact and relationship copy."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from memory_machine.companion_creator import CompanionCreator
from memory_machine.companion_gallery import (
    copy_relationship, deletion_impact, life_diff, life_timeline,
    list_relationships, list_templates, retire_event,
)
from memory_machine.companion_life_admission import admit_life
from memory_machine.companion_memory import CompanionMemory
from memory_machine.companion_persona import CompanionPersona
from memory_machine.companion_session import CompanionSession
from memory_machine.tape import MemoryRecord

ROOT = Path(__file__).resolve().parents[1]
PERSONA = ROOT / "personas" / "lia" / "v1.json"


def _life(slug: str = "lia") -> dict:
    path = ROOT / "personas" / slug / "life" / "v1.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _root(base, person="p1", character="lia", self_id="lia"):
    session = CompanionSession(base, person, character, "main")

    def setup(store):
        CompanionPersona(store.root).create(
            json.loads(PERSONA.read_text(encoding="utf-8")))
        CompanionCreator(store.root, self_id=self_id).approve(_life(self_id))
        admit_life(store.root, self_id=self_id)

    session.run_turn(setup, save=True)
    return session.root


def test_list_templates_and_relationships(tmp_path):
    templates = {row["slug"]: row for row in list_templates(ROOT)}
    assert templates["lia"]["persona_versions"] == [1]
    assert templates["lia"]["life_versions"] == [1]
    assert templates["tomas"]["life_versions"] == [1]

    assert list_relationships(tmp_path) == []
    _root(tmp_path)
    rows = list_relationships(tmp_path)
    assert len(rows) == 1
    assert rows[0] == {"person": "p1", "character": "lia", "continuity": "main",
                       "name": "Lia", "persona_version": 1, "life_version": 1}


def test_timeline_is_time_ordered(tmp_path):
    timeline = life_timeline(_life())
    assert [entry["event_id"] for entry in timeline] == [
        "life-0001", "life-0002", "life-0003", "life-0004", "life-0005",
        "life-0006"]
    assert timeline[0]["event_time"] == "2009-11"
    assert timeline[-1]["event_time"] == "2018-06-10"
    assert timeline[0]["place"] == "Vila do Farol"
    assert timeline[0]["generator"] == "manual"


def test_diff_reports_added_changed_removed():
    old = _life()
    new = copy.deepcopy(old)
    new["life_version"] = 2
    for event in new["events"]:
        event["life_version"] = 2
    new["events"][0]["summary"] = "Resumo novo."
    new["events"][4]["status"] = "retired"
    new["events"][4]["approved_at"] = ""
    new["events"][4]["approved_by"] = ""
    new["events"].append({
        "event_id": "life-0007", "life_version": 2, "title": "Extra",
        "summary": "Um evento novo.", "event_time": "2018",
        "time_precision": "year", "place": "Vila do Farol",
        "participants": [{"id": "lia", "role": ""}],
        "causes": [], "effects": [], "status": "approved",
        "provenance": {"kind": "synthetic_life", "generator": "manual",
                       "sheet_version": 1, "prompt": "", "model": "", "seed": ""},
        "approved_at": "2026-09-24T00:00:00+00:00", "approved_by": "owner",
    })

    diff = life_diff(old, new)
    assert diff["old_version"] == 1 and diff["new_version"] == 2
    assert diff["added"] == ["life-0007"]
    assert diff["removed"] == []
    assert diff["changed"]["life-0001"] == ["summary"]
    assert "status" in diff["changed"]["life-0005"]


def test_retire_event_supersedes_and_leaves_recall(tmp_path):
    root = _root(tmp_path)
    memory = CompanionMemory(root)
    before = [record.id for record in memory.tape.read()
              if record.source.endswith("#life-0002")]
    assert len(before) == 1

    result = retire_event(root, "life-0002")
    assert result["ok"] is True and result["life_version"] == 2
    assert result["published"]["admitted"]

    reloaded = CompanionMemory(root)
    statuses = {record.id: record.status for record in reloaded.tape.read()}
    assert statuses[before[0]] == "superseded"
    assert all("life-0002" not in record.source
               for record in reloaded.search("Primeiro violão"))
    creator = CompanionCreator(root)
    assert creator.load_current()["life_version"] == 2
    retired = next(event for event in creator.load_current()["events"]
                   if event["event_id"] == "life-0002")
    assert retired["status"] == "retired"
    with pytest.raises(ValueError, match="already retired"):
        retire_event(root, "life-0002")
    with pytest.raises(ValueError, match="unknown event"):
        retire_event(root, "life-0099")


def test_deletion_impact_lists_derivations_and_mentions(tmp_path):
    root = _root(tmp_path)
    memory = CompanionMemory(root)
    record = next(item for item in memory.tape.read()
                  if item.source.endswith("#life-0001"))
    memory.tape.append(MemoryRecord(
        type="person_report",
        summary="Ela contou que se mudou com a família para uma vila à beira do mar.",
        source="u9", origin={"kind": "turn", "turn_ids": ["u9"]}))

    impact = deletion_impact(root, "life-0001")
    assert impact["target"]["record_id"] == record.id
    assert impact["target"]["active"] is True
    assert impact["derived"] == []
    assert any(memory_id != record.id for memory_id in impact["mentions"])


def test_copy_relationship_inherits_no_conversations(tmp_path):
    root = _root(tmp_path)
    memory = CompanionMemory(root)
    memory.tape.append(MemoryRecord(
        type="question", summary="segredo antigo", why="segredo antigo",
        source="companion#t1"))
    source_before = {path: path.read_bytes()
                     for path in root.rglob("*") if path.is_file()}

    result = copy_relationship(tmp_path, "p1", "lia", "lia-b")
    assert result["ok"] is True
    target = Path(result["root"])
    assert target.exists()
    assert CompanionPersona(target).load()["name"] == "Lia"
    assert CompanionCreator(target).load_current()["life_version"] == 1

    copied = CompanionMemory(target)
    assert all(record.type not in {"question", "reply"}
               for record in copied.tape.read())
    assert len([record for record in copied.tape.read()
                if (record.origin or {}).get("kind") == "synthetic_life_event"]) == 6
    assert not any("segredo antigo" in (record.summary or "")
                   for record in copied.tape.read())

    source_after = {path: path.read_bytes()
                    for path in root.rglob("*") if path.is_file()}
    assert source_after == source_before

    with pytest.raises(ValueError, match="already exists"):
        copy_relationship(tmp_path, "p1", "lia", "lia-b")
    with pytest.raises(ValueError, match="no approved persona"):
        copy_relationship(tmp_path, "p1", "fantasma", "outra")
