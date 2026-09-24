"""companion-eval-v1: fixture hash and the recorded single-run verdicts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "eval" / "fixtures" / "companion_eval_v1"
OUT = ROOT / "eval" / "results" / "companion_eval_v1"


def test_fixture_hash_matches_manifest():
    text = (FIXTURE / "script.json").read_text(encoding="utf-8")
    manifest = json.loads((FIXTURE / "manifest.json").read_text(encoding="utf-8"))
    assert hashlib.sha256(text.encode("utf-8")).hexdigest() == \
        manifest["script_sha256"]


def test_recorded_verdicts():
    report = json.loads((OUT / "report.json").read_text(encoding="utf-8"))
    assert report["all_pass"] is False
    assert report["total_calls"] == 48
    assert report["cost"] == {"A": 18, "B": 30}
    assert report["setup"] == {"t1_report": True, "t2_story": False}
    assert report["structural_isolation"] is False
    assert report["gates"] == {
        "G1_fiction": True, "G2_draft": False, "G3_correction": True,
        "G4_retirement": True, "G5_deletion": True, "G6_isolation": False,
        "G7_no_invention": False, "G8_switch": True, "G9_budget": True,
        "G10_setup": False,
    }
    judged = report["judged"]
    assert judged["p1"]["B"]["answer"] == "yes"
    assert judged["p5"]["B"] == {"answer": "yes", "fiction_as_real": False,
                                 "unsupported_claims": False}
    assert judged["p7"]["B"]["answer"] == "no"
    assert judged["p7"]["A"]["answer"] == "yes"
    rows = {row["id"]: row for row in report["rows"]}
    assert rows["p3"]["checks"]["forbid:piano"] is False
    assert rows["p6"]["checks"]["forbid:Mestre Bento"] is True
    assert rows["p9"]["checks"]["contain:Tomás"] is True
    assert rows["del1"]["removed"]
    assert {"M0025", "M0028"} <= set(rows["del1"]["removed"])
