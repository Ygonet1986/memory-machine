#!/usr/bin/env python3
"""Deterministic generator for the snippet-window holdout fixture.

12 new cases where the answering fact is buried deep in a long record. The
generator verifies, with the product retriever and the product window, that:
- the fact is beyond the first 400 characters (head snippets miss it);
- `fact_window(text, question, 400)` contains it (query snippets reach it);
- the required record is in the lexical top-5 (L5).
Simulated annotations (A) list decoy records only, reproducing the
annotation-miss pattern the design addresses. No LLM here.

    python3 eval/gen_snippet_holdout_v1.py --out eval/fixtures/snippet_holdout_v1
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

GENERATOR_VERSION = 1
CASES = 12
PROJECTS = ("Vega", "Orion", "Lyra", "Pavo")
SETTINGS = (
    ("migration", "eleven weeks", "How long did the {project} migration take?"),
    ("audit", "$3,400", "What was the final cost of the {project} audit?"),
    ("rollout", "sixteen days", "How many days did the {project} rollout take?"),
    ("training", "$1,250", "How much did the {project} training cost in total?"),
)
FILLERS = (
    "The team aligned on scope and milestones.",
    "A checklist was updated after the review.",
    "Notes were filed for the next planning cycle.",
    "The schedule was adjusted once during the phase.",
    "Stakeholders received a short progress summary.",
    "The vendor confirmed availability for the window.",
)


def _iso(offset: int) -> str:
    return (date(2026, 7, 1) + timedelta(days=offset)).isoformat()


def build_cases() -> list[dict]:
    cases = []
    for index in range(CASES):
        project = PROJECTS[index % len(PROJECTS)]
        topic, answer, question_template = SETTINGS[index % len(SETTINGS)]
        question = question_template.format(project=project)

        segments = []
        for position in range(48):
            if position == 36:
                segments.append(
                    f"In the end the {project} {topic} took {answer} overall, "
                    f"which the team recorded in the closing notes.")
            elif position == 35:
                segments.append(
                    f"The {project} {topic} review covered the delivery steps.")
            elif position == 37:
                segments.append(
                    f"A follow-up on the {project} {topic} was scheduled.")
            else:
                segments.append(FILLERS[position % len(FILLERS)])
        why = "user: I want to close the loop on the current work. " + \
              " ".join(segments)
        record_id = f"K{index + 1:02d}-R01"
        main_record = {
            "memory_id": record_id, "type": "memory",
            "summary": "user: closing notes for the quarter",
            "why": why, "created_at": _iso(index),
        }
        decoys = []
        for number in range(3):
            decoys.append({
                "memory_id": f"K{index + 1:02d}-D{number + 1:02d}",
                "type": "memory",
                "summary": f"user: note about the {project} {topic} planning "
                           f"meeting number {number + 1}",
                "why": f"user: we discussed the {project} {topic} timeline and "
                       f"the review steps for meeting {number + 1}.",
                "created_at": _iso(index + number + 1),
            })
        records = [main_record] + decoys
        cases.append({
            "case_id": f"K{index + 1:02d}", "question": question,
            "gold": answer, "records": records,
            "required": [record_id],
            "simulated_annotations": [d["memory_id"] for d in decoys],
        })
    return cases


def verify(cases: list[dict]) -> None:
    for case in cases:
        by_id = {r["memory_id"]: r for r in case["records"]}
        record = by_id[case["required"][0]]
        text = f"{record['summary']} {record['why']}".strip()
        assert case["gold"].lower() not in text[:400].lower(), case["case_id"]
        assert case["gold"].lower() in text.lower(), case["case_id"]
        snippet = fact_window(text, case["question"], 400)
        assert case["gold"].lower() in snippet.lower(), case["case_id"]
        scores = bm25(case["question"], [f"{r['summary']} {r['why']}"
                                         for r in case["records"]])
        order = sorted(range(len(case["records"])), key=lambda i: -scores[i])
        ranked = [case["records"][i]["memory_id"] for i in order if scores[i] > 0]
        assert case["required"][0] in ranked[:5], case["case_id"]


def generate(out_dir: Path) -> dict:
    cases = build_cases()
    verify(cases)
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = "".join(json.dumps(case, ensure_ascii=False, sort_keys=True) + "\n"
                      for case in cases)
    (out_dir / "cases.jsonl").write_text(payload, encoding="utf-8")
    manifest = {
        "generator": "gen_snippet_holdout_v1.py",
        "generator_version": GENERATOR_VERSION,
        "cases": len(cases),
        "buried_verified": len(cases),
        "cases_sha256": hashlib.sha256(payload.encode("utf-8")).hexdigest(),
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="eval/fixtures/snippet_holdout_v1")
    args = parser.parse_args()
    print(json.dumps(generate(Path(args.out)), indent=2, ensure_ascii=False,
                     sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
