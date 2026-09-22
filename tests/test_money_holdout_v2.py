"""money-holdout-v2: fixture design invariants and recorded verdicts."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))
sys.path.insert(0, str(ROOT / "src"))

import gen_money_holdout_v2 as gen  # noqa: E402

FIXTURE = ROOT / "eval" / "fixtures" / "money_holdout_v2"
OUT = ROOT / "eval" / "results" / "money_holdout_v2"


def test_fixture_regenerates_and_design_holds():
    payload = (FIXTURE / "cases.jsonl").read_text(encoding="utf-8")
    manifest = json.loads((FIXTURE / "manifest.json").read_text(encoding="utf-8"))
    regenerated = "".join(
        json.dumps(case, ensure_ascii=False, sort_keys=True) + "\n"
        for case in gen.build_cases())
    assert regenerated == payload
    assert hashlib.sha256(payload.encode("utf-8")).hexdigest() == \
        manifest["cases_sha256"]
    assert manifest["design_checks"] == {"w4_contains_target": 12,
                                         "w1_contains_target": 4}


def test_recorded_verdicts():
    report = json.loads((OUT / "report.json").read_text(encoding="utf-8"))
    assert report["w1_hits"] == 4 and report["w4_hits"] == 12
    assert report["external_u3a24"] == {
        "W1": {"1000": False, "300": False},
        "W4": {"1000": True, "300": False}}
    assert report["answer"]["cases"][1]["arms"]["W1"] == ["incorrect"] * 3
    assert report["answer"]["cases"][1]["arms"]["W4"] == ["correct"] * 3
    assert report["gates"] == {"Y1_w4_full": True, "Y2_beats_w1": True,
                               "Y3_components": False, "Y4_budget": True,
                               "Y4_determinism": True, "Y5_answers": True,
                               "Y6_infra": True}
    assert report["all_pass"] is False
