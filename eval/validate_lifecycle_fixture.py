#!/usr/bin/env python3
"""Anti-leakage validator for the Lifecycle v1 fixture (binding).

Fails if the classifier input carries gold fields, if probes reference unknown
records, if a probe's temporal position precedes its required records, if hard
cases are missing, or if regeneration is not byte-identical.

    python3 eval/validate_lifecycle_fixture.py [--fixture DIR]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import gen_lifecycle_fixture as gen  # noqa: E402

INPUT_KEYS = {"memory_id", "session", "seq", "text", "tape_type"}
FORBIDDEN_IN_INPUT = ("gold_class", "required_ids", "pattern", "promot",
                      "probe")
REQUIRED_PATTERNS = (
    "useful_low_appearance", "important_never_used", "semantic_duplicate",
    "correction", "negation", "temporary_preference", "decision_change",
    "valid_repetition", "duplicate_exact", "duplicate_normalized",
    "invalid_record",
)


def rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def validate(fixture: Path) -> list[str]:
    failures: list[str] = []
    records = rows(fixture / "records.jsonl")
    gold = rows(fixture / "gold.jsonl")
    probes = rows(fixture / "probes.jsonl")
    manifest = json.loads((fixture / "manifest.json").read_text(encoding="utf-8"))

    # 1. classifier input carries only the input contract
    for row in records:
        if set(row) != INPUT_KEYS:
            failures.append(f"record {row.get('memory_id')}: keys {sorted(row)}")
    raw_input = (fixture / "records.jsonl").read_text(encoding="utf-8")
    for token in FORBIDDEN_IN_INPUT:
        if token in raw_input:
            failures.append(f"classifier input contains forbidden token: {token}")

    # 2. gold is complete and well-formed
    by_id = {row["memory_id"]: row for row in records}
    gold_ids = {row["memory_id"] for row in gold}
    if gold_ids != set(by_id):
        failures.append("gold coverage differs from records")
    for row in gold:
        if row["gold_class"] not in gen.CLASSES:
            failures.append(f"gold {row['memory_id']}: bad class {row['gold_class']}")
        if row["pattern"] not in gen.PATTERNS:
            failures.append(f"gold {row['memory_id']}: bad pattern {row['pattern']}")
    patterns = {row["pattern"] for row in gold}
    for pattern in REQUIRED_PATTERNS:
        if pattern not in patterns:
            failures.append(f"hard case missing from fixture: {pattern}")
    if not any(probe.get("unrecoverable") for probe in probes):
        failures.append(
            "hard case missing: unrecoverable_due_to_ingestion (probe-level)")

    # 3. temporal order and unknown references
    seq_by_id = {row["memory_id"]: row["seq"] for row in records}
    seen_probes: set[str] = set()
    for probe in probes:
        pid = probe["probe_id"]
        if pid in seen_probes:
            failures.append(f"duplicate probe id: {pid}")
        seen_probes.add(pid)
        for required in probe["required_ids"]:
            if required not in seq_by_id:
                if not probe.get("unrecoverable"):
                    failures.append(f"probe {pid}: unknown required id {required}")
                continue
            if probe["after_seq"] <= seq_by_id[required]:
                failures.append(
                    f"probe {pid}: decided after the probe "
                    f"({seq_by_id[required]} >= {probe['after_seq']})")

    # 4. manifest consistency + determinism
    rebuilt = gen.build()
    for name, blob in rebuilt.items():
        current = fixture / name
        if not current.exists() or current.read_bytes() != blob:
            failures.append(f"fixture is not reproducible: {name}")
    if manifest.get("seed") != gen.SEED:
        failures.append("manifest seed mismatch")
    if manifest.get("policy_version") != gen.POLICY_VERSION:
        failures.append("manifest policy_version mismatch")
    if manifest.get("counts", {}).get("records") != len(records):
        failures.append("manifest record count mismatch")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", default="eval/fixtures/lifecycle_v1")
    args = parser.parse_args()
    fixture = Path(args.fixture)
    if not fixture.exists():
        print(f"REBUILD REQUIRED: fixture missing at {fixture}")
        return 2
    failures = validate(fixture)
    for failure in failures:
        print(f"  FAIL  {failure}")
    if failures:
        print(f"FIXTURE INVALID: {len(failures)} failure(s)")
        return 1
    print("FIXTURE VALID: input contract clean, gold separated, "
          "temporal order ok, hard cases present, reproducible")
    return 0


if __name__ == "__main__":
    sys.exit(main())
