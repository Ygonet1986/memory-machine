"""component-allocation-v1: recorded delivery fix and gates."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))
sys.path.insert(0, str(ROOT / "src"))


OUT = ROOT / "eval" / "results" / "component_allocation_v1"


def test_recorded_components_and_gates():
    report = json.loads((OUT / "report.json").read_text(encoding="utf-8"))
    assert report["u3a24_components"] == {
        "W4": {"1000": True, "300": False},
        "W6c": {"1000": True, "300": True}}
    assert report["holdout_hits"] == {"W4": 12, "W6c": 12}
    assert report["answer"]["arms"]["W6c"] == ["correct"] * 3
    gates = report["gates"]
    for gate in ("Z1_dev_both_components", "Z2_holdout_no_regression",
                 "Z3_budget", "Z3_determinism", "Z4_answers", "Z5_infra"):
        assert gates[gate] is True, gate
    assert report["all_pass"] is True
    assert report["w4_unchanged"] is True
