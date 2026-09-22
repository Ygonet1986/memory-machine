"""ingestion-caveats-v1: verified headers, reference-date unavailability."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))
sys.path.insert(0, str(ROOT / "src"))

import ingestion_caveats_v1 as harness  # noqa: E402


def test_u3a14_components_are_header_dates():
    report = harness.collect()
    entry = report["u3a14"]
    assert entry["distinct_date_like"] == []
    assert entry["header_dates"] == {"M0045": "2023-03-21",
                                     "M0032": "2023-02-26"}
    assert entry["interval_days"] == 23  # ~3 weeks, the gold
    assert harness.collect()["u3a14"] == entry  # deterministic


def test_u3b40_reference_date_unavailable():
    report = harness.collect()
    entry = report["u3b40"]
    assert entry["has_question_date_field"] is False
    assert entry["question_date_tokens"] == []
    assert entry["delivered_header_dates"] == ["2023-03-20 18:06"]
