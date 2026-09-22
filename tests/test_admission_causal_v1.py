"""admission-causal-v1 lab: frozen fixture, determinism, recorded mechanism."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))
sys.path.insert(0, str(ROOT / "src"))

import admission_causal_v1 as harness  # noqa: E402
import gen_admission_causal_v1 as gen  # noqa: E402

FIXTURE = ROOT / "eval" / "fixtures" / "admission_causal_v1"


def test_fixture_regenerates_byte_identically():
    import hashlib
    payload = (FIXTURE / "cases.jsonl").read_text(encoding="utf-8")
    manifest = json.loads((FIXTURE / "manifest.json").read_text(encoding="utf-8"))
    regenerated = "".join(
        json.dumps(case, ensure_ascii=False, sort_keys=True) + "\n"
        for case in gen.build_cases())
    assert regenerated == payload
    assert hashlib.sha256(payload.encode("utf-8")).hexdigest() == manifest["cases_sha256"]


def test_harness_deterministic_and_recorded_verdicts():
    report = harness.collect(FIXTURE)
    assert harness.content_digest(report) == harness.content_digest(
        harness.collect(FIXTURE))
    for policy in ("B", "K", "K-abl"):
        assert report["policies"][policy]["availability"] == 0.6667
        assert report["policies"][policy]["precision"] == 0.8
    assert report["gates"]["G1_availability"] is False
    assert report["gates"]["G3_causal_wins"] is False
    assert report["gates"]["G5_negatives"] is True
    assert all(report["gates"].values()) is False


def test_expansion_adds_rationale_but_relative_floor_rejects_it():
    """Lock the recorded mechanism: R08 enters the pool, gain < floor."""
    cases = harness.load_cases(FIXTURE)
    case = next(c for c in cases if c["case_id"] == "C1-01")
    records = harness._wrap(case["records"])
    lexical = harness._lexical_candidates(case["question"], records)
    pool = harness.expanded_pool(case["question"], case, records, lexical)
    assert "C1-01-R08" in {candidate.memory_id for candidate in pool}
    assert "C1-01-R08" in case["gold"]
    from memory_machine import admission_p3v4 as p3v4
    p3v4.decide(case["question"], pool, records)
    assert "C1-01-R08" not in p3v4.delivered_ids(pool)
    rationale = next(c for c in pool if c.memory_id == "C1-01-R08")
    best_gain = max(c.gain for c in pool)
    assert rationale.gain < 0.60 * best_gain
