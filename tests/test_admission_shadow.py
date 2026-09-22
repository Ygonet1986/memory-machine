"""Admission shadow instrumentation: privacy, derived metrics, neutrality."""

from __future__ import annotations

import hashlib
import json
import os

from memory_machine import admission_shadow as shadow
from memory_machine.config import Config
from memory_machine.coordinator import Machine
from memory_machine.tape import MemoryRecord
from memory_machine.whiteboard import Annotation

from fakes import FakeClient, text

QUESTION = "Qual a pool do Postgres em /srv/app/db.py na v2.1.0?"


def _record(**kwargs):
    base = dict(question=QUESTION, session_id="s1", records=[], annotations=[],
                payload=[], event_hits=[], cached=False,
                ts="2026-01-01T00:00:00+00:00")
    base.update(kwargs)
    return shadow.build_record(**base)


def _machine(root, handler):
    client = FakeClient(handler)
    cfg = Config(capacity=3, router_enabled=False,
                 evidence_payload="budgeted")
    return Machine(root, config=cfg, client=client), client


def _handler(messages, temperature):
    if "You are a memory agent" in text(messages, "system"):
        return ('{"annotations":[{"memory_id":"M0001","note":"db choice",'
                '"relevance":0.9}]}')
    raise AssertionError("recall should only call agents")


def test_shadow_record_is_derived_only_and_private():
    record = MemoryRecord(id="M0001", type="decision",
                          summary="Use Postgres pool 20 em /srv/app/db.py",
                          why="version v2.1.0 pinned")
    annotation = Annotation(memory_id="M0001", note="db choice", relevance=0.9)
    payload = [{"memory_id": "M0001", "used_chars": 123,
                "evidence": "CONTEUDO SENSIVEL"}]

    entry = _record(records=[record], annotations=[annotation], payload=payload)
    assert entry["v"] == 2
    assert isinstance(entry["judged_subsample"], bool)
    assert isinstance(entry["retrieval_ms"], (int, float))
    assert set(entry["lexical"]) == {"candidates", "delivered", "delivered_chars",
                                     "empty", "comparator_p1_margin50",
                                     "comparator_p2_margin90"}
    line = json.dumps(entry, ensure_ascii=False)
    assert "Postgres" not in line
    assert "CONTEUDO SENSIVEL" not in line
    assert QUESTION not in line
    assert entry["question"]["sha256"] == hashlib.sha256(
        QUESTION.encode("utf-8")).hexdigest()[:16]
    candidate = entry["active"][0]
    assert candidate["memory_id"] == "M0001"
    assert candidate["origin"] == "active"
    assert candidate["type"] == "decision"
    assert candidate["chars_if_admitted"] == 123
    assert candidate["in_payload"] is True
    assert candidate["counterfactual_admitted"] is True
    assert "srv/app/db.py" in candidate["entity_matches"]
    assert "v2.1.0" in candidate["entity_matches"]
    assert 0.0 <= candidate["lexical_overlap"] <= 1.0
    assert 0.0 <= candidate["rare_term_coverage"] <= 1.0


def test_event_rule_counterfactual_and_ranking():
    hits = [
        {"session_id": "s2", "memory_id": "M0009", "type": "lesson",
         "summary": "alpha", "why": "beta", "score": 2.0},
        {"session_id": "s3", "memory_id": "M0010", "type": "lesson",
         "summary": "gamma", "why": "delta", "score": 1.5},
        {"session_id": "s4", "memory_id": "M0011", "type": "decision",
         "summary": "epsilon", "why": "zeta", "score": 0.4},
    ]
    entry = _record(event_hits=hits)
    first, second, third = entry["event_log"]
    assert [c["rank"] for c in entry["event_log"]] == [1, 2, 3]
    assert first["counterfactual_admitted"] is True
    assert second["counterfactual_admitted"] is False
    assert third["counterfactual_admitted"] is False
    assert first["source_session"] == "s2"
    assert all(c["in_payload"] is False for c in entry["event_log"])
    assert entry["payload_items"] == 0 and entry["payload_chars"] == 0


def test_shadow_is_off_by_default_and_recall_stays_identical(tmp_path, monkeypatch):
    monkeypatch.delenv(shadow.ENV_FLAG, raising=False)
    monkeypatch.delenv(shadow.ENV_PATH, raising=False)
    control_root = tmp_path / "control"
    control_root.mkdir()
    control, control_client = _machine(control_root, _handler)
    control.add_memory(MemoryRecord(type="decision", summary="Use Postgres",
                                    why="ACID"))
    control_result = control.recall("which database?")
    assert not (control_root / "admission_shadow.jsonl").exists()

    shadow_root = tmp_path / "shadow"
    shadow_root.mkdir()
    shadow_path = tmp_path / "shadow.jsonl"
    monkeypatch.setenv(shadow.ENV_FLAG, "1")
    monkeypatch.setenv(shadow.ENV_PATH, str(shadow_path))
    instrumented, instrumented_client = _machine(shadow_root, _handler)
    instrumented.add_memory(MemoryRecord(type="decision",
                                         summary="Use Postgres", why="ACID"))
    result = instrumented.recall("which database?")

    assert len(instrumented_client.calls) == len(control_client.calls)
    for key in ("annotations", "evidence_payload", "evidence_payload_chars",
                "tape_records"):
        assert result[key] == control_result[key]

    if os.name == "posix":
        assert (shadow_path.stat().st_mode & 0o777) == 0o600

    lines = shadow_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["cached"] is False
    assert entry["active"][0]["memory_id"] == "M0001"
    assert entry["payload_items"] == 1

    instrumented.recall("which database?")  # identical subject -> cache
    lines = shadow_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    cached_entry = json.loads(lines[1])
    assert cached_entry["cached"] is True
    assert cached_entry["active"][0]["memory_id"] == "M0001"
