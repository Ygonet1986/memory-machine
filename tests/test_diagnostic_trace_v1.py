"""diagnostic-trace-v1: recorded four-stage verdicts and invariants."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))
sys.path.insert(0, str(ROOT / "src"))

import diagnostic_trace_v1 as harness  # noqa: E402

OUT = ROOT / "eval" / "results" / "diagnostic_trace_v1"


def test_deterministic_stages_recorded():
    rows, summary = harness.collect(skip_llm=True)
    assert summary["T1_stage_consistency"] is True
    assert len(rows) == 12
    by_key = {(r["block"], r["case"], r["arm"]): r for r in rows}
    for arm in ("W0", "W1", "W3"):
        row = by_key[("u3a", 19, arm)]
        assert row["ingestion_ok"] is True
        assert row["delivery_ok"] is False
        assert "number:200" in row["delivery_missing"]
    for arm in ("W0", "W1", "W3"):
        assert by_key[("u3a", 12, arm)]["delivery_ok"] is True


def test_recorded_answer_stage():
    report = json.loads((OUT / "report.json").read_text(encoding="utf-8"))
    by_key = {(r["block"], r["case"], r["arm"]): r for r in report["rows"]}
    assert by_key[("u3a", 12, "W3")]["answer"]["verdicts"] == ["correct"] * 3
    assert by_key[("u3a", 22, "W3")]["answer"]["verdicts"] == ["incorrect"] * 3
    assert by_key[("u3a", 22, "W1")]["answer"]["verdicts"] == ["correct"] * 3
    v27 = by_key[("u3b", 27, "W1")]["answer"]["verdicts"]
    assert v27.count("correct") == 2 and v27.count("incorrect") == 1
    assert report["summary"]["llm_calls"] == 72
