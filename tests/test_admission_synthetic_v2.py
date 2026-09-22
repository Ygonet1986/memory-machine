"""admission-synthetic-v2: determinism, frozen verdicts and scenario wins."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))
sys.path.insert(0, str(ROOT / "src"))

import admission_synthetic_v2 as harness  # noqa: E402

FIXTURE = ROOT / "eval" / "fixtures" / "admission_synthetic_v1"


def test_v2_deterministic_and_recorded_verdicts():
    report = harness.collect(FIXTURE)
    assert harness.content_digest(report) == harness.content_digest(
        harness.collect(FIXTURE))
    policies = report["policies"]
    assert policies["P3v2"]["availability"] == 1.0
    assert policies["P3v2"]["precision"] == 0.4545
    assert policies["P3v1"]["availability"] == 0.7
    gates = report["gates"]
    assert gates["G1_availability"] is True
    assert gates["G2_precision"] is False
    assert gates["G3_dual_frontier"] is True
    assert gates["G4_abstention"] is True
    assert gates["G5_scenario_floor"] is True
    assert gates["G7_beats_v1"] is False
    assert all(gates.values()) is False


def test_v2_fixes_the_three_named_scenarios():
    report = harness.collect(FIXTURE)
    for scenario in ("corrected", "near_duplicate", "multi_memory"):
        assert report["policies"]["P3v2"]["scenario_availability"][scenario] == 1.0
        assert report["policies"]["P3v1"]["scenario_availability"][scenario] < 1.0
