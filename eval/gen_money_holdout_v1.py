#!/usr/bin/env python3
"""Deterministic generator for the money-rule holdout fixture.

12 new cases with a money question and a currency answer placed at different
positions in the record (early/middle/late), plus two distractor amounts.
The rule under test (W4) is NOT referenced here: the fixture is generated from
declared positions only. Manifest carries the sample hash and the declared
positions.

    python3 eval/gen_money_holdout_v1.py --out eval/fixtures/money_holdout_v1
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date, timedelta
from pathlib import Path

GENERATOR_VERSION = 1
CASES = 12
ITEMS = ("consulting invoice", "laptop repair", "conference ticket",
         "team dinner", "design retainer", "legal review", "hardware order",
         "training course", "server upgrade", "marketing audit",
         "translation job", "photo shoot")
PROJECTS = ("Vega", "Orion", "Lyra", "Pavo")
FILLERS = (
    "the team reviewed scope and timeline",
    "a checklist was agreed for the next sprint",
    "the vendor confirmed availability",
    "notes were filed for the next review",
    "the schedule was adjusted once",
    "a follow-up call was booked",
    "the draft was shared for comments",
)


def _iso(offset: int) -> str:
    return (date(2026, 3, 1) + timedelta(days=offset)).isoformat()


def build_cases() -> list[dict]:
    cases = []
    for k in range(CASES):
        item = ITEMS[k % len(ITEMS)]
        project = PROJECTS[k % 4]
        target = 100 + 37 * (k + 1)
        distractor_a = target + 55
        distractor_b = target - 30
        position = ("early", "middle", "late")[k % 3]
        target_index = {"early": 3, "middle": 14, "late": 26}[position]

        why_parts = []
        for index in range(30):
            if index == target_index:
                why_parts.append(
                    f"In the end the {item} came to ${target} in total, "
                    f"which was written into the {project} ledger.")
            elif index == 6:
                why_parts.append(
                    f"A first estimate for the {item} was ${distractor_a}.")
            elif index == 20:
                why_parts.append(
                    f"A revised estimate of ${distractor_b} was discussed.")
            else:
                why_parts.append(FILLERS[index % len(FILLERS)].capitalize() + ".")
        why = "user: we need to close the books for the quarter. " + " ".join(why_parts)

        record_id = f"H{k + 1:02d}-R01"
        records = [{
            "memory_id": record_id, "type": "memory",
            "summary": f"user: closing notes for the {item} in {project}",
            "why": why, "created_at": _iso(k),
        }]
        decoy_id = f"H{k + 1:02d}-R02"
        records.append({
            "memory_id": decoy_id, "type": "memory",
            "summary": f"user: unrelated note about {project} scheduling",
            "why": "user: " + " ".join(FILLERS[(k + j) % len(FILLERS)] + "."
                                       for j in range(6)),
            "created_at": _iso(k + 1),
        })
        cases.append({
            "case_id": f"H{k + 1:02d}",
            "question": f"What is the total amount spent on the {item} in {project}?",
            "gold": f"${target}", "records": records,
            "gold_record": record_id, "target": target,
            "distractors": [distractor_a, distractor_b], "position": position,
        })
    return cases


def generate(out_dir: Path) -> dict:
    cases = build_cases()
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = "".join(json.dumps(case, ensure_ascii=False, sort_keys=True) + "\n"
                      for case in cases)
    (out_dir / "cases.jsonl").write_text(payload, encoding="utf-8")
    manifest = {
        "generator": "gen_money_holdout_v1.py",
        "generator_version": GENERATOR_VERSION,
        "cases": len(cases),
        "positions": {p: sum(1 for c in cases if c["position"] == p)
                      for p in ("early", "middle", "late")},
        "cases_sha256": hashlib.sha256(payload.encode("utf-8")).hexdigest(),
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="eval/fixtures/money_holdout_v1")
    args = parser.parse_args()
    print(json.dumps(generate(Path(args.out)), indent=2, ensure_ascii=False,
                     sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
