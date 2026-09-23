"""agent-map-v2: recorded stopping-rule verdicts and scope limit."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))
sys.path.insert(0, str(ROOT / "src"))

OUT = ROOT / "eval" / "results" / "agent_map_v2"


def test_recorded_verdicts():
    report = json.loads((OUT / "report.json").read_text(encoding="utf-8"))
    assert report["cases"] == 27
    assert report["routing_coverage"] == {"B0": 1.0, "B1": 0.6728, "B2": 1.0,
                                          "B3": 0.8519, "B4": 0.7469}
    assert report["consulted_partitions"] == {"B0": 54, "B1": 27, "B2": 54,
                                              "B3": 39, "B4": 29}
    assert report["gates"] == {"M1_no_case_lost": True, "M2_economy": False,
                               "M5_pointers": True, "M4_determinism": True}
    assert report["all_pass"] is False
    assert "K=2 artificial partitions" in report["scope_limit"]
