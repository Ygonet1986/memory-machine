"""C3: synthetic-life admission, batch versioning, non-resurrection."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from memory_machine.companion_creator import CompanionCreator
from memory_machine.companion_life_admission import admit_life
from memory_machine.companion_memory import CompanionMemory
from memory_machine.groups import load_manifest
from memory_machine.tape import MemoryRecord

ROOT = Path(__file__).resolve().parents[1]


def _template(slug: str = "lia") -> dict:
    path = ROOT / "personas" / slug / "life" / "v1.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _v2() -> dict:
    doc = copy.deepcopy(_template())
    doc["life_version"] = 2
    for event in doc["events"]:
        event["life_version"] = 2
    doc["events"][2]["summary"] = "O caderno de letras ganhou uma capa nova."
    retired = doc["events"][5]
    retired["status"] = "retired"
    retired["approved_at"] = ""
    retired["approved_by"] = ""
    return doc


def _files(root: Path) -> dict[str, bytes]:
    return {str(path.relative_to(root)): path.read_bytes()
            for path in root.rglob("*") if path.is_file()}


def _setup(tmp_path) -> CompanionCreator:
    creator = CompanionCreator(tmp_path)
    creator.approve(_template())
    return creator


def test_admits_one_story_per_event_without_forged_turns(tmp_path):
    _setup(tmp_path)
    result = admit_life(tmp_path)
    assert result["ok"] is True and result["idempotent"] is False
    assert result["life_version"] == 1
    assert len(result["admitted"]) == 6
    assert result["superseded"] == []

    tape = CompanionMemory(tmp_path).tape
    records = tape.read()
    assert all(record.type == "story" for record in records)
    assert not any(record.type in {"question", "reply"} for record in records)
    for record in records:
        assert record.source.startswith("life#1#life-")
        assert record.origin["kind"] == "synthetic_life_event"
        assert record.origin["life_version"] == 1
        assert record.origin["continuity_id"] == "main"
        assert record.author == "joint"
        assert record.derived_from == []
        assert record.event_time
    manifest = load_manifest(tmp_path / "manifest.json")
    covered = {memory_id for group in manifest.groups
               for memory_id in range(group.start, group.end + 1)}
    assert all(int(memory_id[1:]) in covered for memory_id in result["admitted"])


def test_admission_is_idempotent(tmp_path):
    _setup(tmp_path)
    admit_life(tmp_path)
    before = (tmp_path / "tape.jsonl").read_bytes()
    again = admit_life(tmp_path)
    assert again["idempotent"] is True
    assert again["admitted"] == []
    assert len(again["skipped"]) == 6
    assert (tmp_path / "tape.jsonl").read_bytes() == before


def test_new_version_supersedes_old_in_one_batch(tmp_path):
    creator = _setup(tmp_path)
    first = admit_life(tmp_path)
    old_ids = first["admitted"]

    creator.approve(_v2())
    second = admit_life(tmp_path)
    assert second["life_version"] == 2
    assert len(second["admitted"]) == 5
    assert second["superseded"] == sorted(old_ids)

    tape = CompanionMemory(tmp_path).tape
    statuses = {record.id: record.status for record in tape.read()}
    assert all(statuses[memory_id] == "superseded" for memory_id in old_ids)
    assert all(statuses[memory_id] == "active" for memory_id in second["admitted"])
    active_versions = {record.origin.get("life_version") for record in tape.read()
                       if record.status == "active"}
    assert active_versions == {2}
    assert creator.history_versions() == [1, 2]


def test_non_resurrection_after_reload(tmp_path):
    creator = _setup(tmp_path)
    first = admit_life(tmp_path)
    old_id = first["admitted"][2]

    creator.approve(_v2())
    admit_life(tmp_path)

    reloaded = CompanionMemory(tmp_path)
    assert all(record.id != old_id for record in reloaded.search("caderno"))
    assert reloaded.evidence([old_id]) == []
    statuses = {record.id: record.status for record in reloaded.tape.read()}
    assert statuses[old_id] == "superseded"


def test_conflict_when_same_source_has_different_content(tmp_path):
    _setup(tmp_path)
    admit_life(tmp_path)
    tape = CompanionMemory(tmp_path).tape
    tape.append(MemoryRecord(
        type="story", summary="conteúdo divergente",
        source="life#1#life-0002",
    ))
    with pytest.raises(ValueError, match="different content"):
        admit_life(tmp_path)


def test_missing_current_fails_without_tape_change(tmp_path):
    with pytest.raises(ValueError, match="no approved life"):
        admit_life(tmp_path)
    assert not (tmp_path / "tape.jsonl").exists()


def test_retired_events_are_not_admitted(tmp_path):
    creator = _setup(tmp_path)
    doc = _v2()
    extra = copy.deepcopy(doc["events"][0])
    extra.update({
        "event_id": "life-0007", "title": "Evento retirado",
        "summary": "Um evento que não entra no recall.",
        "causes": [], "effects": [], "status": "retired",
        "approved_at": "", "approved_by": "",
    })
    doc["events"].append(extra)
    creator.approve(doc)

    result = admit_life(tmp_path)
    assert len(result["admitted"]) == 5
    tape = CompanionMemory(tmp_path).tape
    assert all("life-0007" not in record.source for record in tape.read())


def test_publish_batch_rejects_unknown_supersede(tmp_path):
    tape = CompanionMemory(tmp_path).tape
    with pytest.raises(ValueError, match="unknown id"):
        tape.publish_batch(
            [MemoryRecord(type="story", summary="x")], supersede=["M0999"])
    assert not (tmp_path / "tape.jsonl").exists()
