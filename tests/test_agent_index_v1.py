"""agent-index-v1: recorded routing/answer verdicts and the scope limit."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))
sys.path.insert(0, str(ROOT / "src"))

FIXTURE = ROOT / "eval" / "fixtures" / "agent_index_v1"
OUT = ROOT / "eval" / "results" / "agent_index_v1"


def test_fixture_counts_locked():
    manifest = json.loads((FIXTURE / "manifest.json").read_text(encoding="utf-8"))
    payload = (FIXTURE / "cases.jsonl").read_text(encoding="utf-8")
    assert hashlib.sha256(payload.encode("utf-8")).hexdigest() == \
        manifest["cases_sha256"]
    assert manifest["cases"] == 27
    assert manifest["a1_miss_cases"] == 20
    assert manifest["a2_recover_cases"] == 27


def test_recorded_verdicts_and_scope_limit():
    report = json.loads((OUT / "report.json").read_text(encoding="utf-8"))
    assert report["routing_coverage"] == {"A0": 1.0, "A1": 0.5321, "A2": 1.0}
    assert report["consulted_partitions"] == {"A0": 54, "A1": 27, "A2": 54}
    assert report["answer"]["scores"]["A2"] == 0.125
    assert report["answer"]["llm_calls"] == 72
    assert report["gates"]["G3_fewer_calls"] is False
    assert report["all_pass"] is False
    assert "no real-tape call savings" in report["scope_limit"]
