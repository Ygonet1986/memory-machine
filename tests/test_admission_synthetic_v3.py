"""admission-synthetic-v3: determinism, captured verdicts, only two deltas."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))
sys.path.insert(0, str(ROOT / "src"))

import admission_synthetic_v1 as v1  # noqa: E402
import admission_synthetic_v2 as v2  # noqa: E402
import admission_synthetic_v3 as v3  # noqa: E402

FIXTURE = ROOT / "eval" / "fixtures" / "admission_synthetic_v1"


def test_v3_deterministic_and_recorded_verdicts():
    report = v3.collect(FIXTURE)
    assert v3.content_digest(report) == v3.content_digest(v3.collect(FIXTURE))
    p3v3 = report["policies"]["P3v3"]
    assert p3v3["availability"] == 0.9
    assert p3v3["precision"] == 0.6429
    assert p3v3["delivered"] == 140
    assert p3v3["max_per_case"] == 2
    assert report["removed_superseded_total"] == 30
    gates = report["gates"]
    assert gates["G1_availability"] is True
    assert gates["G2_precision"] is False
    assert gates["G5_scenario_floor"] is False
    assert gates["G7_beats_v2"] is False
    assert gates["G8_cap"] is True
    assert all(gates.values()) is False


def test_v3_differs_from_v2_only_by_removal_and_cap():
    """On cases without supersession and with <= 2 qualifying candidates the
    two rules must deliver exactly the same set."""
    cases = v1.load_cases(FIXTURE)
    for case in cases:
        candidates = v1.candidates_for(case)
        v2_out = [c["record"]["memory_id"] for c in v2.deliver_v2(case, candidates)]
        v3_out, removed = v3.deliver_v3(case, candidates)
        v3_ids = [c["record"]["memory_id"] for c in v3_out]
        if removed == 0 and len(v2_out) <= 2:
            assert v3_ids == v2_out, case["case_id"]
        assert len(v3_ids) <= 2
