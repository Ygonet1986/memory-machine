"""Two-tier retrieval v2: determinism, frozen thresholds and recorded verdict."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))
sys.path.insert(0, str(ROOT / "src"))

import two_tier_retrieval_v2 as t2v2  # noqa: E402


def test_two_tier_v2_is_deterministic_and_frozen():
    report = t2v2.collect(t2v2.DEFAULT_FIXTURE, t2v2.DEFAULT_PROJECTION)
    assert set(report["arms"]) == set(t2v2.ARMS)
    assert report["thresholds"] == {"top_k": 5, "margin_primary": 0.9,
                                    "margin_variant": 0.7}
    assert report["probes_used"] == 19
    assert report["required_occurrences"] == 21
    again = t2v2.collect(t2v2.DEFAULT_FIXTURE, t2v2.DEFAULT_PROJECTION)
    import two_tier_retrieval_v1 as v1
    assert v1.content_digest(report) == v1.content_digest(again)
    assert report["arms"]["T2v2-P"]["availability"] == 0.9048
    assert report["arms"]["T2v2-P"]["precision_at_k"] == 0.8261
    assert report["arms"]["T2v2-B2"]["availability"] == 0.9524
    assert report["gates"]["H6-1_availability"] is False
    assert report["gates"]["H6-2_precision"] is True
    assert report["gates"]["H6-3_budget"] is True
    assert report["gates"]["H6-4_no_regression_vs_unfiltered"] is True
    assert all(report["gates"].values()) is False
