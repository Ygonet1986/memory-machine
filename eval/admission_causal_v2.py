#!/usr/bin/env python3
"""admission-causal-v2 harness: relation slot (exploratory round).

Frozen by docs/ADMISSION_CAUSAL_V2_EXPLORATORY.md. Policy B = P3v4 baseline;
policy S = B + one relation slot for depth-1 `justified_by` evidence on
causal queries, with provenance and no threshold relaxation for others.

    PYTHONPATH=src:.:eval python3 eval/admission_causal_v2.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "src"))

import admission_causal_v1 as v1  # noqa: E402
from memory_machine import admission_p3v4 as p3v4  # noqa: E402
from memory_machine.retrieval import bm25  # noqa: E402

CAUSAL_RE = re.compile(r"\b(why|reason|led|because|justification|explain)\b"
                       r"|\b(motivo|justificativa)\b", re.IGNORECASE)
POLICIES = ("B", "S")
BUDGET_CHARS = 4000
MAX_ITEMS = 3


def slot_evidence(case: dict[str, Any], records: list[Any],
                  lexical: list[Any]) -> tuple[Any | None, str | None, float]:
    """Return (slot candidate, relation source id, bm25 score) or Nones."""
    if not CAUSAL_RE.search(case["question"]):
        return None, None, 0.0
    index = {record["memory_id"]: record for record in case["records"]}
    by_id = {record.id: record for record in records}
    texts = [f"{record.summary} {record.why}".strip() for record in records]
    scores = bm25(case["question"], texts)
    score_by_id = {record.id: float(scores[i]) for i, record in enumerate(records)}
    best: tuple[str, str] | None = None
    best_score = -1.0
    for candidate in lexical[:v1.TOP_FACTUAL]:
        relations = (index.get(candidate.memory_id) or {}).get("relations") or {}
        for target in relations.get("justified_by", []):
            if target not in by_id or candidate.memory_id in (target,):
                continue
            score = score_by_id.get(target, 0.0)
            if score > best_score:
                best_score = score
                best = (target, candidate.memory_id)
    if best is None:
        return None, None, 0.0
    target_id, source_id = best
    record = by_id[target_id]
    text = f"{record.summary} {record.why}".strip()
    candidate = p3v4.Candidate(memory_id=target_id, rank=99, score=best_score,
                               type=record.type, created_at=record.created_at,
                               text=text)
    candidate.chars = len(text) + 8
    return candidate, source_id, best_score


def collect(fixture: Path) -> dict[str, Any]:
    cases = v1.load_cases(fixture)
    per_case: list[dict[str, Any]] = []
    for case in cases:
        records = v1._wrap(case["records"])
        lexical = v1._lexical_candidates(case["question"], records)

        baseline = [v1._fresh(candidate) for candidate in lexical]
        p3v4.decide(case["question"], baseline, records)
        b_ids = p3v4.delivered_ids(baseline)

        slot, source_id, slot_score = slot_evidence(case, records, lexical)
        pool = v1.expanded_pool(case["question"], case, records, lexical)
        p3v4.decide(case["question"], pool, records)
        p3v4_ids = p3v4.delivered_ids(pool)

        s_ids = list(p3v4_ids)
        slot_used = False
        if (slot is not None and slot.memory_id not in s_ids
                and len(s_ids) < MAX_ITEMS):
            used = sum(len(next(r for r in records if r.id == mid).summary) +
                       len(next(r for r in records if r.id == mid).why) + 8
                       for mid in s_ids)
            if used + slot.chars <= BUDGET_CHARS:
                s_ids = [slot.memory_id] + s_ids
                slot_used = True

        per_case.append({"case_id": case["case_id"],
                         "scenario": case["scenario"],
                         "gold": case["gold"],
                         "policies": {"B": b_ids, "S": s_ids},
                         "slot_used": slot_used,
                         "relation_source": source_id,
                         "slot_score": round(slot_score, 4)})

    report: dict[str, Any] = {
        "prereg": "docs/ADMISSION_CAUSAL_V2_EXPLORATORY.md",
        "fixture": str(fixture),
        "cases": len(cases),
        "gold_occurrences": sum(len(case["gold"]) for case in cases),
        "round_type": "exploratory/mechanistic",
        "policies": {}, "per_case": per_case, "requirements": {},
    }
    for policy in POLICIES:
        gold_total = sum(len(case["gold"]) for case in cases)
        gold_hit = delivered = 0
        scenario_hit: dict[str, int] = {}
        scenario_gold: dict[str, int] = {}
        scenario_delivered: dict[str, int] = {}
        absent_undue = absent_delivered = 0
        max_items = 0
        for case, entry in zip(cases, per_case):
            mids = entry["policies"][policy]
            hits = [mid for mid in mids if mid in case["gold"]]
            gold_hit += len(hits)
            delivered += len(mids)
            max_items = max(max_items, len(mids))
            scenario_hit[case["scenario"]] = scenario_hit.get(case["scenario"], 0) + len(hits)
            scenario_gold[case["scenario"]] = scenario_gold.get(case["scenario"], 0) + len(case["gold"])
            scenario_delivered[case["scenario"]] = (
                scenario_delivered.get(case["scenario"], 0) + len(mids))
            if case["scenario"] == "causal_absent":
                absent_delivered += len(mids)
                absent_undue += sum(1 for mid in mids if mid not in case["gold"])
        report["policies"][policy] = {
            "availability": round(gold_hit / gold_total, 4),
            "precision": round(gold_hit / delivered, 4) if delivered else 0.0,
            "delivered": delivered,
            "max_items": max_items,
            "undue_rate": (round(absent_undue / absent_delivered, 4)
                           if absent_delivered else 0.0),
            "scenario_availability": {
                scenario: (round(scenario_hit[scenario] / scenario_gold[scenario], 4)
                           if scenario_gold[scenario] else None)
                for scenario in scenario_gold},
            "scenario_precision": {
                scenario: (round(scenario_hit[scenario] / scenario_delivered[scenario], 4)
                           if scenario_delivered[scenario] else None)
                for scenario in scenario_delivered},
        }
    b, s = report["policies"]["B"], report["policies"]["S"]
    report["requirements"] = {
        "R1_factual_clean": (
            s["scenario_availability"]["factual_control"]
            >= b["scenario_availability"]["factual_control"]),
        "R2_absent_clean": s["undue_rate"] <= b["undue_rate"] + 0.05,
        "R3_budget": s["max_items"] <= MAX_ITEMS,
    }
    report["slot_used_total"] = sum(1 for entry in per_case if entry["slot_used"])
    return report


def content_digest(report: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(report, sort_keys=True,
                                     ensure_ascii=False).encode("utf-8")).hexdigest()


def run(fixture: Path) -> dict[str, Any]:
    report = collect(fixture)
    first = content_digest(report)
    second = content_digest(collect(fixture))
    report["determinism"] = {"run1": first, "run2": second,
                             "identical": first == second}
    report["requirements"]["R4_determinism"] = first == second
    report["requirements"]["all_pass"] = all(report["requirements"].values())
    return report


def render_markdown(report: dict[str, Any]) -> list[str]:
    lines = ["# admission-causal-v2 (exploratory)", "",
             f"- cases: {report['cases']} · gold: {report['gold_occurrences']}"
             f" · slot used: {report['slot_used_total']}",
             "",
             "| policy | availability | precision | delivered | max items | undue (absent) |",
             "|---|---:|---:|---:|---:|---:|"]
    for policy in POLICIES:
        data = report["policies"][policy]
        lines.append(f"| {policy} | {data['availability']:.3f} | {data['precision']:.3f} | "
                     f"{data['delivered']} | {data['max_items']} | {data['undue_rate']:.3f} |")
    lines += ["", f"requirements: {json.dumps(report['requirements'], sort_keys=True)}", "",
              "## Per-scenario availability", "",
              "| scenario | B | S |", "|---|---:|---:|"]
    for scenario in sorted(report["policies"]["S"]["scenario_availability"]):
        row = []
        for policy in POLICIES:
            value = report["policies"][policy]["scenario_availability"].get(scenario)
            row.append("—" if value is None else f"{value:.2f}")
        lines.append(f"| {scenario} | " + " | ".join(row) + " |")
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture",
                        default=str(HERE / "fixtures" / "admission_causal_v1"))
    parser.add_argument("--out",
                        default=str(HERE / "results" / "admission_causal_v2"))
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    report = run(Path(args.fixture))
    (out / "report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8")
    markdown = "\n".join(render_markdown(report)) + "\n"
    (out / "report.md").write_text(markdown, encoding="utf-8")
    print(markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
