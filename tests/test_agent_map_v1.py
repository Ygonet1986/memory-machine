"""agent-map-v1: recorded map-routing verdicts and pointer invariant."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))
sys.path.insert(0, str(ROOT / "src"))

import agent_map_v1 as harness  # noqa: E402

OUT = ROOT / "eval" / "results" / "agent_map_v1"


def test_recorded_verdicts():
    report = json.loads((OUT / "report.json").read_text(encoding="utf-8"))
    assert report["cases"] == 27
    assert report["routing_coverage"] == {"A0": 1.0, "A1": 0.6728,
                                          "A2": 1.0, "A3": 0.7469}
    assert report["consulted_partitions"] == {"A0": 54, "A1": 27,
                                              "A2": 54, "A3": 29}
    assert report["gates"] == {"L1_no_case_lost": False,
                               "L2_fewer_activations": True,
                               "L3_vs_union": True, "L5_pointers": True,
                               "L4_determinism": True}
    assert report["all_pass"] is False
    assert "K=2 artificial partitions" in report["scope_limit"]


def test_map_pointers_present():
    report = harness.collect()
    assert report["gates"]["L5_pointers"] is True
