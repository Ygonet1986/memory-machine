import json

import pytest

from memory_machine.config import Config
from memory_machine.graph import GraphRelation
from memory_machine.graph_utility import (
    CLIP_MAX,
    CLIP_MIN,
    DEFAULT_ETA,
    DEFAULT_LAMBDA,
    DEFAULT_SCOPE,
    SHRINKAGE_K,
    EdgeKey,
    NavPath,
    UtilityLedger,
    apply_update,
    energy,
    shrink,
)


def _edge(source="E0001", verb="works_in", target="E0002", scope="chunk"):
    return EdgeKey(source=source, relation=verb, target=target, extraction_scope=scope)


def _relation(
    rid="R0001",
    source="E0001",
    verb="marcou",
    target="E0002",
    scope="",
    document="docs/a.txt",
    memory="M0001",
):
    return GraphRelation(
        id=rid,
        source=source,
        relation=verb,
        target=target,
        memory_id=memory,
        source_document=document,
        extraction_scope=scope,
    )


# ------------------------------------------------------------------ EdgeKey
def test_edge_key_is_scope_sensitive():
    a = _edge(scope="chunk")
    b = _edge(scope="document")
    assert a != b
    assert a.to_key() != b.to_key()


def test_edge_key_from_relation_ignores_audit_fields():
    key = EdgeKey.from_relation(_relation(rid="R0001"))
    assert key.to_key() == "E0001|marcou|E0002|chunk"
    other = EdgeKey.from_relation(_relation(rid="R9999", document="docs/other.txt", memory="M0042"))
    assert other.to_key() == key.to_key()


def test_edge_key_empty_scope_defaults_chunk_and_normalizes_case():
    key = EdgeKey.from_relation(_relation(scope=""))
    assert key.extraction_scope == DEFAULT_SCOPE
    key2 = EdgeKey.from_relation(_relation(scope="Document"))
    assert key2.extraction_scope == "document"
    key3 = EdgeKey.from_relation(_relation(verb="Marca"))
    assert key3.relation == "marca"


def test_edge_key_roundtrip():
    key = _edge()
    assert EdgeKey.from_key(key.to_key()) == key


def test_edge_key_equal_entities_are_resolution_criteria():
    a = _edge(source="E0001", target="E0002")
    c = _edge(source="E0001", target="E0003")
    assert a != c


# ---------------------------------------------------------------- numeric
def test_shrink_zero_observations():
    assert shrink(0.5, 0) == 0.0
    assert shrink(0.5, 5) == pytest.approx(0.5 * (5 / (5 + SHRINKAGE_K)))


def test_apply_update_matches_preregistered_math():
    u = apply_update(0.0, signal=+1.0, lam=DEFAULT_LAMBDA, eta=DEFAULT_ETA)
    assert u == pytest.approx(DEFAULT_ETA)
    u2 = apply_update(u, signal=-1.0, lam=DEFAULT_LAMBDA, eta=DEFAULT_ETA)
    expected = (1 - DEFAULT_LAMBDA) * u - DEFAULT_ETA
    assert u2 == pytest.approx(expected)


def test_apply_update_clips_to_bounds():
    assert apply_update(0.5, signal=+10.0) == pytest.approx(CLIP_MAX)
    assert apply_update(-0.5, signal=-10.0) == pytest.approx(-CLIP_MIN)


def test_energy_terms(tmp_path):
    ledger = UtilityLedger(tmp_path)
    path = NavPath(edges=(_edge(),), semantic_depth=2)
    e0 = energy(path, query_distance=1.0, ledger=ledger)
    assert e0 == pytest.approx(1.0 + 0.15)  # D=1 + one extra hop
    ledger.record(_edge(), signal=+1.0)
    e_learned = energy(path, query_distance=1.0, ledger=ledger)
    assert e_learned < e0  # positive utility lowers E
    e_risk = energy(path, query_distance=1.0, ledger=ledger, risk_penalty=1.5)
    assert e_risk == pytest.approx(e_learned + 1.5)


def test_energy_empty_path_is_pure_distance(tmp_path):
    ledger = UtilityLedger(tmp_path)
    assert energy(NavPath(()), query_distance=0.7, ledger=ledger) == pytest.approx(0.7)


# ------------------------------------------------------------------ ledger
def test_ledger_record_and_get(tmp_path):
    ledger = UtilityLedger(tmp_path)
    row = ledger.record(_edge(), signal=+0.5)
    assert row.observations == 1
    assert row.successes == 1
    got = ledger.get(_edge())
    assert got.utility == pytest.approx(apply_update(0.0, +0.5))


def test_ledger_latest_wins_on_load(tmp_path):
    key = _edge()
    ledger = UtilityLedger(tmp_path)
    for _ in range(3):
        ledger.record(key, signal=+0.5)
    fresh = UtilityLedger(tmp_path)
    assert fresh.get(key).observations == 3
    assert fresh.get(key).utility == pytest.approx(ledger.get(key).utility)


def test_ledger_corrupt_lines_are_skipped(tmp_path):
    (tmp_path / "plasticity").mkdir(parents=True)
    (tmp_path / "plasticity" / "utility.jsonl").write_text(
        "not json\n{key: 42}\n{\"key\": [], \"utility\": \"bogus\"}\n", encoding="utf-8"
    )
    ledger = UtilityLedger(tmp_path)
    assert ledger.is_empty


def test_ledger_rebuild_replays_events_deterministically(tmp_path):
    key_a = _edge()
    key_b = _edge(source="E0003", target="E0004")
    ledger = UtilityLedger(tmp_path)
    ledger.record(key_a, signal=+0.4)
    ledger.record(key_b, signal=-0.2)
    ledger.record(key_a, signal=+0.4, evidenced=False)
    ledger.record(key_b, signal=+0.3, evidenced=True)
    rebuilt = UtilityLedger(tmp_path)
    rebuilt.utility_path.unlink(missing_ok=True)
    rows = rebuilt.rebuild()
    assert rows[key_a.to_key()].observations == 1
    assert rows[key_a.to_key()].utility == pytest.approx(apply_update(0.0, +0.4))
    assert rows[key_b.to_key()].observations == 2
    assert rows[key_b.to_key()].failures == 1
    assert rows[key_b.to_key()].successes == 1
    assert rows[key_a.to_key()].utility == pytest.approx(ledger.get(key_a).utility)
    assert rows[key_b.to_key()].utility == pytest.approx(ledger.get(key_b).utility)
    assert rows[key_a.to_key()].policy_version == ledger.policy_version
    materialized = (tmp_path / "plasticity" / "utility.jsonl").read_text(encoding="utf-8")
    assert key_a.to_key() in materialized


def test_ledger_reset_restores_baseline(tmp_path):
    ledger = UtilityLedger(tmp_path)
    row = ledger.record(_edge(), signal=+1.0, evidenced=False)
    assert row.utility == 0.0
    assert row.observations == 0
    ledger.record(_edge(), signal=+1.0)
    assert ledger.get(_edge()).observations == 1
    ledger.reset()
    assert ledger.is_empty
    assert not (tmp_path / "plasticity" / "events.jsonl").exists()
    assert not (tmp_path / "plasticity" / "utility.jsonl").exists()


def test_ledger_only_writes_under_plasticity_dir(tmp_path):
    ledger = UtilityLedger(tmp_path)
    ledger.record(_edge(), signal=+0.1)
    written = {p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file()}
    assert written == {"plasticity/events.jsonl", "plasticity/utility.jsonl"}


def test_ledger_evidenced_false_never_reinforces(tmp_path):
    ledger = UtilityLedger(tmp_path)
    row = ledger.record(_edge(), signal=-1.0, evidenced=False)
    assert row.utility == 0.0
    assert row.observations == 0


# ------------------------------------------------------------- durability
def test_ledger_append_is_crash_safe_events_are_source_of_truth(tmp_path):
    ledger = UtilityLedger(tmp_path)
    ledger.record(_edge(), signal=+0.2)
    ledger.record(_edge(), signal=-0.1)
    events = [json.loads(x) for x in
              (tmp_path / "plasticity" / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [e["reinforced"] for e in events] == [True, True]
    assert events[0]["before"] == pytest.approx(0.0)
    assert events[1]["before"] == pytest.approx(events[0]["after"])


# ----------------------------------------------------------------- config
def test_plasticity_mode_default_off():
    assert Config().plasticity_mode == "off"


def test_plasticity_mode_validation():
    assert Config(plasticity_mode="observe").plasticity_mode == "observe"
    assert Config(plasticity_mode="nonsense").plasticity_mode == "off"
    assert Config(plasticity_mode="deliver").plasticity_mode == "deliver"