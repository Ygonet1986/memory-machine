"""gap-recall-v1: fixture freeze, mechanism contract and recorded verdicts."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))
sys.path.insert(0, str(ROOT / "src"))

import gen_gap_recall_v1 as gen  # noqa: E402
import gap_recall_v1 as gr  # noqa: E402

FIXTURE = ROOT / "eval" / "fixtures" / "gap_recall_v1"
OUT = ROOT / "eval" / "results" / "gap_recall_v1"


def test_fixture_regenerates_byte_identically():
    fixture = (FIXTURE / "cases.jsonl").read_text(encoding="utf-8")
    payload = "".join(json.dumps(case, ensure_ascii=False, sort_keys=True) + "\n"
                      for case in gen.build_cases())
    assert payload == fixture
    manifest = json.loads((FIXTURE / "manifest.json").read_text(encoding="utf-8"))
    digest = hashlib.sha256(fixture.encode("utf-8")).hexdigest()
    assert manifest["cases_sha256"] == digest
    assert manifest["design_checks"] == {
        "control_g0_complete": 3, "control_g1_extra_zero": 3,
        "g0_incomplete": 12, "g1_complete": 12, "g2_incomplete": 12,
        "g3_complete": 12}


def test_mechanism_contract():
    assert gr.demand("How much did the annual audit for Vega cost?") == {
        "numerals": 1, "date": 0}
    assert gr.demand("When was the launch event for Orion paid?") == {
        "numerals": 0, "date": 1}
    assert gr.demand("What did we spend on the A and the B in P?") == {
        "numerals": 2, "date": 0}
    assert gr.detect_gaps("How much did X cost?", "no money here") == [
        {"kind": "numerals", "missing": 1}]
    assert gr.detect_gaps("How much did X cost?", "it was $5") == []
    query = gr.directed_queries("When was the launch event for Orion paid?")
    assert query == ["launch event orion payment date"]


def test_recorded_verdicts():
    report = json.loads((OUT / "report.json").read_text(encoding="utf-8"))
    assert report["complete"] == {"G0": 3, "G1": 15, "G2": 3, "G3": 15}
    assert len(report["recovered"]) == 12
    assert report["budget"] == {"directed_extra_total": 12,
                                "control_triggers": 0,
                                "max_extra_per_case": 1,
                                "mean_extra_per_case": 0.8}
    assert report["gates"] == {
        "R1_no_loss": True, "R2_recovery": True, "R3_direction": True,
        "R4_budget": True, "R6_audit": True, "R5_determinism": True,
        "A1_answers": True, "A2_infra": True}
    assert report["all_pass"] is True
    assert "lab-only" in report["scope"]
    assert report["exploratory"] == {
        "money_holdout_v2": {"cases": 12, "w1_found": 4, "directed_found": 4},
        "multi_component_holdout_v1": {"cases": 12, "w1_found": 0,
                                       "directed_found": 0}}
    answer = report["answer"]
    assert answer["llm_calls"] == 36
    assert answer["failures"] == 0
    assert answer["score_g0"] == 0.1667
    assert answer["score_g1"] == 3.0
    assert answer["cases"][0]["arms"]["G0"] == ["incorrect"] * 3
    assert answer["cases"][0]["arms"]["G1"] == ["correct"] * 3
    assert answer["cases"][1]["arms"]["G0"] == ["incorrect"] * 3
    assert answer["cases"][1]["arms"]["G1"] == ["correct"] * 3
    assert answer["cases"][2]["arms"]["G0"] == ["incorrect", "incorrect",
                                                "partial"]
    assert answer["cases"][2]["arms"]["G1"] == ["correct"] * 3
