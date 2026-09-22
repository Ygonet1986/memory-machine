#!/usr/bin/env python3
"""admission-synthetic-v3 harness: P3v3 = P3v2 with tail cap and removal.

Frozen by docs/ADMISSION_SYNTHETIC_V3_PREREG.md. Same frozen sample as v1;
P0/P1/P2, P3v1 and P3v2 are re-executed from their frozen modules.

    PYTHONPATH=src:.:eval python3 eval/admission_synthetic_v3.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "src"))

import admission_synthetic_v1 as v1  # noqa: E402
import admission_synthetic_v2 as v2  # noqa: E402
from memory_machine.retrieval import tokenize  # noqa: E402

POLICIES = ("P0", "P1", "P2", "P3v1", "P3v2", "P3v3")
MAX_DELIVERIES = 2


def deliver_v3(case: dict[str, Any],
               candidates: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    """P3v2 scoring, then supersession removal, then the 2-candidate cap."""
    if not candidates:
        return [], 0
    best = candidates[0]["score"]
    idf = v1._idf(case["records"])
    question_tokens = set(tokenize(case["question"]))
    hint = v1._type_hint(case["question"])
    question_entities = set(v2.ENTITY_V2_RE.findall(case["question"]))
    newest = max((c["record"]["created_at"] for c in candidates
                  if v1._rare(question_tokens,
                              set(tokenize(v1.record_text(c["record"]))), idf) > 0),
                 default="")

    scored = []
    for candidate in candidates:
        record = candidate["record"]
        text = v1.record_text(record)
        doc_tokens = set(tokenize(text))
        rare = v1._rare(question_tokens, doc_tokens, idf)
        entity = 1.0 if question_entities & set(v2.ENTITY_V2_RE.findall(text)) else 0.0
        temporal = 1.0 if (rare > 0 and record["created_at"] == newest) else 0.0
        correction = v2._correction(text)
        gain = (0.30 * (candidate["score"] / best) + 0.20 * rare
                + 0.15 * entity + 0.15 * temporal
                + 0.10 * v1._type_fit(hint, record["type"])
                + 0.10 * correction)
        scored.append({**candidate, "rare": rare, "correction": correction,
                       "tokens": doc_tokens, "gain": gain})

    corrections = [c for c in scored if c["correction"] == 1.0]
    removed = 0
    if corrections:
        survivors = []
        for candidate in scored:
            superseded = False
            if candidate["correction"] == 0.0:
                for correction in corrections:
                    same_type = candidate["record"]["type"] == correction["record"]["type"]
                    older = candidate["record"]["created_at"] < correction["record"]["created_at"]
                    overlap = len(candidate["tokens"] & correction["tokens"])
                    if same_type and older and overlap >= v2.MIN_SUPERSEDE_OVERLAP:
                        superseded = True
                        break
            if superseded:
                removed += 1
            else:
                survivors.append(candidate)
        scored = survivors

    scored.sort(key=lambda c: (-c["gain"], -c["score"], c["rank"]))
    best_gain = scored[0]["gain"] if scored else 0.0
    floor = v2.RELATIVE_FLOOR * best_gain

    selected: list[dict[str, Any]] = []
    selected_tokens: set[str] = set()
    used = 0
    for candidate in scored:
        if len(selected) >= MAX_DELIVERIES:
            break
        if candidate["rare"] < v2.RARE_FLOOR or candidate["gain"] < floor:
            continue
        union = selected_tokens | candidate["tokens"]
        jaccard = (len(selected_tokens & candidate["tokens"]) / len(union)
                   if union else 0.0)
        gain = candidate["gain"]
        if jaccard > v2.REDUNDANCY:
            gain *= 1.0 - jaccard
        if gain < floor:
            continue
        cost = v1._chars(candidate)
        if used + cost > v2.BUDGET_CHARS:
            continue
        selected.append({**candidate, "gain": gain})
        selected_tokens |= candidate["tokens"]
        used += cost
    return selected, removed


def collect(fixture: Path) -> dict[str, Any]:
    cases = v1.load_cases(fixture)
    per_case: list[dict[str, Any]] = []
    for case in cases:
        candidates = v1.candidates_for(case)
        entry: dict[str, Any] = {"case_id": case["case_id"],
                                 "scenario": case["scenario"],
                                 "gold": case["gold"],
                                 "expectation": case["expectation"],
                                 "policies": {}}
        for policy in ("P0", "P1", "P2", "P3v1"):
            chosen = v1.deliver(case, candidates, policy)
            entry["policies"][policy] = {
                "delivered": [c["record"]["memory_id"] for c in chosen],
                "chars": sum(v1._chars(c) for c in chosen)}
        chosen_v2 = v2.deliver_v2(case, candidates)
        entry["policies"]["P3v2"] = {
            "delivered": [c["record"]["memory_id"] for c in chosen_v2],
            "chars": sum(v1._chars(c) for c in chosen_v2)}
        chosen_v3, removed = deliver_v3(case, candidates)
        entry["policies"]["P3v3"] = {
            "delivered": [c["record"]["memory_id"] for c in chosen_v3],
            "chars": sum(v1._chars(c) for c in chosen_v3),
            "removed_superseded": removed}
        per_case.append(entry)

    report: dict[str, Any] = {
        "prereg": "docs/ADMISSION_SYNTHETIC_V3_PREREG.md",
        "fixture": str(fixture),
        "cases": len(cases),
        "gold_occurrences": sum(len(case["gold"]) for case in cases),
        "policies": {}, "per_case": per_case, "gates": {},
    }
    for policy in POLICIES:
        gold_total = sum(len(case["gold"]) for case in cases)
        gold_hit = delivered = chars = 0
        scenario_hit: dict[str, int] = {}
        scenario_gold: dict[str, int] = {}
        abstain_ok = abstain_total = 0
        max_per_case = 0
        for case, entry in zip(cases, per_case):
            mids = entry["policies"][policy]["delivered"]
            hits = [mid for mid in mids if mid in case["gold"]]
            gold_hit += len(hits)
            delivered += len(mids)
            chars += entry["policies"][policy]["chars"]
            max_per_case = max(max_per_case, len(mids))
            scenario_hit[case["scenario"]] = scenario_hit.get(case["scenario"], 0) + len(hits)
            scenario_gold[case["scenario"]] = scenario_gold.get(case["scenario"], 0) + len(case["gold"])
            if case["expectation"] == "abstain":
                abstain_total += 1
                abstain_ok += 1 if not mids else 0
        report["policies"][policy] = {
            "availability": round(gold_hit / gold_total, 4),
            "precision": round(gold_hit / delivered, 4) if delivered else 0.0,
            "delivered": delivered,
            "mean_chars": round(chars / len(cases), 2),
            "max_per_case": max_per_case,
            "abstention_rate": round(abstain_ok / abstain_total, 4) if abstain_total else 0.0,
            "scenario_availability": {
                scenario: (round(scenario_hit[scenario] / scenario_gold[scenario], 4)
                           if scenario_gold[scenario] else None)
                for scenario in scenario_gold},
        }
    report["removed_superseded_total"] = sum(
        entry["policies"]["P3v3"]["removed_superseded"] for entry in per_case)
    p1, p2, p3v2, p3v3 = (report["policies"][key]
                          for key in ("P1", "P2", "P3v2", "P3v3"))
    deliver_scenarios = [s for s, value in p3v3["scenario_availability"].items()
                         if value is not None]
    report["gates"] = {
        "G1_availability": p3v3["availability"] >= 0.90,
        "G2_precision": p3v3["precision"] >= 0.70,
        "G3_dual_frontier": (p3v3["availability"] > p2["availability"]
                             and p3v3["precision"] > p1["precision"]),
        "G4_abstention": p3v3["abstention_rate"] >= 0.80,
        "G5_scenario_floor": all(
            p3v3["scenario_availability"][s] >= 0.70 for s in deliver_scenarios),
        "G7_beats_v2": (p3v3["availability"] >= p3v2["availability"]
                        and p3v3["precision"] > p3v2["precision"]),
        "G8_cap": p3v3["max_per_case"] <= MAX_DELIVERIES,
    }
    return report


def content_digest(report: dict[str, Any]) -> str:
    blob = json.dumps(report, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def run(fixture: Path) -> dict[str, Any]:
    report = collect(fixture)
    first = content_digest(report)
    second = content_digest(collect(fixture))
    report["determinism"] = {"run1": first, "run2": second,
                             "identical": first == second}
    report["gates"]["G6_determinism"] = first == second
    report["gates"]["all_pass"] = all(report["gates"].values())
    return report


def render_markdown(report: dict[str, Any]) -> list[str]:
    lines = ["# admission-synthetic-v3", "",
             f"- cases: {report['cases']} · gold occurrences: {report['gold_occurrences']}"
             f" · removed superseded (P3v3): {report['removed_superseded_total']}",
             "",
             "| policy | availability | precision | delivered | mean chars | max/case | abstention (S7) |",
             "|---|---:|---:|---:|---:|---:|---:|"]
    for policy in POLICIES:
        data = report["policies"][policy]
        lines.append(f"| {policy} | {data['availability']:.3f} | {data['precision']:.3f} | "
                     f"{data['delivered']} | {data['mean_chars']:.0f} | "
                     f"{data['max_per_case']} | {data['abstention_rate']:.3f} |")
    lines += ["", f"gates: {json.dumps(report['gates'], sort_keys=True)}", "",
              "## Per-scenario availability", "",
              "| scenario | P1 | P2 | P3v1 | P3v2 | P3v3 |",
              "|---|---:|---:|---:|---:|---:|"]
    for scenario in sorted(report["policies"]["P3v3"]["scenario_availability"]):
        row = []
        for policy in ("P1", "P2", "P3v1", "P3v2", "P3v3"):
            value = report["policies"][policy]["scenario_availability"].get(scenario)
            row.append("—" if value is None else f"{value:.2f}")
        lines.append(f"| {scenario} | " + " | ".join(row) + " |")
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture",
                        default=str(HERE / "fixtures" / "admission_synthetic_v1"))
    parser.add_argument("--out",
                        default=str(HERE / "results" / "admission_synthetic_v3"))
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
