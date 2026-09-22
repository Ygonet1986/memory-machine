"""Lifecycle A/B/D harness: runs end-to-end, deterministically, structurally.

Does not pin fixture numbers (those follow the pre-registration); guards the
report contract: three arms, the frozen metric names, temporal per-probe
evaluation, and an identical rebuild.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_report_runs_and_keeps_the_frozen_contract(tmp_path):
    result = subprocess.run(
        [sys.executable, "eval/lifecycle_shadow.py", "--out", str(tmp_path)],
        cwd=ROOT, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert report["rebuild_identical"] is True
    for arm in ("A", "B", "D"):
        entry = report["arms"][arm]
        metrics = entry["global_memory_metrics"]
        for key in ("promotion_precision", "promotion_recall",
                    "false_discard_rate", "active_set_reduction_received"):
            assert key in entry or key in metrics, (arm, key)
        assert entry["per_probe"]["per_probe"], arm  # probes evaluated
    probes = report["arms"]["B"]["per_probe"]["per_probe"]
    assert any(p.get("skipped") == "unrecoverable_due_to_ingestion" for p in probes)
    assert (tmp_path / "projection" / "lifecycle" / "decisions.jsonl").exists()
    assert (tmp_path / "projection" / "lifecycle" / "manifest.json").exists()
