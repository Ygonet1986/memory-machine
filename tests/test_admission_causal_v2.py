"""admission-causal-v2 lab: relation slot mechanism and recorded verdicts."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))
sys.path.insert(0, str(ROOT / "src"))

import admission_causal_v1 as v1  # noqa: E402
import admission_causal_v2 as harness  # noqa: E402

FIXTURE = ROOT / "eval" / "fixtures" / "admission_causal_v1"


def test_slot_requires_cue_and_relation():
    cases = v1.load_cases(FIXTURE)
    for case in cases:
        records = v1._wrap(case["records"])
        lexical = v1._lexical_candidates(case["question"], records)
        slot, source, _score = harness.slot_evidence(case, records, lexical)
        if case["scenario"] in {"causal_buried", "causal_chain"}:
            assert slot is not None and source is not None
            assert source in case["gold"] and slot.memory_id in case["gold"]
        else:
            assert slot is None, case["case_id"]


def test_deterministic_and_recorded_verdicts():
    report = harness.collect(FIXTURE)
    assert harness.content_digest(report) == harness.content_digest(
        harness.collect(FIXTURE))
    assert report["slot_used_total"] == 20
    assert report["policies"]["B"]["availability"] == 0.6667
    assert report["policies"]["S"]["availability"] == 1.0
    assert report["policies"]["S"]["precision"] == 0.8571
    assert report["policies"]["S"]["max_items"] == 2
    assert report["policies"]["S"]["undue_rate"] == 0.0
    assert all(report["requirements"].values()) is True
