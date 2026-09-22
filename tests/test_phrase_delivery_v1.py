"""phrase-delivery-v1: recorded metric verdicts and invariants."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))
sys.path.insert(0, str(ROOT / "src"))

import phrase_delivery_v1 as harness  # noqa: E402


def test_phrase_metric_recorded_verdicts():
    report = harness.collect()

    def row(case: int, arm: str):
        return next(r for r in report["rows"]
                    if r["case"] == case and r["arm"] == arm)

    assert row(22, "W0")["ok"] and row(22, "W1")["ok"]
    assert not row(22, "W3")["ok"]
    assert row(22, "W3")["gold_phrases"] == ["2week"]
    assert not row(19, "W0")["ok"]
    assert row(12, "W0")["ok"] and row(12, "W3")["ok"]
    assert row(27, "W0")["basis"] == "atom_fallback"
    assert report["gates"] == {"P1_detects_u3a22": True, "P2_controls": True,
                               "P3_locates_u3a19": True, "P4_hashes": True}


def test_phrase_helpers():
    assert ("2", "week") in harness.phrases("about two weeks later")
    assert ("16", "gb") in harness.phrases("upgrade to 16GB")
    assert ("200", "$") in harness.phrases("spent about $200 total")
    assert harness.phrase_present(("2", "week"), "two weeks passed")
    assert not harness.phrase_present(("2", "week"), "two months passed")
