"""delivery-combined-v1: recorded delivery readings and context invariants."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))
sys.path.insert(0, str(ROOT / "src"))

import delivery_combined_v1 as harness  # noqa: E402

FIXTURE = ROOT / "eval" / "fixtures" / "composition_u4"


def test_eval_a_recorded_values_and_gates():
    cases, records = harness.load_fixture(FIXTURE)
    report = harness.eval_a(cases, records)
    summary = report["summary"]
    assert summary["W0"]["mean_all"] == 0.515
    assert summary["W1"]["mean_all"] == 0.6433
    assert summary["W3"]["mean_all"] == 0.7267
    assert summary["W3"]["mean_numeric"] == 0.6571
    assert summary["W3"]["mean_nonnumeric"] == summary["W1"]["mean_nonnumeric"]
    for gate in ("A1_mean", "A2_numeric", "A3_nonnumeric_identical", "A4_budget"):
        assert report["gates"][gate] is True, gate


def test_non_numeric_w3_context_equals_w1():
    cases, records = harness.load_fixture(FIXTURE)
    for case in cases:
        if harness.da.NUM_CUE_RE.search(case["question"]):
            continue
        ctx = harness.contexts(case, records)
        assert ctx["W3"] == ctx["W1"], case["case"]


def test_recorded_eval_b_verdicts():
    import json
    report = json.loads((ROOT / "eval" / "results" / "delivery_combined_v1"
                         / "report.json").read_text(encoding="utf-8"))
    b = report["evaluation_b"]
    assert b["summary"]["W3"]["score"] == 0.6167
    assert b["summary"]["W1"]["score"] == 0.5833
    assert b["summary"]["W0"]["score"] == 0.3833
    assert b["gates"]["B1_beats_W0"] is True
    assert b["gates"]["B4_downgrades"] is False  # recorded failure, not re-fit
    assert b["calls"]["llm_calls"] == 180
    assert b["inconclusive_infrastructure"] is False
