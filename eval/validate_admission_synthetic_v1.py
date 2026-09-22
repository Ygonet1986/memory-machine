#!/usr/bin/env python3
"""Validate the admission-synthetic-v1 fixture.

Checks schema invariants and that the committed sample is byte-identical to a
fresh deterministic regeneration (generator frozen).

    python3 eval/validate_admission_synthetic_v1.py [--fixture DIR]

Exit 0 = valid; 1 = problems.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import gen_admission_synthetic_v1 as gen  # noqa: E402


def validate(fixture: Path) -> list[str]:
    problems: list[str] = []
    cases_path = fixture / "cases.jsonl"
    manifest_path = fixture / "manifest.json"
    if not cases_path.exists() or not manifest_path.exists():
        return [f"missing fixture files under {fixture}"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload = cases_path.read_text(encoding="utf-8")
    if hashlib.sha256(payload.encode("utf-8")).hexdigest() != manifest.get("cases_sha256"):
        problems.append("cases_sha256 does not match cases.jsonl")

    regenerated = "".join(
        json.dumps(case, ensure_ascii=False, sort_keys=True) + "\n"
        for case in gen.build_cases())
    if regenerated != payload:
        problems.append("regeneration differs from the committed sample")

    cases = [json.loads(line) for line in payload.splitlines() if line.strip()]
    if len(cases) != manifest.get("cases"):
        problems.append("case count differs from the manifest")
    counts: dict[str, int] = {}
    seen_cases: set[str] = set()
    for case in cases:
        missing = {"case_id", "scenario", "question", "records", "gold",
                   "expectation"} - set(case)
        if missing:
            problems.append(f"{case.get('case_id')}: missing keys {sorted(missing)}")
            continue
        cid = case["case_id"]
        if cid in seen_cases:
            problems.append(f"duplicate case id {cid}")
        seen_cases.add(cid)
        counts[case["scenario"]] = counts.get(case["scenario"], 0) + 1
        if case["scenario"] not in gen.SCENARIOS:
            problems.append(f"{cid}: unknown scenario {case['scenario']}")
        if not str(case["question"]).strip():
            problems.append(f"{cid}: empty question")
        if case["expectation"] not in {"deliver", "abstain"}:
            problems.append(f"{cid}: bad expectation {case['expectation']}")
        ids = [record.get("memory_id") for record in case["records"]]
        if len(ids) != len(set(ids)):
            problems.append(f"{cid}: duplicate record ids")
        if len(case["gold"]) != len(set(case["gold"])):
            problems.append(f"{cid}: duplicate gold ids")
        missing_gold = [mid for mid in case["gold"] if mid not in ids]
        if missing_gold:
            problems.append(f"{cid}: gold not in records: {missing_gold}")
        if case["expectation"] == "abstain" and case["gold"]:
            problems.append(f"{cid}: abstain case with gold")
        if case["expectation"] == "deliver" and not case["gold"]:
            problems.append(f"{cid}: deliver case without gold")
        for record in case["records"]:
            if not str(record.get("summary", "")).strip():
                problems.append(f"{cid}/{record.get('memory_id')}: empty summary")
    expected = {scenario: gen.CASES_PER_SCENARIO for scenario in gen.SCENARIOS}
    if counts != expected:
        problems.append(f"scenario counts differ: {counts}")
    if manifest.get("counts_by_scenario") != counts:
        problems.append("manifest counts_by_scenario differ from the sample")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture",
                        default=str(HERE / "fixtures" / "admission_synthetic_v1"))
    args = parser.parse_args()
    problems = validate(Path(args.fixture))
    if problems:
        for problem in problems:
            print(f"FAIL  {problem}")
        return 1
    print("admission-synthetic-v1 fixture: valid (schema + frozen regeneration)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
