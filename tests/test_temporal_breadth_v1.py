"""temporal-breadth-v1: recorded counts, verdict and invariants."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))
sys.path.insert(0, str(ROOT / "src"))

import temporal_breadth_v1 as harness  # noqa: E402


def test_recorded_counts_and_verdict():
    report = harness.collect()
    assert report["temporal_cases"] == 13
    assert report["phrase_cases"] == 6
    assert report["counts"] == {
        "delivery_loss_w1": 3, "delivery_loss_w1_non_dev": 3,
        "fixed_by_w5": 1, "fixed_by_w5_non_dev": 1,
        "w3_regressions": 1, "w5_recovers_w3": 1, "w5_regressions": 0}
    assert report["verdict"] == "recurring_class"
    assert report["gates"] == {"V1_consistent": True, "V3_w5_no_regression": True,
                               "V4_budget": True}
    assert harness.W5_SOURCE_SHA == (
        "db5021c90c3c060d3c9176755d8860a6f370b10d80a0fb66f2bd8a8fd4976cb6")


def test_case_flags_recorded():
    report = harness.collect()
    by_id = {(r["block"], r["case"]): r for r in report["rows"]}
    assert by_id[("u3a", 22)]["w5_recovers_w3"] is True
    assert by_id[("u3b", 31)]["fixed_by_w5"] is True
    assert by_id[("u3a", 17)]["delivery_loss_w1"] is True
    assert by_id[("u3b", 41)]["delivery_loss_w1"] is True
