"""selection-probe-v1: recorded counts and u3a-17 reference row."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))
sys.path.insert(0, str(ROOT / "src"))

import selection_probe_v1 as harness  # noqa: E402

OUT = ROOT / "eval" / "results" / "selection_probe_v1"


def test_recorded_counts():
    report = json.loads((OUT / "report.json").read_text(encoding="utf-8"))
    assert report["snapshot_rows"] == 30
    assert len(report["affected_cases"]) == 8
    assert report["counts"] == {"missing_records": 11,
                                "lexically_retrievable_miss": 10,
                                "lexical_gap": 1,
                                "view_disjoint": 0}
    assert report["gates"] == {"S1_classified": True, "S3_u3a17_visible": True}
    assert report["all_pass"] is True


def test_u3a17_reference_row():
    report = json.loads((OUT / "report.json").read_text(encoding="utf-8"))
    row = next(r for r in report["missing_records"]
               if r["block"] == "u3a" and r["case"] == 17
               and r["memory_id"] == "M0043")
    assert row["lexical_rank"] == 1
    assert row["lexical_overlap"] == 0.8
    assert row["view_overlap"] is True
    assert row["classification"] == "lexically_retrievable_miss"


def test_recompute_when_snapshots_present():
    if not (ROOT / "eval" / "graph_out"
            / "u_diag_longmemeval_u3a.jsonl").exists():
        pytest.skip("frozen snapshots not present in this checkout")
    report = harness.collect()
    assert report["counts"]["lexically_retrievable_miss"] == 10
    assert all(report["gates"].values())
