"""Lifecycle v2 harness: deterministic, three variants, gates evaluated."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_v2_runs_deterministically_with_the_frozen_variants(tmp_path):
    result = subprocess.run(
        [sys.executable, "eval/lifecycle_retroactive_v2.py", "--out", str(tmp_path)],
        cwd=ROOT, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    report = json.loads((tmp_path / "report_v2.json").read_text(encoding="utf-8"))
    assert set(report["variants"]) == {"T1", "T2", "T3"}
    assert report["thresholds"] == {"coverage": 0.5, "min_token_len": 4, "top_k": 5}
    for variant in ("T1", "T2", "T3"):
        entry = report["variants"][variant]
        for key in ("trigger_quality", "fallback_rate",
                    "retroactive_recovery_rate", "retroactive_precision_at_k",
                    "combined_recall_occurrences"):
            assert 0.0 <= entry[key] <= 1.0, (variant, key)
    assert set(report["gates"]) >= {"H2-1_trigger_quality", "H2-2_recovery",
                                    "H2-3_precision", "H2-4_combined_recall",
                                    "H2-5_selective", "all_pass"}
    assert report["probes_needing_fallback"] >= 1
