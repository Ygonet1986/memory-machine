"""money-holdout-v1: recorded holdout outcome and rule-freeze invariant."""

from __future__ import annotations

import hashlib
import inspect
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))
sys.path.insert(0, str(ROOT / "src"))

import money_holdout_v1 as harness  # noqa: E402
import numeral_inclusion_v1 as ni  # noqa: E402


def test_w4_rule_is_frozen_by_source_hash():
    digest = hashlib.sha256(inspect.getsource(ni.w4_window).encode()).hexdigest()
    assert digest == harness.W4_SOURCE_SHA


def test_recorded_holdout_outcome():
    cases = harness.load_holdout(ROOT / "eval" / "fixtures" / "money_holdout_v1")
    stage = harness.delivery_stage(cases)
    assert stage["w1_present"] == 12 and stage["w4_present"] == 12
    assert stage["gates"]["H1_new_fixture"] is False  # fixture too easy
    assert stage["gates"]["H2_positions"] is False
    assert stage["external_u3a24"]["W4"]["ok"] is False  # derived-sum gold
