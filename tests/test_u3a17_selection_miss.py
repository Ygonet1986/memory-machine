"""Correction guard: u3a-17 is a selection/annotation miss, not a room case."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))
sys.path.insert(0, str(ROOT / "src"))

import delivery_combined_v1 as dc  # noqa: E402
from fact_presence import item_span  # noqa: E402


def test_u3a17_required_record_absent_from_payload_and_annotations():
    cases, records = dc.load_fixture(ROOT / "eval" / "fixtures" / "composition_u4")
    case = next(c for c in cases if (c["block"], c["case"]) == ("u3a", 17))
    assert case["required_ids"] == ["M0043"]
    assert case["payload_ids"] == ["M0018", "M0022"]
    assert "M0043" not in case["context"]
    span, found = item_span(case["context"], "M0043")
    assert found is False and span == ""
    record = records[(17, "M0043")]
    assert "over a year" in record["why"].lower()


def test_frozen_snapshot_shows_agents_never_annotated_m0043():
    """The snapshot lives under gitignored eval/graph_out; when present it
    is the primary evidence; the payload_ids invariant is committed."""
    path = ROOT / "eval" / "graph_out" / "u_diag_longmemeval_u3a.jsonl"
    if not path.exists():
        pytest.skip("frozen snapshot not present in this checkout")
    rows = [json.loads(line) for line in path.read_text().splitlines()
            if line.strip()]
    row = next(r for r in rows if r.get("case") == 17)
    assert row["agent_ids"] == ["M0018", "M0022"]
    assert "M0043" not in row["agent_ids"]
