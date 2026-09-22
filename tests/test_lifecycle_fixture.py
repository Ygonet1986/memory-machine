"""Lifecycle v1 fixture: anti-leakage, temporal order, determinism.

The classifier input must never carry gold; probes must be measurable only
after the record they require; hard cases must exist; regeneration must be
byte-identical. These are the binding guards of the pre-registration.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))

import validate_lifecycle_fixture as validator  # noqa: E402
from gen_lifecycle_fixture import build  # noqa: E402

FIXTURE = ROOT / "eval" / "fixtures" / "lifecycle_v1"


def test_fixture_is_clean_and_reproducible():
    failures = validator.validate(FIXTURE)
    assert failures == [], failures


def test_classifier_input_never_carries_gold_fields():
    import json

    rows = [json.loads(line) for line in
            (FIXTURE / "records.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()]
    assert rows
    for row in rows:
        assert set(row) == {"memory_id", "session", "seq", "text", "tape_type"}
    gold = (FIXTURE / "gold.jsonl").read_text(encoding="utf-8")
    assert "gold_class" in gold  # the gold file exists, separate from input


def test_probes_are_measured_after_the_required_records():
    import json

    records = {row["memory_id"]: row["seq"] for row in (
        json.loads(line) for line in
        (FIXTURE / "records.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip())}
    probes = [json.loads(line) for line in
              (FIXTURE / "probes.jsonl").read_text(encoding="utf-8").splitlines()
              if line.strip()]
    for probe in probes:
        for required in probe["required_ids"]:
            if required in records:
                assert probe["after_seq"] > records[required], probe["probe_id"]


def test_hard_cases_are_present():
    import json

    gold = [json.loads(line) for line in
            (FIXTURE / "gold.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()]
    patterns = {row["pattern"] for row in gold}
    for expected in ("useful_low_appearance", "important_never_used",
                     "semantic_duplicate", "correction", "negation",
                     "temporary_preference", "decision_change",
                     "valid_repetition", "duplicate_exact",
                     "duplicate_normalized", "invalid_record"):
        assert expected in patterns, expected


def test_regeneration_is_byte_identical(tmp_path):
    generated = build()
    for name, blob in generated.items():
        assert (FIXTURE / name).read_bytes() == blob, name
