"""numeral-inclusion-v1: recorded delivery and answer verdicts."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))
sys.path.insert(0, str(ROOT / "src"))

import numeral_inclusion_v1 as harness  # noqa: E402

OUT = ROOT / "eval" / "results" / "numeral_inclusion_v1"


def test_delivery_stage_recorded():
    report, _meta = harness.collect(skip_llm=True)

    def row(case: int, arm: str):
        return next(r for r in report["rows"]
                    if r["case"] == case and r["arm"] == arm)

    assert not row(19, "W3")["ok"]
    assert row(19, "W4")["ok"]
    assert row(12, "W4")["ok"] and row(27, "W4")["ok"]
    assert row(22, "W3")["ok"] == row(22, "W4")["ok"] is False


def test_recorded_answer_verdicts():
    report = json.loads((OUT / "report.json").read_text(encoding="utf-8"))
    cases = {entry["case"]: entry for entry in report["answer"]["cases"]}
    assert cases[19]["arms"]["W3"] == ["incorrect", "partial", "incorrect"]
    assert cases[19]["arms"]["W4"] == ["correct", "correct", "incorrect"]
    assert cases[22]["arms"]["W3"] == ["incorrect"] * 3
    assert cases[22]["arms"]["W4"] == ["incorrect"] * 3
    assert report["answer"]["llm_calls"] == 24
    for gate in ("N1_fixes_u3a19", "N2_no_new_regressions", "N3_answers",
                 "N4_determinism", "N5_infra"):
        assert report["gates"][gate] is True, gate
    assert report["all_pass"] is True
