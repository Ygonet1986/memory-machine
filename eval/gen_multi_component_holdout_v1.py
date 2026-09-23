#!/usr/bin/env python3
"""Deterministic generator for the multi-component money holdout (W6c).

12 cases whose answer requires TWO distant values (the combined total is
never written in the record). Design verified at generation with the product
code: the two components are present, lie in different positional strata,
are beyond the head allocation, the frozen W6c window delivers BOTH, and the
W1/W4 reference coverage is reported (not forced).

    python3 eval/gen_multi_component_holdout_v1.py --out eval/fixtures/multi_component_holdout_v1
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

import numeral_inclusion_v1 as ni  # noqa: E402

GENERATOR_VERSION = 1
CASES = 12
ALLOCATION = 3600
PROJECTS = ("Vega", "Orion", "Lyra", "Pavo")
PAIRS = (
    ("annual audit", "training program"),
    ("device fleet", "support contract"),
    ("launch event", "venue booking"),
    ("data migration", "hardware refresh"),
)
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
    return (date(2026, 9, 1) + timedelta(days=offset)).isoformat()


def build_cases() -> list[dict]:
    cases = []
    for index in range(CASES):
        project = PROJECTS[index % 4]
        item_a, item_b = PAIRS[index % len(PAIRS)]
        value_a = 400 + 60 * (index + 1)      # $460 .. $1,120
        value_b = value_a + 220               # second component
        total = value_a + value_b
        slot_a, slot_b = 18, 88               # different strata (of 110)
        distractor_1, distractor_2 = 40, 70

        segments = []
        for slot in range(110):
            if slot == slot_a:
                segments.append(
                    f"The first invoice closed at ${value_a} once the "
                    f"paperwork was done.")
            elif slot == slot_b:
                segments.append(
                    f"Separately, the second invoice came to ${value_b} in "
                    f"the final sheet.")
            elif slot == distractor_1:
                segments.append(
                    f"An early estimate mentioned ${value_a + 90} for the "
                    f"first part of the work.")
            elif slot == distractor_2:
                segments.append(
                    f"A draft listed ${value_b - 70} for the other part.")
            elif slot == 1:
                segments.append(
                    f"For the {item_a} and the {item_b} in {project}, the "
                    f"review compared vendor quotes and delivery dates.")
            elif slot == 2:
                segments.append(
                    f"The {item_a} and the {item_b} in {project} were "
                    f"discussed at length in the planning session.")
            else:
                segments.append(FILLERS[slot % len(FILLERS)])
        why = f"user: I need the {item_a} and {item_b} numbers for " \
              f"{project}. " + " ".join(segments)
        record_id = f"L{index + 1:02d}-R01"
        records = [{
            "memory_id": record_id, "type": "memory",
            "summary": f"user: combined numbers for the {project} work",
            "why": why, "created_at": _iso(index),
        }]
        for number in range(2):
            records.append({
                "memory_id": f"L{index + 1:02d}-D{number + 1:02d}",
                "type": "memory",
                "summary": f"user: note about the {project} planning",
                "why": "user: we compared quotes and asked for a revised "
                       f"sheet (round {number + 1}).",
                "created_at": _iso(index + number + 1),
            })
        cases.append({
            "case_id": f"L{index + 1:02d}",
            "question": f"What was the combined amount spent on the {item_a} "
                        f"and the {item_b} in {project}?",
            "gold": f"${total}", "records": records,
            "required": [record_id],
            "components": [value_a, value_b],
            "slots": [slot_a, slot_b],
        })
    return cases


def verify(cases: list[dict]) -> dict:
    from component_allocation_v1 import w6c_window

    w6c_both = w4_both = w1_both = 0
    for case in cases:
        record = case["records"][0]
        text = f"{record['summary']} {record['why']}".strip()
        value_a, value_b = case["components"]
        assert f"${value_a}" in text and f"${value_b}" in text, case["case_id"]
        assert f"${value_a + value_b}" not in text, case["case_id"]
        room = ALLOCATION - len(record["summary"]) - 1
        windows = {
            "W6c": w6c_window(text, case["question"], room),
            "W4": ni.w4_window(text, case["question"], room),
            "W1": fact_window(text, case["question"], room),
        }
        has = {name: (f"${value_a}" in out and f"${value_b}" in out)
               for name, out in windows.items()}
        w6c_both += 1 if has["W6c"] else 0
        w4_both += 1 if has["W4"] else 0
        w1_both += 1 if has["W1"] else 0
        assert has["W6c"], case["case_id"]
    return {"w6c_both": w6c_both, "w4_both": w4_both, "w1_both": w1_both}


def generate(out_dir: Path) -> dict:
    cases = build_cases()
    checks = verify(cases)
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = "".join(json.dumps(case, ensure_ascii=False, sort_keys=True) + "\n"
                      for case in cases)
    (out_dir / "cases.jsonl").write_text(payload, encoding="utf-8")
    manifest = {
        "generator": "gen_multi_component_holdout_v1.py",
        "generator_version": GENERATOR_VERSION,
        "cases": len(cases),
        "allocation": ALLOCATION,
        "design_checks": checks,
        "cases_sha256": hashlib.sha256(payload.encode("utf-8")).hexdigest(),
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out",
                        default="eval/fixtures/multi_component_holdout_v1")
    args = parser.parse_args()
    print(json.dumps(generate(Path(args.out)), indent=2, ensure_ascii=False,
                     sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
