"""P3v4 product scorer: mandatory equivalence with the frozen v4 harness."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))
sys.path.insert(0, str(ROOT / "src"))

import admission_synthetic_v1 as v1  # noqa: E402
import admission_synthetic_v4 as v4  # noqa: E402
from memory_machine import admission_p3v4 as p3v4  # noqa: E402

FIXTURE = ROOT / "eval" / "fixtures" / "admission_synthetic_v1"


def _records(case):
    return [SimpleNamespace(id=r["memory_id"], type=r["type"],
                            summary=r["summary"], why=r["why"],
                            created_at=r["created_at"])
            for r in case["records"]]


def test_product_p3v4_equals_frozen_v4_harness_on_the_whole_fixture():
    cases = v1.load_cases(FIXTURE)
    assert len(cases) == 100
    for case in cases:
        records = _records(case)
        candidates = p3v4.build_candidates(case["question"], records)
        harness_candidates = v1.candidates_for(case)
        assert [c.memory_id for c in candidates] == [
            c["record"]["memory_id"] for c in harness_candidates], case["case_id"]
        p3v4.decide(case["question"], candidates, records)
        harness_selected, harness_removed = v4.deliver_v4(case, harness_candidates)
        assert p3v4.delivered_ids(candidates) == [
            c["record"]["memory_id"] for c in harness_selected], case["case_id"]
        assert sum(1 for c in candidates if c.removed_superseded) == harness_removed


def test_p3v4_constants_are_frozen():
    assert p3v4.BUDGET_CHARS == 4000
    assert p3v4.MAX_DELIVERIES == 2
    assert p3v4.RARE_FLOOR == 0.30
    assert p3v4.RELATIVE_FLOOR == 0.60
    assert p3v4.REDUNDANCY == 0.60
    assert p3v4.MIN_SUPERSEDE_OVERLAP == 2
    assert "supersedes" in p3v4.CORRECTION_MARKERS
    assert p3v4.TYPE_CUES["decision"] == ("decided", "decision", "decide", "migrate")
