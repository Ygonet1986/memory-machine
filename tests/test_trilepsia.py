"""T1: trilepsia extractor, validator, tape units (deterministic, no LLM).

Covers the T0 invariants (docs/TRILEPSIA_V1.md): declared schema, prompt
temporal isolation, exact spans, epistemic rules, local refs only, counted
caps, raw envelope on tape, provenance refs, hash gate, idempotency and the
pending/failed queues.
"""

from __future__ import annotations

import inspect
import json

import pytest

from memory_machine.attachments import _file_hash
from memory_machine.tape import MemoryRecord, Tape
from memory_machine.trilepsia import (
    CAPS,
    SCHEMA_KEYS,
    TrilepsiaError,
    TrilepsiaExtractor,
    build_prompt,
    existing_units,
    ingest_trilepsia,
    show_unit,
    trilepsia_status,
    unit_source,
    validate_trilepsia,
    window_groups,
)

ORIGINAL = (
    "Alpha beta gamma. The value is 42. The user reported the value changed.\n\n"
    "A second paragraph mentions that the measurement used a thermometer.\n"
)


def _valid_payload() -> dict:
    value_start = ORIGINAL.index("The value is 42.")
    content = "The value is 42."
    return {
        "schema": "doc_claims_v1",
        "entities": [
            {"ref": "e1", "name": "Alpha", "kind": "object", "confidence": 0.9,
             "evidence_span": [0, 5]},
        ],
        "events": [
            {"ref": "ev1", "agent": "e1", "action": "report",
             "evidence_span": [0, 16]},
        ],
        "qualifications": [
            {"attr": "value", "value": "42", "evaluated": False,
             "evidence_span": [value_start, value_start + len(content)]},
        ],
        "observations": [
            {"kind": "reported", "content": content, "method": "",
             "evidence_span": [value_start, value_start + len(content)]},
        ],
        "hypotheses": [
            {"ref": "h1", "class": "cause", "statement": "value changed",
             "state": "open", "evidence_for": [], "evidence_against": [],
             "assumptions": []},
        ],
        "query_policies": [
            {"ref": "q1", "question": "was the value measured?",
             "expected_info": "method", "cost": 1},
        ],
        "unknowns": ["who measured it"],
    }


class FakeClient:
    def __init__(self, payload, *, fail: bool = False):
        self.payload = payload
        self.fail = fail
        self.calls = 0

    def complete_with_reasoning(self, messages, temperature=0.0):
        self.calls += 1
        if self.fail:
            raise RuntimeError("transport down")
        return json.dumps(self.payload), ""


def test_prompt_isolation():
    params = set(inspect.signature(build_prompt).parameters)
    assert params == {"window_text", "schema"}  # no question/task can enter
    messages = build_prompt("### [M0001] char 0-5\nAlpha", "doc_claims_v1")
    assert messages[1]["content"] == "### [M0001] char 0-5\nAlpha"
    assert "doc_claims_v1" in messages[0]["content"]
    assert "NEVER use ids" in messages[0]["content"]


def test_validator_accepts_exact_spans():
    validated, dropped = validate_trilepsia(
        _valid_payload(), original=ORIGINAL, schema="doc_claims_v1"
    )
    assert dropped == {}
    assert validated["observations"][0]["content"] == "The value is 42."
    assert validated["qualifications"][0]["evaluated"] is False
    assert validated["hypotheses"][0]["state"] == "open"


def test_validator_rejects_paraphrase_and_bounds():
    payload = _valid_payload()
    payload["observations"][0]["content"] = "the value is about 42"
    validated, dropped = validate_trilepsia(
        payload, original=ORIGINAL, schema="doc_claims_v1"
    )
    assert validated["observations"] == []
    assert dropped["observations"]["invalid"] == 1

    payload = _valid_payload()
    payload["entities"][0]["evidence_span"] = [0, 99999]
    validated, dropped = validate_trilepsia(
        payload, original=ORIGINAL, schema="doc_claims_v1", window_span=(0, 16)
    )
    assert validated["entities"] == []

    payload = _valid_payload()
    payload["entities"][0]["evidence_span"] = [20, 30]  # inside original, outside window
    validated, dropped = validate_trilepsia(
        payload, original=ORIGINAL, schema="doc_claims_v1", window_span=(0, 16)
    )
    assert validated["entities"] == []


def test_validator_epistemic_rules():
    payload = _valid_payload()
    payload["observations"][0]["kind"] = "observed"  # no method -> invalid
    validated, _ = validate_trilepsia(payload, original=ORIGINAL, schema="s")
    assert validated["observations"] == []

    payload = _valid_payload()
    payload["observations"][0]["kind"] = "observed"
    payload["observations"][0]["method"] = "thermometer"
    validated, _ = validate_trilepsia(payload, original=ORIGINAL, schema="s")
    assert validated["observations"][0]["kind"] == "observed"

    payload = _valid_payload()
    payload["hypotheses"][0]["state"] = "proven"
    validated, _ = validate_trilepsia(payload, original=ORIGINAL, schema="s")
    assert validated["hypotheses"] == []

    payload = _valid_payload()
    payload["hypotheses"][0]["relation"] = "causes"
    validated, _ = validate_trilepsia(payload, original=ORIGINAL, schema="s")
    assert validated["hypotheses"] == []

    payload = _valid_payload()
    payload["hypotheses"][0]["relation"] = "causes"
    payload["hypotheses"][0]["assumptions"] = ["no confounders"]
    validated, _ = validate_trilepsia(payload, original=ORIGINAL, schema="s")
    assert len(validated["hypotheses"]) == 1


def test_validator_local_refs_and_caps():
    payload = _valid_payload()
    payload["events"][0]["agent"] = "E0001"  # graph id -> invalid
    validated, dropped = validate_trilepsia(payload, original=ORIGINAL, schema="s")
    assert validated["events"] == []
    assert dropped["events"]["invalid"] == 1

    payload = _valid_payload()
    payload["entities"] = [
        {"ref": f"e{i}", "name": f"n{i}"} for i in range(CAPS["entities"] + 3)
    ]
    validated, dropped = validate_trilepsia(payload, original=ORIGINAL, schema="s")
    assert len(validated["entities"]) == CAPS["entities"]
    assert dropped["entities"]["over_cap"] == 3


def test_validator_requires_structure():
    with pytest.raises(TrilepsiaError):
        validate_trilepsia({"foo": []}, original=ORIGINAL, schema="s")
    with pytest.raises(TrilepsiaError):
        validate_trilepsia([], original=ORIGINAL, schema="s")


def _make_doc(root, text: str = ORIGINAL):
    doc_source = f"spec.txt#{_file_hash(text.strip())}"
    (root / "documents").mkdir(parents=True, exist_ok=True)
    (root / "documents" / "spec.txt").write_text(text, encoding="utf-8")
    tape = Tape(root / "tape.jsonl")
    pieces = [
        "Alpha beta gamma.",
        "The value is 42.",
        "The user reported the value changed.",
        "A second paragraph mentions that the measurement used a thermometer.",
    ]
    pos = 0
    for index, piece in enumerate(pieces, start=1):
        start = text.find(piece, pos)
        end = start + len(piece)
        pos = end
        tape.append(MemoryRecord(
            type="attachment",
            summary=f"chunk {index}/{len(pieces)}",
            why=piece,
            source=doc_source,
            source_document=doc_source,
            source_span=(start, end),
        ))
    return tape, doc_source


def test_extractor_tape_roundtrip_and_envelope(tmp_path):
    tape, doc_source = _make_doc(tmp_path)
    windows = window_groups(
        [r for r in tape.read() if r.type == "attachment"], 12000
    )
    client = FakeClient(_valid_payload())
    extractor = TrilepsiaExtractor(client)
    envelope = extractor.extract_window(windows[0], ORIGINAL, "doc_claims_v1")
    assert set(envelope) == {
        "schema_version", "extractor", "extractor_version", "raw",
    }
    assert envelope["extractor"] == "trilepsia"
    assert envelope["extractor_version"] == "v1"
    assert envelope["raw"]["entities"][0]["name"] == "Alpha"

    result = ingest_trilepsia(
        tape=tape, root=tmp_path, doc_source=doc_source, schema="doc_claims_v1",
        client=client, extractor=extractor,
        scope="projeto_autorizado",
        validity={"from": "2026-09-16", "until": None},
    )
    assert result["ok"] and result["applied"] == result["windows"]
    units = [r for r in tape.read() if r.type == "trilepsia_unit"]
    assert len(units) == result["windows"]
    unit = units[0]
    assert set(unit.trilepsia) == {
        "schema_version", "extractor", "extractor_version", "raw", "V",
    }
    assert unit.trilepsia["schema_version"] == "doc_claims_v1"
    assert unit.trilepsia["V"]["scope"] == "projeto_autorizado"
    assert unit.trilepsia["V"]["validity"] == {"from": "2026-09-16", "until": None}
    assert unit.trilepsia["V"]["permissions"] == {
        "local_memory": True, "local_training": True, "shared_training": False,
    }
    assert unit.derived_from == [r.id for r in windows[0].members]
    assert "type/trilepsia_unit" in unit.views
    assert unit.source.startswith(f"{doc_source}#w")
    assert "#trilepsia/v1" in unit.source
    # selects-not-supplies: the factual quote lives only in the envelope refs,
    # never copied into summary/why
    assert "The value is 42." not in unit.summary
    assert "The value is 42." not in unit.why
    assert show_unit(tape, unit.id)["trilepsia"]["raw"]["observations"][0]["content"] == (
        "The value is 42."
    )


def test_idempotency_by_version(tmp_path):
    tape, doc_source = _make_doc(tmp_path)
    client = FakeClient(_valid_payload())
    first = ingest_trilepsia(
        tape=tape, root=tmp_path, doc_source=doc_source, schema="s", client=client,
        extractor=TrilepsiaExtractor(client),
    )
    assert first["applied"] == first["windows"] and first["skipped"] == 0
    client.calls = 0
    second = ingest_trilepsia(
        tape=tape, root=tmp_path, doc_source=doc_source, schema="s", client=client,
        extractor=TrilepsiaExtractor(client),
    )
    assert second["applied"] == 0 and second["skipped"] == second["windows"]
    assert client.calls == 0  # idempotent: no LLM call on the same version

    third = ingest_trilepsia(
        tape=tape, root=tmp_path, doc_source=doc_source, schema="s", client=client,
        extractor=TrilepsiaExtractor(client, version="v2"),
    )
    assert third["applied"] == third["windows"]
    assert len(existing_units(tape, "trilepsia/v2")) == third["windows"]
    assert unit_source(doc_source, "w01", "trilepsia/v1") in {
        r.source for r in tape.read() if r.type == "trilepsia_unit"
    }


def test_hash_gate_and_missing_original(tmp_path):
    tape, doc_source = _make_doc(tmp_path)
    client = FakeClient(_valid_payload())
    (tmp_path / "documents" / "spec.txt").write_text("tampered", encoding="utf-8")
    tampered = ingest_trilepsia(
        tape=tape, root=tmp_path, doc_source=doc_source, schema="s", client=client,
    )
    assert tampered["ok"] is False and "hash mismatch" in tampered["error"]
    (tmp_path / "documents" / "spec.txt").unlink()
    missing = ingest_trilepsia(
        tape=tape, root=tmp_path, doc_source=doc_source, schema="s", client=client,
    )
    assert missing["ok"] is False and "missing" in missing["error"]


def test_queues_pending_and_failed(tmp_path):
    tape, doc_source = _make_doc(tmp_path)
    transient = ingest_trilepsia(
        tape=tape, root=tmp_path, doc_source=doc_source, schema="s",
        client=FakeClient({}, fail=True), max_attempts=2,
    )
    assert transient["failed"] == transient["windows"]
    failed_rows = (tmp_path / "trilepsia" / "failed.jsonl").read_text().splitlines()
    assert len(failed_rows) == transient["windows"]

    bad = FakeClient({"nothing": "here"})  # no trilepsia keys -> definitive
    definitive = ingest_trilepsia(
        tape=tape, root=tmp_path, doc_source=doc_source, schema="s",
        client=bad, max_attempts=3,
    )
    assert definitive["failed"] == definitive["windows"]
    assert definitive["pending"] == 0


def test_status_counts(tmp_path):
    tape, doc_source = _make_doc(tmp_path)
    client = FakeClient(_valid_payload())
    ingest_trilepsia(
        tape=tape, root=tmp_path, doc_source=doc_source, schema="doc_claims_v1",
        client=client, extractor=TrilepsiaExtractor(client),
    )
    status = trilepsia_status(tape, tmp_path)
    assert status["units"] >= 1
    assert status["schemas"] == {"doc_claims_v1": status["units"]}
    assert set(status["typed_counts"]) == set(SCHEMA_KEYS)
    assert status["typed_counts"]["entities"] >= 1
    assert status["queues"] == {"pending": 0, "failed": 0}
