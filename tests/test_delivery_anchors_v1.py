"""delivery-anchors-v1: frozen fixture mechanics and recorded verdicts."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))
sys.path.insert(0, str(ROOT / "src"))

import delivery_anchors_v1 as harness  # noqa: E402

FIXTURE = ROOT / "eval" / "fixtures" / "composition_u4"


def test_deterministic_and_recorded_verdicts():
    report = harness.collect(FIXTURE)
    assert harness.content_digest(report) == harness.content_digest(
        harness.collect(FIXTURE))
    policies = report["policies"]
    assert policies["W0"]["all_present_cases"] == 14
    assert policies["W1"]["all_present_cases"] == 17
    assert policies["W2"]["all_present_cases"] == 17
    assert policies["W1"]["mean_presence"] == 0.6433
    assert policies["W2"]["mean_presence_numeric"] == 0.6571
    gates = report["gates"]
    assert gates["D1_no_regression"] is True
    assert gates["D2_numeric_mean"] is True
    assert gates["D4_numeric_repairs"] is True
    assert gates["D5_nonnumeric_unchanged"] is True
    assert gates["D6_budget"] is True
    assert gates["D7_determinism"] is True
    assert gates["D3_case0_anchor"] is False  # not reproducible at this layer


def test_case0_anchor_present_in_all_arms():
    report = harness.collect(FIXTURE)
    for policy in ("W0", "W1", "W2"):
        assert report["case0"]["policies"][policy]["presence"] == 1.0
