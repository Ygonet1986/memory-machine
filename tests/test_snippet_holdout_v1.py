"""snippet-holdout-v1: fixture invariants and recorded holdout verdicts."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))
sys.path.insert(0, str(ROOT / "src"))

import gen_snippet_holdout_v1 as gen  # noqa: E402
from memory_machine.payload import fact_window  # noqa: E402

FIXTURE = ROOT / "eval" / "fixtures" / "snippet_holdout_v1"
OUT = ROOT / "eval" / "results" / "snippet_holdout_v1"


def test_fixture_regenerates_and_burial_invariants():
    payload = (FIXTURE / "cases.jsonl").read_text(encoding="utf-8")
    manifest = json.loads((FIXTURE / "manifest.json").read_text(encoding="utf-8"))
    regenerated = "".join(
        json.dumps(case, ensure_ascii=False, sort_keys=True) + "\n"
        for case in gen.build_cases())
    assert regenerated == payload
    assert hashlib.sha256(payload.encode("utf-8")).hexdigest() == \
        manifest["cases_sha256"]
    for case in gen.build_cases():
        record = case["records"][0]
        text = f"{record['summary']} {record['why']}".strip()
        assert case["gold"].lower() not in text[:400].lower()
        assert case["gold"].lower() in fact_window(
            text, case["question"], 400).lower()


def test_recorded_holdout_verdicts():
    report = json.loads((OUT / "report.json").read_text(encoding="utf-8"))
    assert report["aggregates"]["S-head"]["mean_coverage"] == 0.0278
    assert report["aggregates"]["S-query"]["mean_coverage"] == 1.0
    assert report["aggregates"]["S-query"]["total_undue_mean_per_case"] == 0.0
    assert report["recovered_cases_s_query"] == 12
    assert report["llm_calls"] == 72
    for gate in ("X1_coverage", "X2_generalization", "X3_undue", "X4_infra"):
        assert report["gates"][gate] is True, gate
    assert report["all_pass"] is True
