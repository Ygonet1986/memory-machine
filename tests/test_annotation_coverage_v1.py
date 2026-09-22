"""annotation-coverage-v1: recorded aggregate coverage and u3a-17 row."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))
sys.path.insert(0, str(ROOT / "src"))

import annotation_coverage_v1 as harness  # noqa: E402

OUT = ROOT / "eval" / "results" / "annotation_coverage_v1"


def test_recorded_aggregate():
    report = json.loads((OUT / "report.json").read_text(encoding="utf-8"))
    agg = report["aggregate"]
    assert agg["required_total"] == 62
    assert agg["coverage_A"] == 0.8226
    assert agg["coverage_L5"] == 0.9355
    assert agg["coverage_U5"] == 0.9839
    assert agg["missing_total"] == 11
    assert agg["missing_covered_by_L5"] == 10
    assert agg["undue_proxy"] == 14
    assert report["gates"] == {"A1_processed": True, "A3_u3a17_visible": True,
                               "A2_determinism": True}
    assert report["all_pass"] is True


def test_u3a17_row():
    report = json.loads((OUT / "report.json").read_text(encoding="utf-8"))
    row = next(e for e in report["per_case"]
               if e["block"] == "u3a" and e["case"] == 17)
    assert row["coverage"]["A"] == 0.0
    assert row["coverage"]["L5"] == 1.0
    assert row["missing"] == ["M0043"]
    assert row["missing_covered_by_L5"] == ["M0043"]


def test_recompute_when_snapshots_present():
    if not (ROOT / "eval" / "graph_out"
            / "u_diag_longmemeval_u3a.jsonl").exists():
        pytest.skip("frozen snapshots not present in this checkout")
    report = harness.collect()
    assert report["aggregate"]["coverage_U5"] == 0.9839
    assert all(report["gates"].values())
