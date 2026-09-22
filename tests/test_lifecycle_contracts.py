"""Lifecycle v1 step-2 contracts: schemas, hashes, normalisation, precedence,
projection idempotency and atomic rebuild.

These tests freeze the deterministic foundation before the rules arm (B) is
measured: same input -> same decision, conservative fingerprints, correction
before dedup, atomic batches, conflict detection, no partial projection.
"""

from __future__ import annotations

import json

import pytest

from memory_machine import lifecycle as lc


def _record(memory_id="M0001", text="usamos PostgreSQL como banco primário",
            tape_type="decision", session="S1", seq=1, **extra):
    row = {"memory_id": memory_id, "text": text, "tape_type": tape_type,
           "session": session, "seq": seq}
    row.update(extra)
    return row


# --------------------------------------------------------------- fingerprints


def test_same_input_same_decision():
    record = _record()
    first = lc.classify_record(record)
    second = lc.classify_record(record)
    assert first.normative() == second.normative()
    assert first.decision_key == second.decision_key


def test_relevant_field_change_alters_input_hash():
    base = lc.input_hash(_record())
    assert lc.input_hash(_record(text="outro texto")) != base
    assert lc.input_hash(_record(tape_type="memory")) != base
    assert lc.input_hash(_record(session="S2")) != base


def test_audit_only_field_does_not_alter_normative_content():
    base = lc.classify_record(_record())
    stamped = lc.classify_record(_record(created_at="2026-09-22T00:00:00Z",
                                         decided_at="ignored"))
    assert base.input_hash == stamped.input_hash
    assert base.normative() == stamped.normative()


def test_policy_version_changes_decision_key():
    record = _record()
    decision = lc.classify_record(record)
    other = lc.decision_key(memory_id=record["memory_id"],
                            input_hash_value=decision.input_hash, arm="B",
                            policy_version="lifecycle-v2")
    assert other != decision.decision_key


def test_nfkc_crlf_and_case_handling():
    composed = "sérviço"
    decomposed = "se\u0301rviço"
    assert lc.exact_hash(composed) == lc.exact_hash(decomposed)  # NFKC
    assert lc.exact_hash("Sérviço\r\n") == lc.exact_hash("Sérviço")  # CRLF + spaces
    assert lc.exact_hash("Sérviço") != lc.exact_hash("sérviço")  # case preserved
    assert lc.normalized_hash("Sérviço") == lc.normalized_hash("sérviço")  # comparison


def test_negation_numbers_and_identifiers_stay_distinct():
    assert lc.normalized_hash("não usamos Redis") != lc.normalized_hash("usamos Redis")
    assert lc.normalized_hash("p95 = 500 ms") != lc.normalized_hash("p95 = 600 ms")
    assert lc.normalized_hash("memory M0001") != lc.normalized_hash("memory M0002")


# ------------------------------------------------------------------ precedence


def test_invalid_and_secret_come_first():
    empty = lc.classify_record(_record(text="   ", tape_type="decision"))
    assert empty.target_class == "reject" and empty.decisive_reason == "invalid_record"
    secret = lc.classify_record(_record(
        text="a chave é sk-abcdefghijklmnopqrstuvwxyz123456 podes guardar"))
    assert secret.target_class == "reject"
    assert secret.decisive_reason == "secret_blocked"


def test_correction_precedes_deduplication():
    prior = _record(memory_id="M0001", text="usamos PostgreSQL como banco primário")
    correction = _record(
        memory_id="M0002",
        text="não usaremos mais PostgreSQL como banco primário; trocamos por CockroachDB",
        tape_type="memory", seq=2)
    decision = lc.classify_record(correction, previous=[prior])
    assert decision.target_class == "semantic"
    assert decision.decisive_reason == "decision_change"
    assert decision.duplicate_kind is None


def test_typed_record_and_stability_markers():
    typed = lc.classify_record(_record(tape_type="bugfix", text="corrigi o pool"))
    assert typed.target_class == "semantic" and typed.decisive_reason == "typed_record"
    restriction = lc.classify_record(_record(tape_type="memory",
                                             text="Importante: nunca trocar sem benchmark"))
    assert restriction.target_class == "semantic"
    assert restriction.decisive_reason == "restriction"


def test_duplicates_within_window_and_valid_repetition_across_sessions():
    prior = _record(memory_id="M0001", text="rodamos o teste de carga; p95 820 ms",
                    tape_type="build")
    exact = lc.classify_record(_record(memory_id="M0002",
                                       text="rodamos o teste de carga; p95 820 ms",
                                       tape_type="memory", seq=2), previous=[prior])
    assert exact.target_class == "reject" and exact.decisive_reason == "duplicate_exact"
    normalized = lc.classify_record(
        _record(memory_id="M0003", text="Rodamos  o teste de carga, P95 820 ms!",
                tape_type="memory", seq=3), previous=[prior])
    assert normalized.target_class == "reject"
    assert normalized.decisive_reason == "duplicate_normalized"

    decisions = lc.classify_records([
        _record(memory_id="M0001", text="decidimos usar PostgreSQL", seq=1),
        _record(memory_id="M0002", text="decidimos usar PostgreSQL", session="S2", seq=2),
    ])
    assert all(d.target_class == "semantic" for d in decisions)  # valid repetition


def test_ambiguous_and_no_signal_buckets():
    weak = lc.classify_record(_record(text="talvez devêssemos considerar Kafka no futuro",
                                      tape_type="memory"))
    assert weak.target_class == "episodic" and weak.decisive_reason == "ambiguous"
    chatter = lc.classify_record(_record(text="vamos ver como fica amanhã",
                                         tape_type="memory"))
    assert chatter.target_class == "event_only"
    assert chatter.promoted is False


# ------------------------------------------------------------------- projection


def test_append_is_idempotent_and_conflicts_are_detected(tmp_path):
    projection = lc.LifecycleProjection(tmp_path)
    record = _record()
    decision = lc.classify_record(record)
    assert len(projection.append_decisions([decision])) == 1
    assert len(projection.append_decisions([decision])) == 0  # no duplicate line
    assert len(projection.load_decisions()) == 1

    conflicting = lc.Decision(
        memory_id=decision.memory_id, arm="B", target_class="reject",
        promoted=False, decisive_reason="invalid_record",
        reason_codes=("invalid_record",), confidence=1.0,
        input_hash=decision.input_hash)
    with pytest.raises(lc.LifecycleConflict):
        projection.append_decisions([conflicting])


def test_rebuild_is_normalised_identical_and_order_independent(tmp_path):
    records = [
        _record(memory_id="M0002", seq=5, text="ok"),
        _record(memory_id="M0001", seq=5, text="decidimos usar PostgreSQL"),
    ]
    projection = lc.LifecycleProjection(tmp_path)
    projection.rebuild(records)
    first = (tmp_path / "lifecycle" / "decisions.jsonl").read_bytes()
    projection.rebuild(list(reversed(records)))
    second = (tmp_path / "lifecycle" / "decisions.jsonl").read_bytes()
    assert first == second  # stable order by (seq, memory_id)
    rows = [json.loads(line) for line in first.decode().splitlines()]
    assert [row["memory_id"] for row in rows] == ["M0001", "M0002"]


def test_failure_never_publishes_a_partial_projection(tmp_path, monkeypatch):
    projection = lc.LifecycleProjection(tmp_path)
    calls = {"n": 0}
    original = lc._classify

    def flaky(record, previous, *, arm="B"):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("simulated failure")
        return original(record, previous, arm=arm)

    monkeypatch.setattr(lc, "_classify", flaky)
    with pytest.raises(RuntimeError):
        lc.classify_records([_record(memory_id="M0001"),
                             _record(memory_id="M0002", seq=2)])
    assert not (tmp_path / "lifecycle" / "decisions.jsonl").exists()
