"""Synthetic life schema and validator (C1).

Pure functions, no writes: validate an approved-or-draft life version document
(frozen by docs/COMPANION_LIFE_V1_CONTRACT.md) before any publication to the
tape. Rejections cover versions, unknown fields, IDs, links (unknown, self,
cycles, time-respecting), contradictions with the reference date, limits,
approval acts and secret-like content.
"""

from __future__ import annotations

import re
from typing import Any

from .secrets import assert_clean

LIFE_MIN_EVENTS = 5
LIFE_MAX_EVENTS = 30
SUMMARY_LIMIT = 500
TITLE_LIMIT = 120
MAX_PARTICIPANTS = 5
MAX_LINKS = 5
MAX_PLACES = 8
MAX_PEOPLE = 8
MAX_FORBIDDEN = 8
MAX_ROLE = 80

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{2,31}$")
_TIME_RE = re.compile(r"^(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?$")
_PRECISIONS = ("year", "month", "day", "unknown")
_STATUSES = ("draft", "approved", "retired")
_GENERATORS = ("manual", "generated", "imported")

_LIFE_FIELDS = {"life_version", "sheet_version", "status", "reference_date",
                "world", "events", "approved_at", "approved_by"}
_WORLD_FIELDS = {"continuity_id", "places", "people", "forbidden_subjects"}
_EVENT_FIELDS = {"event_id", "life_version", "title", "summary", "event_time",
                 "time_precision", "place", "participants", "causes", "effects",
                 "status", "provenance", "approved_at", "approved_by"}
_PROVENANCE_FIELDS = {"kind", "generator", "sheet_version", "prompt", "model",
                      "seed"}


def _text(value: Any, label: str, limit: int) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a string")
    text = value.strip()
    if len(text) > limit:
        raise ValueError(f"{label} must have at most {limit} characters")
    if any(ord(char) < 32 for char in text):
        raise ValueError(f"{label} must be a single line")
    assert_clean(text)
    return text


def _required_text(value: Any, label: str, limit: int) -> str:
    text = _text(value, label, limit)
    if not text:
        raise ValueError(f"{label} must not be empty")
    return text


def _int(value: Any, label: str, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{label} must be an integer >= {minimum}")
    return value


def _id(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _ID_RE.fullmatch(value):
        raise ValueError(f"{label} must be an opaque id ([a-z0-9-], 3-32)")
    return value


def _id_list(value: Any, label: str, limit: int) -> list[str]:
    if not isinstance(value, list) or len(value) > limit:
        raise ValueError(f"{label} must be a list of at most {limit} ids")
    out: list[str] = []
    for item in value:
        identifier = _id(item, label)
        if identifier in out:
            raise ValueError(f"{label} has a duplicate id: {identifier}")
        out.append(identifier)
    return out


def _timestamp(value: Any, label: str) -> str:
    from datetime import datetime

    text = _required_text(value, label, 64)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError
    except ValueError as exc:
        raise ValueError(f"{label} must be a timezone-aware ISO timestamp") from exc
    return text


def _partial_key(event_time: str) -> tuple[int, int, int] | None:
    match = _TIME_RE.fullmatch(event_time)
    if not match:
        return None
    year, month, day = match.groups()
    return (int(year), int(month or 0), int(day or 0))


def time_sort_key(event_time: str) -> tuple[int, int, int]:
    """Sortable key for partial dates; unknown times sort last."""
    key = _partial_key(event_time or "")
    return key if key is not None else (9999, 12, 31)


def _check_time(event_time: str, precision: str, label: str) -> str:
    if precision == "unknown":
        if event_time:
            raise ValueError(f"{label}: unknown precision forbids an exact time")
        return ""
    key = _partial_key(event_time)
    if key is None:
        raise ValueError(f"{label}: event_time must be YYYY, YYYY-MM or YYYY-MM-DD")
    year, month, day = key
    if precision == "year" and (month or day):
        raise ValueError(f"{label}: year precision forbids a month or day")
    if precision == "month" and day:
        raise ValueError(f"{label}: month precision forbids a day")
    if month and not 1 <= month <= 12:
        raise ValueError(f"{label}: month out of range")
    if day and not 1 <= day <= 31:
        raise ValueError(f"{label}: day out of range")
    return event_time


def _world(world: Any, self_id: str) -> tuple[dict[str, Any], set[str]]:
    if not isinstance(world, dict) or set(world) != _WORLD_FIELDS:
        raise ValueError("life.world fields must match the schema")
    continuity = _id(world["continuity_id"], "world.continuity_id")
    places: list[dict[str, str]] = []
    if not isinstance(world["places"], list) or len(world["places"]) > MAX_PLACES:
        raise ValueError(f"world.places must be a list of at most {MAX_PLACES}")
    seen_places: set[str] = set()
    for place in world["places"]:
        if not isinstance(place, dict) or set(place) != {"id", "name"}:
            raise ValueError("world.places entries need exactly id and name")
        pid = _id(place["id"], "world.places.id")
        if pid in seen_places:
            raise ValueError(f"world.places has a duplicate id: {pid}")
        seen_places.add(pid)
        places.append({"id": pid,
                       "name": _required_text(place["name"],
                                              "world.places.name", 80)})
    people: list[dict[str, str]] = []
    if not isinstance(world["people"], list) or len(world["people"]) > MAX_PEOPLE:
        raise ValueError(f"world.people must be a list of at most {MAX_PEOPLE}")
    seen_people: set[str] = set()
    for person in world["people"]:
        if not isinstance(person, dict) or set(person) != {"id", "name", "relation"}:
            raise ValueError("world.people entries need exactly id, name, relation")
        person_id = _id(person["id"], "world.people.id")
        if person_id in seen_people:
            raise ValueError(f"world.people has a duplicate id: {person_id}")
        if person_id == self_id:
            raise ValueError("world.people cannot redeclare the character itself")
        seen_people.add(person_id)
        people.append({
            "id": person_id,
            "name": _required_text(person["name"], "world.people.name", 80),
            "relation": _text(person["relation"], "world.people.relation", 80),
        })
    forbidden = []
    if (not isinstance(world["forbidden_subjects"], list)
            or len(world["forbidden_subjects"]) > MAX_FORBIDDEN):
        raise ValueError(
            f"world.forbidden_subjects must be a list of at most {MAX_FORBIDDEN}")
    for item in world["forbidden_subjects"]:
        forbidden.append(_required_text(item, "world.forbidden_subjects", 120))
    return ({"continuity_id": continuity, "places": places, "people": people,
             "forbidden_subjects": forbidden}, seen_people)


def _participants(value: Any, self_id: str,
                  known: set[str]) -> list[dict[str, str]]:
    if not isinstance(value, list) or len(value) > MAX_PARTICIPANTS:
        raise ValueError(
            f"participants must be a list of at most {MAX_PARTICIPANTS}")
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in value:
        if isinstance(item, str):
            identifier, role = _id(item, "participants"), ""
        elif isinstance(item, dict) and set(item) <= {"id", "role"}:
            identifier = _id(item.get("id", ""), "participants")
            role = _text(item.get("role", ""), "participants.role", MAX_ROLE)
        else:
            raise ValueError("participants entries must be ids or {id, role}")
        if identifier in seen:
            raise ValueError(f"participants has a duplicate id: {identifier}")
        seen.add(identifier)
        if identifier != self_id and identifier not in known:
            raise ValueError(f"participants has an unknown id: {identifier}")
        out.append({"id": identifier, "role": role})
    return out


def _provenance(value: Any, sheet_version: int, label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != _PROVENANCE_FIELDS:
        raise ValueError(f"{label}: provenance fields must match the schema")
    if value["kind"] != "synthetic_life":
        raise ValueError(f"{label}: provenance.kind must be synthetic_life")
    generator = value["generator"]
    if generator not in _GENERATORS:
        raise ValueError(f"{label}: provenance.generator is invalid")
    if value["sheet_version"] != sheet_version:
        raise ValueError(f"{label}: provenance.sheet_version must match the sheet")
    prov = {"kind": "synthetic_life", "generator": generator,
            "sheet_version": sheet_version,
            "prompt": _text(value.get("prompt", ""), f"{label}.prompt", 120),
            "model": _text(value.get("model", ""), f"{label}.model", 80),
            "seed": _text(value.get("seed", ""), f"{label}.seed", 80)}
    if generator == "generated":
        for key in ("prompt", "model", "seed"):
            if not prov[key]:
                raise ValueError(
                    f"{label}: generated events need provenance.{key}")
    return prov


def _events(raw_events: Any, *, self_id: str, sheet_version: int,
            life_version: int, known_people: set[str],
            reference: tuple[int, int, int] | None) -> list[dict[str, Any]]:
    if not isinstance(raw_events, list) or len(raw_events) > LIFE_MAX_EVENTS:
        raise ValueError(f"events must be a list of at most {LIFE_MAX_EVENTS}")
    events: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in raw_events:
        if not isinstance(raw, dict) or set(raw) != _EVENT_FIELDS:
            raise ValueError("event fields must match the schema")
        event_id = _id(raw["event_id"], "event.event_id")
        if event_id in seen:
            raise ValueError(f"duplicate event id: {event_id}")
        seen.add(event_id)
        label = f"event {event_id}"
        event_life = _int(raw["life_version"], f"{label}.life_version", 1)
        if event_life != life_version:
            raise ValueError(f"{label}: life_version must match the document")
        title = _required_text(raw["title"], f"{label}.title", TITLE_LIMIT)
        summary = _required_text(raw["summary"], f"{label}.summary",
                                 SUMMARY_LIMIT)
        precision = raw["time_precision"]
        if precision not in _PRECISIONS:
            raise ValueError(f"{label}: time_precision is invalid")
        event_time = _check_time(str(raw["event_time"] or ""), precision, label)
        if reference is not None and event_time:
            key = _partial_key(event_time)
            if key is not None and key > reference:
                raise ValueError(
                    f"{label}: event_time is after the reference date")
        place = _text(raw["place"], f"{label}.place", 80)
        participants = _participants(raw["participants"], self_id, known_people)
        causes = _id_list(raw["causes"], f"{label}.causes", MAX_LINKS)
        effects = _id_list(raw["effects"], f"{label}.effects", MAX_LINKS)
        status = raw["status"]
        if status not in _STATUSES:
            raise ValueError(f"{label}: status is invalid")
        provenance = _provenance(raw["provenance"], sheet_version, label)
        approved_at = _text(raw.get("approved_at", ""), f"{label}.approved_at", 64)
        approved_by = _text(raw.get("approved_by", ""), f"{label}.approved_by", 80)
        if status == "approved":
            approved_at = _timestamp(raw.get("approved_at", ""),
                                     f"{label}.approved_at")
            approved_by = _required_text(raw.get("approved_by", ""),
                                         f"{label}.approved_by", 80)
        elif approved_at or approved_by:
            raise ValueError(f"{label}: non-approved events carry no approval act")
        events.append({
            "event_id": event_id, "life_version": event_life, "title": title,
            "summary": summary, "event_time": event_time,
            "time_precision": precision, "place": place,
            "participants": participants, "causes": causes, "effects": effects,
            "status": status, "provenance": provenance,
            "approved_at": approved_at, "approved_by": approved_by,
        })
    ids = {event["event_id"] for event in events}
    for event in events:
        for link in event["causes"] + event["effects"]:
            if link not in ids:
                raise ValueError(
                    f"event {event['event_id']}: unknown link {link}")
            if link == event["event_id"]:
                raise ValueError(
                    f"event {event['event_id']}: self link")
        for cause in event["causes"]:
            cause_event = next(e for e in events if e["event_id"] == cause)
            cause_key = _partial_key(cause_event["event_time"])
            event_key = _partial_key(event["event_time"])
            if cause_key and event_key and cause_key > event_key:
                raise ValueError(
                    f"event {event['event_id']}: cause {cause} happens later")
    _check_acyclic(events)
    return events


def _check_acyclic(events: list[dict[str, Any]]) -> None:
    edges: dict[str, set[str]] = {event["event_id"]: set() for event in events}
    for event in events:
        for cause in event["causes"]:
            edges[cause].add(event["event_id"])
        for effect in event["effects"]:
            edges[event["event_id"]].add(effect)
    visiting: set[str] = set()
    done: set[str] = set()

    def visit(node: str) -> None:
        if node in done:
            return
        if node in visiting:
            raise ValueError(f"event links form a cycle at {node}")
        visiting.add(node)
        for child in edges[node]:
            visit(child)
        visiting.discard(node)
        done.add(node)

    for node in list(edges):
        visit(node)


def validate_life(doc: dict[str, Any], *, self_id: str = "lia") -> dict[str, Any]:
    """Validate one life version document; returns the normalized copy."""
    if not isinstance(doc, dict) or set(doc) != _LIFE_FIELDS:
        raise ValueError("life document fields must match the schema")
    _id(self_id, "self_id")
    life_version = _int(doc["life_version"], "life_version", 1)
    sheet_version = _int(doc["sheet_version"], "sheet_version", 1)
    status = doc["status"]
    if status not in _STATUSES:
        raise ValueError("life.status is invalid")
    reference_text = _text(doc["reference_date"], "reference_date", 10)
    reference: tuple[int, int, int] | None = None
    if reference_text:
        reference = _partial_key(reference_text)
        if reference is None or len(reference_text) != 10:
            raise ValueError("reference_date must be YYYY-MM-DD")
    world, known_people = _world(doc["world"], self_id)
    events = _events(doc["events"], self_id=self_id, sheet_version=sheet_version,
                     life_version=life_version, known_people=known_people,
                     reference=reference)
    approved_at = _text(doc.get("approved_at", ""), "approved_at", 64)
    approved_by = _text(doc.get("approved_by", ""), "approved_by", 80)
    if status == "approved":
        if len(events) < LIFE_MIN_EVENTS:
            raise ValueError(
                f"an approved life version needs at least {LIFE_MIN_EVENTS} events")
        approved_at = _timestamp(doc.get("approved_at", ""), "approved_at")
        approved_by = _required_text(doc.get("approved_by", ""), "approved_by", 80)
    elif approved_at or approved_by:
        raise ValueError("non-approved versions carry no approval act")
    return {
        "life_version": life_version,
        "sheet_version": sheet_version,
        "status": status,
        "reference_date": reference_text,
        "world": world,
        "events": events,
        "approved_at": approved_at,
        "approved_by": approved_by,
    }
