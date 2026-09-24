"""companion-eval-v2: fixture hash and the recorded single-run verdicts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "eval" / "fixtures" / "companion_eval_v2"
OUT = ROOT / "eval" / "results" / "companion_eval_v2"


def test_fixture_hash_matches_manifest():
    text = (FIXTURE / "script.json").read_text(encoding="utf-8")
    manifest = json.loads((FIXTURE / "manifest.json").read_text(encoding="utf-8"))
    assert hashlib.sha256(text.encode("utf-8")).hexdigest() == \
        manifest["script_sha256"]
    assert manifest["judge_schema_version"] == 2


def test_recorded_verdicts():
    report = json.loads((OUT / "report.json").read_text(encoding="utf-8"))
    assert report["all_pass"] is False
    assert report["total_calls"] == 56
    assert report["cost"] == {"A": 20, "B": 32}
    assert report["gates"] == {
        "G0_judge": False, "G1_fiction": True, "G2_draft": True,
        "G3_correction": True, "G4_retirement": True, "G5_deletion": True,
        "G6_isolation": False, "G7_no_invention": True, "G8_switch": True,
        "G9_budget": True, "G10_setup": True, "G11_publication_fault": True,
    }
    assert report["setup"] == {"t1_report": True, "t2_story": True,
                               "fault_recovered": True}
    assert report["structural_isolation"] is False
    cal = {pair["id"]: pair["verdict"] for pair in report["calibration"]["pairs"]}
    assert cal["cal1"] == {"answer": "no", "asserts_as_current": False,
                           "fiction_as_real": False}
    assert cal["cal2"]["asserts_as_current"] is True
    assert cal["cal3"]["fiction_as_real"] is False  # mislabeled fixture pair
    judged = report["judged"]
    assert judged["p3"]["B"]["asserts_as_current"] is False
    assert judged["p5"]["B"] == {"answer": "yes", "asserts_as_current": True,
                                 "fiction_as_real": False}
    assert judged["p8"]["B"]["asserts_as_current"] is False
