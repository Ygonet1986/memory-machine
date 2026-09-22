"""Lifecycle v3 harness: deterministic, frozen variants, gates evaluated."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_v3_runs_deterministically_with_the_frozen_variants(tmp_path):
    result = subprocess.run(
        [sys.executable, "eval/lifecycle_retroactive_v3.py", "--out", str(tmp_path)],
        cwd=ROOT, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    report = json.loads((tmp_path / "report_v3.json").read_text(encoding="utf-8"))
    assert set(report["variants"]) == {"V3-A", "V3-B", "V3-C"}
    assert report["thresholds"] == {"coverage_idf": 0.5, "margin": 0.5,
                                    "min_token_len": 4, "top_k": 5}
    primary = report["variants"]["V3-B"]
    assert 0.0 <= primary["trigger_quality"] <= 1.0
    assert 0.0 <= primary["retroactive_precision_at_k"] <= 1.0
    assert set(report["gates"]) >= {"H3-1_trigger_quality", "H3-2_recovery",
                                    "H3-3_precision", "H3-4_combined_recall",
                                    "H3-5_selective", "H3-6_no_regression",
                                    "all_pass"}
    assert report["per_probe"]
