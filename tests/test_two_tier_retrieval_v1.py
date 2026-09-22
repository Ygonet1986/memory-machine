"""Two-tier retrieval v1: determinism, frozen thresholds and recorded verdict."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))
sys.path.insert(0, str(ROOT / "src"))

import two_tier_retrieval_v1 as t2  # noqa: E402


def test_two_tier_v1_is_deterministic_and_frozen():
    report = t2.collect(t2.DEFAULT_FIXTURE, t2.DEFAULT_PROJECTION)
    assert set(report["arms"]) == set(t2.ARMS)
    assert report["thresholds"] == {"top_k": 5, "margin": 0.5, "rrf_k": 60,
                                    "coverage_idf": 0.5,
                                    "comparative_factor": 1.25,
                                    "min_token_len": 4}
    assert report["probes_used"] == 19
    assert report["required_occurrences"] == 21
    again = t2.collect(t2.DEFAULT_FIXTURE, t2.DEFAULT_PROJECTION)
    assert t2.content_digest(report) == t2.content_digest(again)
    assert report["arms"]["T2-C"]["availability"] == 1.0
    assert (report["arms"]["T2-B"]["availability"]
            == report["v4_reference"]["T2-B_combined_recall"])
    assert report["gates"]["H2T-1_availability"] is True
    assert report["gates"]["H2T-2_precision"] is False
    assert report["gates"]["H2T-3_budget"] is True
    assert report["gates"]["H2T-4_no_regression_vs_unfiltered"] is True
    assert report["gates"]["H2T-5_determinism"] is True
    assert report["gates"]["all_pass"] is False
