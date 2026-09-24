"""C1: synthetic life schema, validator and example templates."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from memory_machine.companion_life import validate_life
from memory_machine.secrets import SecretError

ROOT = Path(__file__).resolve().parents[1]


def _template(slug: str) -> dict:
    path = ROOT / "personas" / slug / "life" / "v1.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _event(event_id: str, **overrides) -> dict:
    event = {
        "event_id": event_id, "life_version": 1, "title": "Titulo",
        "summary": "Resumo do evento.", "event_time": "2020-01-02",
        "time_precision": "day", "place": "Vila",
        "participants": [{"id": "lia", "role": "a menina"}],
        "causes": [], "effects": [], "status": "draft",
        "provenance": {"kind": "synthetic_life", "generator": "manual",
                       "sheet_version": 1, "prompt": "", "model": "",
                       "seed": ""},
        "approved_at": "", "approved_by": "",
    }
    event.update(overrides)
    return event


def _draft(events: list[dict]) -> dict:
    return {
        "life_version": 1, "sheet_version": 1, "status": "draft",
        "reference_date": "",
        "world": {
            "continuity_id": "main",
            "places": [{"id": "vila", "name": "Vila"}],
            "people": [{"id": "amiga", "name": "Amiga", "relation": "amiga"}],
            "forbidden_subjects": [],
        },
        "events": events, "approved_at": "", "approved_by": "",
    }


def test_lia_template_is_valid_and_approved():
    doc = validate_life(_template("lia"), self_id="lia")
    assert doc["status"] == "approved"
    assert doc["life_version"] == 1 and doc["sheet_version"] == 1
    assert len(doc["events"]) == 6
    assert all(event["status"] == "approved" for event in doc["events"])
    assert [place["id"] for place in doc["world"]["places"]] == [
        "vila-do-farol", "biblioteca-do-porto", "casa-da-avo"]
    assert {person["id"] for person in doc["world"]["people"]} == {
        "avo-lia", "mestre-bento", "clarice"}


def test_tomas_template_is_valid_and_approved():
    doc = validate_life(_template("tomas"), self_id="tomas")
    assert doc["status"] == "approved"
    assert len(doc["events"]) == 5
    assert doc["world"]["continuity_id"] == "main"


def test_draft_needs_no_approval_act_and_small_size():
    doc = validate_life(_draft([_event("life-0001")]))
    assert doc["events"][0]["status"] == "draft"
    assert doc["approved_at"] == "" and doc["approved_by"] == ""


def test_rejects_bad_versions_and_unknown_fields():
    doc = _draft([])
    doc["life_version"] = 0
    with pytest.raises(ValueError, match="life_version"):
        validate_life(doc)

    doc = _draft([])
    doc["extra"] = 1
    with pytest.raises(ValueError, match="fields"):
        validate_life(doc)

    doc = _draft([_event("life-0001", life_version=2)])
    with pytest.raises(ValueError, match="life_version must match"):
        validate_life(doc)

    doc = _draft([_event("life-0001")])
    doc["events"][0]["provenance"]["sheet_version"] = 2
    with pytest.raises(ValueError, match="sheet_version must match"):
        validate_life(doc)


def test_rejects_bad_ids_links_and_participants():
    doc = _draft([_event("Life-01")])
    with pytest.raises(ValueError, match="event_id"):
        validate_life(doc)

    doc = _draft([_event("life-0001"), _event("life-0001")])
    with pytest.raises(ValueError, match="duplicate event id"):
        validate_life(doc)

    doc = _draft([_event("life-0001", effects=["life-0099"])])
    with pytest.raises(ValueError, match="unknown link"):
        validate_life(doc)

    doc = _draft([_event("life-0001", causes=["life-0001"])])
    with pytest.raises(ValueError, match="self link"):
        validate_life(doc)

    doc = _draft([_event("life-0001", participants=["desconhecida"])])
    with pytest.raises(ValueError, match="unknown id"):
        validate_life(doc)

    doc = _draft([_event("life-0001",
                         participants=[{"id": "lia"}, {"id": "lia"}])])
    with pytest.raises(ValueError, match="duplicate id"):
        validate_life(doc)

    doc = _draft([_event("life-0001", participants=["a", "b", "c", "d", "e", "f"])])
    with pytest.raises(ValueError, match="at most 5"):
        validate_life(doc)


def test_rejects_cycles():
    first = _event("life-0001", time_precision="unknown", event_time="",
                   effects=["life-0002"])
    second = _event("life-0002", time_precision="unknown", event_time="",
                    effects=["life-0001"])
    with pytest.raises(ValueError, match="cycle"):
        validate_life(_draft([first, second]))


def test_rejects_time_contradictions():
    later = _event("life-0001", event_time="2021-01-02")
    earlier = _event("life-0002", event_time="2020-01-02",
                     causes=["life-0001"])
    later["effects"] = ["life-0002"]
    with pytest.raises(ValueError, match="happens later"):
        validate_life(_draft([later, earlier]))

    doc = _draft([_event("life-0001")])
    doc["reference_date"] = "2019-01-01"
    with pytest.raises(ValueError, match="after the reference date"):
        validate_life(doc)

    doc = _draft([_event("life-0001", time_precision="year",
                         event_time="2020-05")])
    with pytest.raises(ValueError, match="year precision"):
        validate_life(doc)

    doc = _draft([_event("life-0001", time_precision="unknown",
                         event_time="2020")])
    with pytest.raises(ValueError, match="unknown precision"):
        validate_life(doc)


def test_rejects_secret_like_content():
    doc = _draft([_event("life-0001",
                         summary="a chave é sk-abcdefghijklmnopqrstuvwx")])
    with pytest.raises(SecretError):
        validate_life(doc)


def test_rejects_bad_approval_acts():
    doc = _draft([_event("life-0001", status="approved")])
    with pytest.raises(ValueError, match="approved_at"):
        validate_life(doc)

    doc = _draft([_event("life-0001", approved_at="2020-01-01T00:00:00+00:00")])
    with pytest.raises(ValueError, match="non-approved events"):
        validate_life(doc)

    doc = _draft([_event("life-0001")])
    doc["status"] = "approved"
    doc["approved_at"] = "2026-01-01T00:00:00+00:00"
    doc["approved_by"] = "owner"
    with pytest.raises(ValueError, match="at least 5 events"):
        validate_life(doc)


def test_rejects_generated_without_provenance():
    provenance = {"kind": "synthetic_life", "generator": "generated",
                  "sheet_version": 1, "prompt": "p", "model": "", "seed": "s"}
    doc = _draft([_event("life-0001", provenance=provenance)])
    with pytest.raises(ValueError, match="provenance.model"):
        validate_life(doc)
    provenance["model"] = "m"
    doc = _draft([_event("life-0001", provenance=provenance)])
    assert validate_life(doc)["events"][0]["provenance"]["model"] == "m"


def test_rejects_too_many_events():
    events = [_event(f"life-{index:04d}") for index in range(1, 32)]
    with pytest.raises(ValueError, match="at most 30"):
        validate_life(_draft(events))


def test_normalizes_without_mutating_input():
    doc = _draft([_event("life-0001")])
    snapshot = copy.deepcopy(doc)
    validate_life(doc)
    assert doc == snapshot
