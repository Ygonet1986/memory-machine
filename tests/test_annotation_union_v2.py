"""annotation-union-v2: recorded verdicts and the excerpt-limit cause."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))
sys.path.insert(0, str(ROOT / "src"))

import annotation_union_v2 as harness  # noqa: E402

OUT = ROOT / "eval" / "results" / "annotation_union_v2"


def test_recorded_verdicts():
    report = json.loads((OUT / "report.json").read_text(encoding="utf-8"))
    assert report["aggregates"]["A"]["mean_coverage"] == 0.4856
    assert report["aggregates"]["U"]["mean_coverage"] == 0.5394
    assert report["u3a17"]["m0043_hits"] == 0
    assert report["llm_calls"] == 180
    assert report["failures"] == 0
    assert report["gates"] == {"H2-1_coverage": True, "H2-2_undue": True,
                               "H2-3_u3a17": False, "H2-4_infra": True}
    assert report["all_pass"] is False


def test_excerpt_limit_explains_u3a17():
    cases, records = harness.dc.load_fixture(ROOT / "eval" / "fixtures"
                                             / "composition_u4")
    record = records[(17, "M0043")]
    text = f"{record['summary']} {record['why']}".strip()
    assert "over a year" not in text[:harness.EXCERPT].lower()
    assert text.lower().find("over a year") > 6000
