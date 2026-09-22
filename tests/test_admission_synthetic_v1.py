"""admission-synthetic-v1: frozen generator, fixture and recorded verdicts."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))
sys.path.insert(0, str(ROOT / "src"))

import admission_synthetic_v1 as harness  # noqa: E402
import gen_admission_synthetic_v1 as gen  # noqa: E402
import validate_admission_synthetic_v1 as validator  # noqa: E402

FIXTURE = ROOT / "eval" / "fixtures" / "admission_synthetic_v1"


def test_fixture_is_frozen_and_valid():
    assert validator.validate(FIXTURE) == []
    payload = (FIXTURE / "cases.jsonl").read_text(encoding="utf-8")
    regenerated = "".join(
        __import__("json").dumps(case, ensure_ascii=False, sort_keys=True) + "\n"
        for case in gen.build_cases())
    assert regenerated == payload


def test_scenario_coverage_and_gold_shape():
    cases = harness.load_cases(FIXTURE)
    assert len(cases) == 100
    counts = {}
    for case in cases:
        counts[case["scenario"]] = counts.get(case["scenario"], 0) + 1
    assert counts == {scenario: 10 for scenario in gen.SCENARIOS}
    multi = [case for case in cases if case["scenario"] == "multi_memory"]
    assert all(len(case["gold"]) == 2 for case in multi)
    abstain = [case for case in cases if case["expectation"] == "abstain"]
    assert len(abstain) == 10 and all(not case["gold"] for case in abstain)


def test_harness_deterministic_and_recorded_gates():
    report = harness.collect(FIXTURE)
    assert harness.content_digest(report) == harness.content_digest(
        harness.collect(FIXTURE))
    results = report["policies"]
    assert results["P3"]["availability"] == 0.7
    assert results["P3"]["precision"] == 0.5
    assert results["P1"]["availability"] == 0.9
    assert results["P2"]["availability"] == 0.6
    assert report["gates"]["G3_dual_frontier"] is True
    assert report["gates"]["G4_abstention"] is True
    assert report["gates"]["G1_availability"] is False
    assert all(report["gates"].values()) is False
