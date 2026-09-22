"""ingestion-trace-v1: classifications, metric fix and recorded gates."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))
sys.path.insert(0, str(ROOT / "src"))

import ingestion_trace_v1 as harness  # noqa: E402
import phrase_delivery_v1 as pd  # noqa: E402


def test_recorded_classifications():
    report = harness.collect()
    classes = {(r["block"], r["case"]): r["classification"]
               for r in report["rows"]}
    assert classes == {("u3a", 14): "computation_needed",
                       ("u3a", 21): "computation_needed",
                       ("u3b", 30): "computation_needed",
                       ("u3b", 40): "computation_needed"}
    assert report["gates"] == {"I1_classified": True, "I2_metric_fix": True,
                               "I4_origin_excerpts": True}


def test_abstention_metric_fix_default_path_unchanged():
    report = harness.collect()
    abstention = report["abstention_u3b41"]
    assert abstention["aware"]["basis"] == "abstention"
    assert abstention["aware"]["applicable"] is False
    assert abstention["aware"]["ok"] is True
    assert abstention["default_basis"] in ("atom_fallback", "phrase")
    assert report["default_path_regression_u3a22"]["ok"] is True


def test_u3a17_residual_recorded():
    report = harness.collect()
    residual = report["residual_u3a17"]
    assert residual["gold_phrases"] == ["1year"]
    assert residual["presence"] == {"W0": False, "W1": False,
                                    "W3": False, "W5": False}
    assert residual["segment_position"] == 106
    assert residual["segment_count"] == 213


def test_abstention_detection_patterns():
    assert pd.ABSTENTION_RE.search("The information provided is not enough.")
    assert not pd.ABSTENTION_RE.search("two weeks")
