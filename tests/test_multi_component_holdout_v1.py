"""multi-component-holdout-v1: fixture design checks and recorded verdicts."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))
sys.path.insert(0, str(ROOT / "src"))

import gen_multi_component_holdout_v1 as gen  # noqa: E402

FIXTURE = ROOT / "eval" / "fixtures" / "multi_component_holdout_v1"
OUT = ROOT / "eval" / "results" / "multi_component_holdout_v1"


def test_fixture_regenerates_and_design_holds():
    payload = (FIXTURE / "cases.jsonl").read_text(encoding="utf-8")
    manifest = json.loads((FIXTURE / "manifest.json").read_text(encoding="utf-8"))
    regenerated = "".join(
        json.dumps(case, ensure_ascii=False, sort_keys=True) + "\n"
        for case in gen.build_cases())
    assert regenerated == payload
    assert hashlib.sha256(payload.encode("utf-8")).hexdigest() == \
        manifest["cases_sha256"]
    assert manifest["design_checks"]["w6c_both"] == 12
    assert manifest["design_checks"]["w4_both"] == 0
    assert manifest["design_checks"]["w1_both"] == 0


def test_recorded_verdicts():
    report = json.loads((OUT / "report.json").read_text(encoding="utf-8"))
    assert report["w4_both"] == 0 and report["w6c_both"] == 12
    assert report["answer"]["score_w4"] == 0.0
    assert report["answer"]["score_w6c"] == 3.0
    for entry in report["answer"]["cases"]:
        assert entry["arms"]["W4"] == ["incorrect"] * 3
        assert entry["arms"]["W6c"] == ["correct"] * 3
    for gate in ("M1_w6c_both", "M2_strict_advantage", "M3_answers",
                 "M4_budget", "M4_determinism", "M5_infra"):
        assert report["gates"][gate] is True, gate
    assert report["all_pass"] is True
