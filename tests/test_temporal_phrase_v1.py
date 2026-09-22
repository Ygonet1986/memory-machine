"""temporal-phrase-v1: recorded correction verdicts and invariants."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))
sys.path.insert(0, str(ROOT / "src"))

import temporal_phrase_v1 as harness  # noqa: E402

OUT = ROOT / "eval" / "results" / "temporal_phrase_v1"


def test_delivery_stage_recorded():
    report = harness.collect(skip_llm=True)

    def row(case: int, arm: str):
        return next(r for r in report["rows"]
                    if r["case"] == case and r["arm"] == arm)

    assert row(22, "W1")["ok"] and row(22, "W5")["ok"]
    assert not row(22, "W3")["ok"]
    for case in (12, 19, 27):
        assert row(case, "W5")["ok"] == row(case, "W3")["ok"]
    assert report["gates"]["T1_fixes_u3a22"] is True
    assert report["gates"]["T2_no_new_regressions"] is True


def test_recorded_answer_verdicts():
    report = json.loads((OUT / "report.json").read_text(encoding="utf-8"))
    assert report["answer"]["arms"]["W1"] == ["correct"] * 3
    assert report["answer"]["arms"]["W3"] == ["incorrect"] * 3
    assert report["answer"]["arms"]["W5"] == ["correct"] * 3
    assert report["answer"]["llm_calls"] == 18
    for gate in ("T1_fixes_u3a22", "T2_no_new_regressions", "T3_answers",
                 "T4_determinism", "T5_infra"):
        assert report["gates"][gate] is True, gate
    assert report["all_pass"] is True


def test_temporal_phrase_detector():
    assert harness.temporal_phrases("I spent two weeks traveling")
    assert harness.temporal_phrases("about 3 days later")
    assert not harness.temporal_phrases("a quick note about pricing")
