#!/usr/bin/env python3
"""Deterministic generator for the corrected money holdout (W4).

Design fixes the two flaws of money-holdout-v1: records are LONGER than the
window allocation (truncation actually happens) and positions are declared
(4 early / 4 middle / 4 late) with distractor amounts. Verified at
generation with the product code: the frozen W4 window contains the target
answer; the W1 window's coverage is reported (not forced).

    python3 eval/gen_money_holdout_v2.py --out eval/fixtures/money_holdout_v2
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

from memory_machine.payload import fact_window  # noqa: E402
from memory_machine.retrieval import bm25  # noqa: E402

import numeral_inclusion_v1 as ni  # noqa: E402

GENERATOR_VERSION = 1
CASES = 12
ALLOCATION = 3600
PROJECTS = ("Vega", "Orion", "Lyra", "Pavo")
ITEMS = ("annual audit", "device fleet", "launch event", "data migration",
         "office refit", "support contract", "training program", "brand study",
         "release party", "hardware refresh", "legal review", "venue booking")
FILLERS = (
    "The team reviewed the plan and confirmed the dates.",
    "A short summary was shared with the stakeholders.",
    "The vendor sent the updated schedule in the morning.",
    "Open questions were parked for the next sync.",
    "The checklist was updated after the walkthrough.",
    "A reminder was set for the following week.",
    "Notes from the session were filed with the project.",
)


def _iso(offset: int) -> str:
    return (date(2026, 8, 1) + timedelta(days=offset)).isoformat()


def build_cases() -> list[dict]:
    cases = []
    for index in range(CASES):
        project = PROJECTS[index % 4]
        item = ITEMS[index % len(ITEMS)]
        target = 300 + 70 * (index + 1)          # $370 .. $1,140
        distractor_a = target + 120
        distractor_b = target - 90
        position = ("early", "middle", "late")[index % 3]
        target_index = {"early": 6, "middle": 75, "late": 100}[position]

        segments = []
        for slot in range(110):
            if slot == target_index:
                segments.append(
                    f"The final invoice closed at ${target} once everything "
                    f"was settled.")
            elif slot == 1:
                segments.append(
                    f"For the {item} in {project}, the review compared "
                    f"vendor quotes and delivery dates.")
            elif slot == 2:
                segments.append(
                    f"The {item} in {project} was discussed at length, "
                    f"including the ${distractor_a} option.")
            elif slot == 45:
                segments.append(
                    f"A later draft mentioned ${distractor_b} for the work.")
            else:
                segments.append(FILLERS[slot % len(FILLERS)])
        why = f"user: I need the {item} numbers for {project}. " + \
              " ".join(segments)
        record_id = f"G{index + 1:02d}-R01"
        records = [{
            "memory_id": record_id, "type": "memory",
            "summary": f"user: numbers for the {project} {item}",
            "why": why, "created_at": _iso(index),
        }]
        for number in range(2):
            records.append({
                "memory_id": f"G{index + 1:02d}-D{number + 1:02d}",
                "type": "memory",
                "summary": f"user: note about the {project} {item} planning",
                "why": f"user: we compared vendor quotes for the {item} and "
                       f"asked for a revised sheet (round {number + 1}).",
                "created_at": _iso(index + number + 1),
            })
        cases.append({
            "case_id": f"G{index + 1:02d}",
            "question": f"What was the total amount spent on the {item} "
                        f"in {project}?",
            "gold": f"${target}", "records": records,
            "required": [record_id], "position": position,
            "target": target,
        })
    return cases


def verify(cases: list[dict]) -> dict:
    w4_ok = w1_ok = 0
    for case in cases:
        by_id = {r["memory_id"]: r for r in case["records"]}
        text = f"{by_id[case['required'][0]]['summary']} " \
               f"{by_id[case['required'][0]]['why']}".strip()
        assert len(text) > ALLOCATION + 1000, case["case_id"]
        gold = case["gold"].lower()
        assert gold in text.lower(), case["case_id"]
        # early targets are shallow by design (W1 reference case); middle/late
        # targets must sit beyond the W1 window (anchored at the question-rich
        # head cluster), making the fixture discriminating.
        if case["position"] in ("middle", "late"):
            assert gold not in text[:ALLOCATION].lower(), case["case_id"]
        else:
            assert gold in text[:ALLOCATION].lower(), case["case_id"]
        w4 = ni.w4_window(text, case["question"], ALLOCATION)
        assert gold in w4.lower(), case["case_id"]
        w4_ok += 1
        w1 = fact_window(text, case["question"], ALLOCATION)
        if gold in w1.lower():
            w1_ok += 1
        if case["position"] in ("middle", "late"):
            assert gold not in w1.lower(), case["case_id"]
        scores = bm25(case["question"], [f"{r['summary']} {r['why']}"
                                         for r in case["records"]])
        order = sorted(range(len(case["records"])), key=lambda i: -scores[i])
        ranked = [case["records"][i]["memory_id"] for i in order
                  if scores[i] > 0]
    return {"w4_contains_target": w4_ok, "w1_contains_target": w1_ok}


def generate(out_dir: Path) -> dict:
    cases = build_cases()
    checks = verify(cases)
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = "".join(json.dumps(case, ensure_ascii=False, sort_keys=True) + "\n"
                      for case in cases)
    (out_dir / "cases.jsonl").write_text(payload, encoding="utf-8")
    manifest = {
        "generator": "gen_money_holdout_v2.py",
        "generator_version": GENERATOR_VERSION,
        "cases": len(cases),
        "allocation": ALLOCATION,
        "positions": {p: sum(1 for c in cases if c["position"] == p)
                      for p in ("early", "middle", "late")},
        "design_checks": checks,
        "cases_sha256": hashlib.sha256(payload.encode("utf-8")).hexdigest(),
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="eval/fixtures/money_holdout_v2")
    args = parser.parse_args()
    print(json.dumps(generate(Path(args.out)), indent=2, ensure_ascii=False,
                     sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
