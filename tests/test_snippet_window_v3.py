"""snippet-window-v3: recorded verdicts and the deterministic snippet check."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))
sys.path.insert(0, str(ROOT / "src"))

import snippet_window_v3 as harness  # noqa: E402

OUT = ROOT / "eval" / "results" / "snippet_window_v3"


def test_recorded_verdicts():
    report = json.loads((OUT / "report.json").read_text(encoding="utf-8"))
    assert report["aggregates"]["S-head"]["mean_coverage"] == 0.5339
    assert report["aggregates"]["S-query"]["mean_coverage"] == 0.705
    assert report["aggregates"]["S-query"]["total_undue_mean_per_case"] < \
        report["aggregates"]["S-head"]["total_undue_mean_per_case"]
    assert report["u3a17"]["m0043_hits"] == {"S-head": 0, "S-query": 3}
    assert report["llm_calls"] == 180
    assert report["gates"] == {"H3-1_coverage": True, "H3-2_undue": True,
                               "H3-3_u3a17": True, "H3-4_infra": True}
    assert report["all_pass"] is True


def test_u3a17_snippet_precheck():
    if not (ROOT / "eval" / "graph_out"
            / "u_diag_longmemeval_u3a.jsonl").exists():
        pytest.skip("frozen snapshots not present in this checkout")
    cases = harness.v2.build_cases()
    info = harness.input_snippet_coverage(cases)
    rows = [r for r in info["rows"] if r["case"] == 17]
    by_arm = {r["arm"]: r["snippet_contains"] for r in rows}
    assert by_arm == {"S-head": 0, "S-query": 1}
