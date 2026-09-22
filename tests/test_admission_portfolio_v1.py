"""admission-portfolio-v1 lab: frozen fixture, determinism, recorded verdicts."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))
sys.path.insert(0, str(ROOT / "src"))

import admission_portfolio_v1 as harness  # noqa: E402
import gen_admission_portfolio_v1 as gen  # noqa: E402

FIXTURE = ROOT / "eval" / "fixtures" / "admission_portfolio_v1"


def test_fixture_regenerates_byte_identically():
    payload = (FIXTURE / "cases.jsonl").read_text(encoding="utf-8")
    manifest = json.loads((FIXTURE / "manifest.json").read_text(encoding="utf-8"))
    regenerated = "".join(
        json.dumps(case, ensure_ascii=False, sort_keys=True) + "\n"
        for case in gen.build_cases())
    assert regenerated == payload
    import hashlib
    assert hashlib.sha256(payload.encode("utf-8")).hexdigest() == manifest["cases_sha256"]


def test_harness_deterministic_and_recorded_verdicts():
    report = harness.collect(FIXTURE)
    assert harness.content_digest(report) == harness.content_digest(
        harness.collect(FIXTURE))
    policies = report["policies"]
    assert policies["P3v4"]["availability"] == 0.9091
    assert policies["P3v4"]["precision"] == 0.8333
    assert policies["P4"]["availability"] == 0.9091
    assert policies["P4"]["precision"] == 0.7143
    assert policies["P4-abl"]["precision"] == 0.7143
    assert report["gates"]["G1_availability"] is True
    assert report["gates"]["G2_precision"] is True
    assert report["gates"]["G3_beats_p3v4"] is False
    assert report["gates"]["G4_targeted_wins"] is False
    assert all(report["gates"].values()) is False
