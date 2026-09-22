"""phrase-coverage-v1: recorded verdicts and the room<0 root cause."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))
sys.path.insert(0, str(ROOT / "src"))

import delivery_combined_v1 as dc  # noqa: E402
import phrase_coverage_v1 as harness  # noqa: E402

OUT = ROOT / "eval" / "results" / "phrase_coverage_v1"


def test_delivery_stage_recorded():
    report = harness.collect(skip_llm=True)

    def row(case: int, arm: str):
        return next(r for r in report["rows"]
                    if r["case"] == case and r["arm"] == arm)

    assert not row(17, "W5")["ok"] and not row(17, "W6")["ok"]
    assert row(19, "W6")["ok"] and not row(19, "W5")["ok"]
    for case in (12, 22, 27):
        assert row(case, "W6")["ok"] == row(case, "W5")["ok"]
    assert report["gates"]["P1_target_fixed"] is False
    assert report["gates"]["P2_no_removals"] is True
    assert report["w5_unchanged"] is True


def test_u3a17_item_never_windows_because_room_negative():
    from fact_presence import item_span

    cases, records = dc.load_fixture(ROOT / "eval" / "fixtures" / "composition_u4")
    case = next(c for c in cases if (c["block"], c["case"]) == ("u3a", 17))
    record = records[(17, "M0043")]
    span_w0, _ = item_span(case["context"], "M0043")
    body_start = span_w0.find("\n")
    frozen_body = span_w0[body_start + 1:]
    room = len(frozen_body) - len(record["summary"]) - 1
    assert room < 120  # guard skips every window for this item
    spans = {arm: item_span(harness.rebuild(case, records, arm), "M0043")[0]
             for arm in ("W5", "W6")}
    assert spans["W5"] == spans["W6"] == span_w0


def test_recorded_answer_verdicts():
    report = json.loads((OUT / "report.json").read_text(encoding="utf-8"))
    assert report["answer"]["arms"]["W5"] == ["incorrect"] * 3
    assert report["answer"]["arms"]["W6"] == ["incorrect"] * 3
    assert report["answer"]["llm_calls"] == 12
    assert report["all_pass"] is False
