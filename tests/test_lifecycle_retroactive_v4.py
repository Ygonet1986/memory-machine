"""Lifecycle v4 harness: deterministic, frozen variants and thresholds."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_v4_runs_deterministically_with_the_frozen_variants(tmp_path):
    result = subprocess.run(
        [sys.executable, "eval/lifecycle_retroactive_v4.py", "--out", str(tmp_path)],
        cwd=ROOT, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    report = json.loads((tmp_path / "report_v4.json").read_text(encoding="utf-8"))
    assert set(report["variants"]) == {"V4-A", "V4-B", "V4-C"}
    assert report["thresholds"]["comparative_factor"] == 1.25
    assert report["thresholds"]["margin"] == 0.5
    diagnostics = report["comparative_diagnostics"]
    assert set(diagnostics) == {"comparative_fires", "extra_triggers_vs_v3",
                                "extra_recovered", "extra_irrelevant"}
    assert set(report["gates"]) >= {"H4-1_trigger_quality", "H4-2_recovery",
                                    "H4-3_precision", "H4-4_combined_recall",
                                    "H4-5_selective", "H4-6_no_regression",
                                    "all_pass"}
    assert report["per_probe"]
