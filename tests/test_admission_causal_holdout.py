"""causal holdout: frozen fixture and the recorded single evaluation."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))
sys.path.insert(0, str(ROOT / "src"))

import admission_causal_holdout as harness  # noqa: E402
import gen_admission_causal_holdout as gen  # noqa: E402

FIXTURE = ROOT / "eval" / "fixtures" / "admission_causal_holdout"


def test_holdout_regenerates_byte_identically():
    payload = (FIXTURE / "cases.jsonl").read_text(encoding="utf-8")
    manifest = json.loads((FIXTURE / "manifest.json").read_text(encoding="utf-8"))
    regenerated = "".join(
        json.dumps(case, ensure_ascii=False, sort_keys=True) + "\n"
        for case in gen.build_cases())
    assert regenerated == payload
    assert hashlib.sha256(payload.encode("utf-8")).hexdigest() == manifest["cases_sha256"]


def test_single_evaluation_recorded_verdicts():
    report = harness.evaluate(FIXTURE)
    assert report["policies"]["B"]["availability"] == 0.6452
    assert report["policies"]["S"]["availability"] == 1.0
    assert report["policies"]["S"]["precision"] == 0.8857
    assert report["policies"]["S"]["undue_rate"] == 0.0
    assert report["slot_used_total"] == 22
    for gate in ("H1_availability", "H2_precision", "H3_factual_control",
                 "H4_absence", "H5_budget", "H6_determinism"):
        assert report["gates"][gate] is True, gate
    assert report["all_pass"] is True
