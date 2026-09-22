"""admission-synthetic-v4: determinism, recorded pass, single-delta invariant."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))
sys.path.insert(0, str(ROOT / "src"))

import admission_synthetic_v1 as v1  # noqa: E402
import admission_synthetic_v3 as v3  # noqa: E402
import admission_synthetic_v4 as v4  # noqa: E402

FIXTURE = ROOT / "eval" / "fixtures" / "admission_synthetic_v1"


def test_v4_deterministic_and_all_gates_pass():
    report = v4.collect(FIXTURE)
    assert v4.content_digest(report) == v4.content_digest(v4.collect(FIXTURE))
    p3v4 = report["policies"]["P3v4"]
    assert p3v4["availability"] == 1.0
    assert p3v4["precision"] == 0.7143
    assert p3v4["delivered"] == 140
    assert p3v4["max_per_case"] == 2
    assert report["removed_superseded_total"] == 30
    gates = report["gates"]
    assert gates["G1_availability"] is True
    assert gates["G2_precision"] is True
    assert gates["G7_beats_v3"] is True
    assert gates["G8_cap"] is True
    assert all(gates.values()) is True


def test_v4_equals_v3_without_an_eligible_correction():
    """The only v4 change is the correction slot: where no eligible
    correction exists, the delivered sets must be identical to v3."""
    cases = v1.load_cases(FIXTURE)
    checked = 0
    for case in cases:
        candidates = v1.candidates_for(case)
        v3_out, _ = v3.deliver_v3(case, candidates)
        v4_out, _ = v4.deliver_v4(case, candidates)
        v3_ids = [c["record"]["memory_id"] for c in v3_out]
        v4_ids = [c["record"]["memory_id"] for c in v4_out]
        eligible_correction = any(
            c["correction"] == 1.0 and c["rare"] >= 0.30
            for c in v4_out) or any(
            c["correction"] == 1.0 for c in v3_out)
        if not eligible_correction:
            assert v4_ids == v3_ids, case["case_id"]
            checked += 1
    assert checked > 0
