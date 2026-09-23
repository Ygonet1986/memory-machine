#!/usr/bin/env python3
"""Deterministic generator for the gap-recall fixture (15 cases).

12 gap cases (4 numeral, 4 date, 4 two-component) whose demanded fact lives
in a *distinct* record that pass 1 (head+2, k=3) never consults, plus 3 easy
controls whose fact is already in the head. Between the head and the missing
record sit six numeral-free distractors that outrank it lexically, so the
equal-budget breadth control (k=4) also misses it.

Design verified at generation with the harness mechanism (product functions):
G0 incomplete 12/12, G1 complete 12/12, G2 incomplete 12/12, G3 complete
12/12, controls complete at G0 with zero directed queries.

    python3 eval/gen_gap_recall_v1.py --out eval/fixtures/gap_recall_v1
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "src"))

import gap_recall_v1 as gr  # noqa: E402

GENERATOR_VERSION = 1
PROJECTS = ("Vega", "Orion", "Lyra", "Pavo")
ITEMS = ("annual audit", "device fleet", "launch event", "data migration",
         "venue booking", "hardware refresh", "support contract",
         "training program")
FILLERS = (
    "The team reviewed the plan and confirmed the timeline.",
    "A short summary was shared with the stakeholders.",
    "The vendor sent the updated schedule in the morning.",
    "Open questions were parked for the next sync.",
    "The checklist was updated after the walkthrough.",
    "A reminder was set for the following week.",
    "The details were logged with the rest.",
)


def _iso(offset: int) -> str:
    return (date(2026, 10, 1) + timedelta(days=offset)).isoformat()


def _head(item: str, project: str, question_terms: tuple[str, ...],
          fact: str | None, index: int) -> dict:
    topic = f"The {item} in {project} stayed on the agenda for the vendor round."
    segments = [FILLERS[0], topic, FILLERS[2], topic, FILLERS[4], topic,
                fact or FILLERS[6]]
    return {
        "memory_id": f"C{index:02d}-R01", "type": "memory",
        "summary": f"user: working notes on the {item} for {project}",
        "why": " ".join(segments), "created_at": _iso(index),
    }


def _missing(item: str, project: str, text: str, index: int) -> dict:
    return {
        "memory_id": f"C{index:02d}-R02", "type": "memory",
        "summary": f"user: follow-up note about the {project} work",
        "why": f"{text} {FILLERS[0]} {FILLERS[3]}", "created_at": _iso(index + 1),
    }


def _distractor(item: str, project: str, round_: int, index: int) -> dict:
    return {
        "memory_id": f"C{index:02d}-D{round_:02d}", "type": "memory",
        "summary": f"user: note about the {project} planning",
        "why": (f"We compared the {item} quotes and parked the rest for now "
                f"in round {round_}."),
        "created_at": _iso(index + round_ + 1),
    }


def build_cases() -> list[dict]:
    cases = []
    counter = 0
    for index in range(4):
        project = PROJECTS[index % 4]
        item = ITEMS[index % len(ITEMS)]
        value = 620 + 45 * (index + 1)
        counter += 1
        cases.append({
            "case_id": f"C{counter:02d}", "kind": "numeral",
            "question": f"How much did the {item} for {project} cost?",
            "gold": f"${value}",
            "records": [
                _head(item, project, (item, project), None, counter),
                _missing(item, project,
                         f"The {item} invoice came to ${value} in the final "
                         f"sheet.", counter),
            ] + [_distractor(item, project, n, counter) for n in range(1, 7)],
            "missing_records": [f"C{counter:02d}-R02"],
            "components": [value],
        })
    for index in range(4):
        project = PROJECTS[(index + 1) % 4]
        item = ITEMS[(index + 2) % len(ITEMS)]
        iso = _iso(10 * (index + 1))
        counter += 1
        cases.append({
            "case_id": f"C{counter:02d}", "kind": "date",
            "question": f"When was the {item} for {project} paid?",
            "gold": iso,
            "records": [
                _head(item, project, (item, project), None, counter),
                _missing(item, project,
                         f"The {item} payment was made on {iso}.", counter),
            ] + [_distractor(item, project, n, counter) for n in range(1, 7)],
            "missing_records": [f"C{counter:02d}-R02"],
            "components": [iso],
        })
    for index in range(4):
        project = PROJECTS[(index + 2) % 4]
        item_a = ITEMS[(index + 1) % len(ITEMS)]
        item_b = ITEMS[(index + 5) % len(ITEMS)]
        value_a = 540 + 35 * (index + 1)
        value_b = value_a + 190
        counter += 1
        cases.append({
            "case_id": f"C{counter:02d}", "kind": "components",
            "question": f"What did we spend on the {item_a} and the {item_b} "
                        f"in {project}?",
            "gold": f"${value_a} and ${value_b}",
            "records": [
                _head(item_a, project, (item_a, item_b, project),
                      f"The first quote for the {item_a} closed at ${value_a} "
                      f"once the paperwork was done.", counter),
                _missing(item_b, project,
                         f"Separately, the {item_b} invoice came to ${value_b} "
                         f"in the final sheet.", counter),
            ] + [_distractor(item_b, project, n, counter) for n in range(1, 7)],
            "missing_records": [f"C{counter:02d}-R02"],
            "components": [value_a, value_b],
        })
    for index in range(3):
        project = PROJECTS[(index + 3) % 4]
        item = ITEMS[(index + 3) % len(ITEMS)]
        counter += 1
        if index == 0:
            value = 780 + 30 * (index + 1)
            question = f"How much did the {item} for {project} cost?"
            gold = f"${value}"
            fact = f"The {item} closed at ${value} after the review."
        elif index == 1:
            iso = _iso(40 + index)
            question = f"When was the {item} for {project} paid?"
            gold = iso
            fact = f"The {item} payment was made on {iso}."
        else:
            value_a = 610
            value_b = 830
            question = (f"What did we spend on the {item} and the "
                        f"{ITEMS[index + 4]} in {project}?")
            gold = f"${value_a} and ${value_b}"
            fact = (f"The {item} closed at ${value_a} and the "
                    f"{ITEMS[index + 4]} closed at ${value_b} in the same "
                    f"review.")
        cases.append({
            "case_id": f"C{counter:02d}", "kind": "control",
            "question": question, "gold": gold,
            "records": [
                _head(item, project, (item, project), fact, counter),
            ] + [_distractor(item, project, n, counter) for n in range(1, 3)],
            "missing_records": [],
            "components": [],
        })
    return cases


def verify(cases: list[dict]) -> dict:
    checks = {"g0_incomplete": 0, "g1_complete": 0, "g2_incomplete": 0,
              "g3_complete": 0, "control_g0_complete": 0,
              "control_g1_extra_zero": 0}
    for case in cases:
        g0 = gr.pass1(case)
        g1 = gr.gap_recall(case)
        g2 = gr.pass1(case, k=gr.K_BREADTH)
        g3 = gr.oracle(case)
        if case["kind"] == "control":
            assert gr.is_complete(case, g0["delivered"]), case["case_id"]
            assert g1["directed_extra"] == 0, case["case_id"]
            checks["control_g0_complete"] += 1
            checks["control_g1_extra_zero"] += 1
            continue
        assert not gr.is_complete(case, g0["delivered"]), case["case_id"]
        assert gr.is_complete(case, g1["delivered"]), case["case_id"]
        assert not gr.is_complete(case, g2["delivered"]), case["case_id"]
        assert gr.is_complete(case, g3["delivered"]), case["case_id"]
        assert g1["directed_extra"] == 1, case["case_id"]
        checks["g0_incomplete"] += 1
        checks["g1_complete"] += 1
        checks["g2_incomplete"] += 1
        checks["g3_complete"] += 1
    return checks


def generate(out_dir: Path) -> dict:
    cases = build_cases()
    checks = verify(cases)
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = "".join(json.dumps(case, ensure_ascii=False, sort_keys=True) + "\n"
                      for case in cases)
    (out_dir / "cases.jsonl").write_text(payload, encoding="utf-8")
    manifest = {
        "generator": "gen_gap_recall_v1.py",
        "generator_version": GENERATOR_VERSION,
        "cases": len(cases),
        "allocation": gr.ALLOCATION,
        "design_checks": checks,
        "cases_sha256": hashlib.sha256(payload.encode("utf-8")).hexdigest(),
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="eval/fixtures/gap_recall_v1")
    args = parser.parse_args()
    print(json.dumps(generate(Path(args.out)), indent=2, ensure_ascii=False,
                     sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
