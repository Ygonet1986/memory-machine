"""companion-demo-v1: fixture hash and the recorded single-run verdicts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "eval" / "fixtures" / "companion_demo_v1"
OUT = ROOT / "eval" / "results" / "companion_demo_v1"


def test_fixture_hash_matches_manifest():
    text = (FIXTURE / "script.json").read_text(encoding="utf-8")
    manifest = json.loads((FIXTURE / "manifest.json").read_text(encoding="utf-8"))
    assert hashlib.sha256(text.encode("utf-8")).hexdigest() == manifest["script_sha256"]


def test_recorded_verdicts():
    report = json.loads((OUT / "report.json").read_text(encoding="utf-8"))
    assert report["all_pass"] is False
    assert report["total_calls"] == 18
    assert report["budget_calls"] == 40
    assert report["gates"] == {
        "G1_fiction": True, "G2_deletion": False, "G3_correction": False,
        "G4_isolation": False, "G5_trailer": True, "G6_budget": True,
        "G7_extraction": False,
    }
    rows = {row["id"]: row for row in report["rows"]}
    assert rows["t1"]["checks"]["record_types"] == ["person_report"]
    assert rows["t6"]["checks"]["record_types"] == []
    assert rows["t5"]["checks"]["contain:mãe"] is True
    assert rows["t5"]["checks"]["forbid:irmã"] is False
    assert rows["t8"]["checks"]["forbid:mãe"] is False
    correction = rows["c1"]["checks"]
    assert correction["old_status"] == "superseded"
    assert correction["new_status"] == "active"
    assert rows["d1"]["checks"]["removed"] == ["M0016"]
    assert rows["i1"]["checks"]["structural"] is True
    assert rows["i1"]["checks"]["forbid:astronomia"] is False
