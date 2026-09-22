#!/usr/bin/env python3
"""admission-portfolio-v1 lab harness: typed slots vs P3v4 (isolated track).

Frozen by docs/ADMISSION_PORTFOLIO_V1_PREREG.md. Policies: P1, P2, P3v4
(frozen module), P4-abl (no slots), P4 (primary, typed portfolio).

    PYTHONPATH=src:.:eval python3 eval/admission_portfolio_v1.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "src"))

from memory_machine import admission_p3v4 as p3v4  # noqa: E402
from memory_machine.retrieval import tokenize  # noqa: E402

POLICIES = ("P1", "P2", "P3v4", "P4-abl", "P4")
CAP = 3
BUDGET_CHARS = 4000
RARE_FLOOR = 0.30
REDUNDANCY = 0.70
PAIR_MIN_SHARED = 3
PAIR_JACCARD = (0.30, 0.70)
PAIR_RARE_FLOOR = 0.40
ORIGIN_CUES = ("where", "from", "source", "origin", "came", "comes",
               "veio", "quem")
PROVENANCE_RE = re.compile(
    r"source|documented|paper|readme|commit|according to|per the",
    re.IGNORECASE)


def load_cases(fixture: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in
            (fixture / "cases.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()]


def _wrap(records: list[dict[str, Any]]) -> list[Any]:
    """Adapt fixture dicts to the record interface the frozen module expects."""
    return [SimpleNamespace(id=record["memory_id"], type=record["type"],
                            summary=record["summary"], why=record["why"],
                            created_at=record["created_at"],
                            status="active")
            for record in records]


def _margin(candidates: list[Any], fraction: float) -> list[str]:
    if not candidates:
        return []
    best = candidates[0].score
    return [c.memory_id for c in candidates if c.score >= fraction * best]


def _tokens(case: dict[str, Any], memory_id: str) -> set[str]:
    plain = memory_id.split("-")[0]
    for record in case["records"]:
        if record["memory_id"] == memory_id:
            return set(tokenize(f"{record['summary']} {record['why']}"))
    return set()


def _add(selected: list[Any], candidate: Any, used: int) -> int:
    selected.append(candidate)
    return used + candidate.chars


def select_ablation(survivors: list[Any]) -> list[Any]:
    selected: list[Any] = []
    tokens: set[str] = set()
    used = 0
    for candidate in survivors:
        if len(selected) >= CAP:
            break
        if candidate.rare < RARE_FLOOR:
            continue
        union = tokens | set(tokenize(candidate.text))
        jaccard = len(tokens & set(tokenize(candidate.text))) / len(union) if union else 0.0
        if jaccard > REDUNDANCY:
            continue
        if used + candidate.chars > BUDGET_CHARS:
            continue
        used = _add(selected, candidate, used)
        tokens |= set(tokenize(candidate.text))
    return selected


def select_portfolio(case: dict[str, Any], survivors: list[Any]) -> list[Any]:
    selected: list[Any] = []
    used = 0
    question_tokens = set(tokenize(case["question"]))

    def add(candidate: Any) -> None:
        nonlocal used
        if candidate is None or candidate in selected or len(selected) >= CAP:
            return
        if used + candidate.chars > BUDGET_CHARS:
            return
        used = _add(selected, candidate, used)

    corrections = [c for c in survivors if c.correction]
    if corrections:
        add(max(corrections, key=lambda c: (c.gain, -c.rank)))

    current = [c for c in survivors if c.temporal]
    if current:
        add(max(current, key=lambda c: (c.gain, -c.rank)))

    best_pair = None
    best_pair_score = -1.0
    for a in survivors:
        for b in survivors:
            if a is b or a in selected or b in selected:
                continue
            if a.rare < PAIR_RARE_FLOOR or b.rare < PAIR_RARE_FLOOR:
                continue
            ta, tb = set(tokenize(a.text)), set(tokenize(b.text))
            shared = ta & tb
            union = ta | tb
            jaccard = len(shared) / len(union) if union else 0.0
            if len(shared) >= PAIR_MIN_SHARED and PAIR_JACCARD[0] <= jaccard <= PAIR_JACCARD[1]:
                score = a.gain + b.gain
                if score > best_pair_score:
                    best_pair_score = score
                    best_pair = (a, b)
    if best_pair is not None and len(selected) + 2 <= CAP:
        first, second = sorted(best_pair, key=lambda c: (-c.gain, c.rank))
        add(first)
        add(second)

    if question_tokens & set(ORIGIN_CUES):
        origins = [c for c in survivors
                   if c not in selected and PROVENANCE_RE.search(c.text)]
        if origins:
            add(max(origins, key=lambda c: (c.gain, -c.rank)))

    tokens = set()
    for candidate in selected:
        tokens |= set(tokenize(candidate.text))
    for candidate in survivors:
        if len(selected) >= CAP:
            break
        if candidate in selected or candidate.rare < RARE_FLOOR:
            continue
        doc_tokens = set(tokenize(candidate.text))
        union = tokens | doc_tokens
        jaccard = len(tokens & doc_tokens) / len(union) if union else 0.0
        if jaccard > REDUNDANCY:
            continue
        add(candidate)
        tokens |= doc_tokens
    return selected


def collect(fixture: Path) -> dict[str, Any]:
    cases = load_cases(fixture)
    per_case: list[dict[str, Any]] = []
    for case in cases:
        records = _wrap(case["records"])
        candidates = p3v4.build_candidates(case["question"], records)
        p3v4.decide(case["question"], candidates, records)
        survivors = [c for c in candidates if not c.removed_superseded]
        entries = {
            "P1": _margin(candidates, 0.50),
            "P2": _margin(candidates, 0.90),
            "P3v4": p3v4.delivered_ids(candidates),
            "P4-abl": [c.memory_id for c in select_ablation(survivors)],
            "P4": [c.memory_id for c in select_portfolio(case, survivors)],
        }
        per_case.append({"case_id": case["case_id"],
                         "scenario": case["scenario"],
                         "gold": case["gold"],
                         "expectation": case["expectation"],
                         "policies": {name: {"delivered": ids}
                                      for name, ids in entries.items()}})

    report: dict[str, Any] = {
        "prereg": "docs/ADMISSION_PORTFOLIO_V1_PREREG.md",
        "fixture": str(fixture),
        "cases": len(cases),
        "gold_occurrences": sum(len(case["gold"]) for case in cases),
        "policies": {}, "per_case": per_case, "gates": {},
    }
    for policy in POLICIES:
        gold_total = sum(len(case["gold"]) for case in cases)
        gold_hit = delivered = 0
        scenario_hit: dict[str, int] = {}
        scenario_gold: dict[str, int] = {}
        scenario_delivered: dict[str, int] = {}
        abstain_ok = abstain_total = 0
        max_per_case = 0
        for case, entry in zip(cases, per_case):
            mids = entry["policies"][policy]["delivered"]
            hits = [mid for mid in mids if mid in case["gold"]]
            gold_hit += len(hits)
            delivered += len(mids)
            max_per_case = max(max_per_case, len(mids))
            scenario_hit[case["scenario"]] = scenario_hit.get(case["scenario"], 0) + len(hits)
            scenario_gold[case["scenario"]] = scenario_gold.get(case["scenario"], 0) + len(case["gold"])
            scenario_delivered[case["scenario"]] = (
                scenario_delivered.get(case["scenario"], 0) + len(mids))
            if case["expectation"] == "abstain":
                abstain_total += 1
                abstain_ok += 1 if not mids else 0
        report["policies"][policy] = {
            "availability": round(gold_hit / gold_total, 4),
            "precision": round(gold_hit / delivered, 4) if delivered else 0.0,
            "delivered": delivered,
            "max_per_case": max_per_case,
            "abstention_rate": round(abstain_ok / abstain_total, 4) if abstain_total else 0.0,
            "scenario_availability": {
                scenario: (round(scenario_hit[scenario] / scenario_gold[scenario], 4)
                           if scenario_gold[scenario] else None)
                for scenario in scenario_gold},
            "scenario_precision": {
                scenario: (round(scenario_hit[scenario] / scenario_delivered[scenario], 4)
                           if scenario_delivered[scenario] else None)
                for scenario in scenario_delivered},
        }
    p1, p3v4_res, abl, p4 = (report["policies"][key]
                             for key in ("P1", "P3v4", "P4-abl", "P4"))
    report["gates"] = {
        "G1_availability": p4["availability"] >= 0.90,
        "G2_precision": p4["precision"] >= 0.70,
        "G3_beats_p3v4": (p4["availability"] > p3v4_res["availability"]
                          and p4["precision"] >= p3v4_res["precision"] - 0.05),
        "G4_targeted_wins": (
            p4["scenario_availability"]["contradiction"]
            > p3v4_res["scenario_availability"]["contradiction"]
            and p4["scenario_availability"]["origin"]
            > p3v4_res["scenario_availability"]["origin"]),
        "G5_slots_are_the_cause": (
            (p4["scenario_availability"]["contradiction"]
             > abl["scenario_availability"]["contradiction"]
             or p4["scenario_availability"]["origin"]
             > abl["scenario_availability"]["origin"])
            and all(p4["scenario_availability"][s] >= abl["scenario_availability"][s]
                    for s in ("contradiction", "origin"))),
        "G6_cap_and_budget": p4["max_per_case"] <= CAP,
    }
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
    report["gates"]["G7_determinism"] = first == second
    report["gates"]["all_pass"] = all(report["gates"].values())
    return report


def render_markdown(report: dict[str, Any]) -> list[str]:
    lines = ["# admission-portfolio-v1 (lab)", "",
             f"- cases: {report['cases']} · gold occurrences: {report['gold_occurrences']}",
             "",
             "| policy | availability | precision | delivered | max/case | abstention |",
             "|---|---:|---:|---:|---:|---:|"]
    for policy in POLICIES:
        data = report["policies"][policy]
        lines.append(f"| {policy} | {data['availability']:.3f} | {data['precision']:.3f} | "
                     f"{data['delivered']} | {data['max_per_case']} | "
                     f"{data['abstention_rate']:.3f} |")
    lines += ["", f"gates: {json.dumps(report['gates'], sort_keys=True)}", "",
              "## Per-scenario availability", "",
              "| scenario | P3v4 | P4-abl | P4 |", "|---|---:|---:|---:|"]
    for scenario in sorted(report["policies"]["P4"]["scenario_availability"]):
        row = []
        for policy in ("P3v4", "P4-abl", "P4"):
            value = report["policies"][policy]["scenario_availability"].get(scenario)
            row.append("—" if value is None else f"{value:.2f}")
        lines.append(f"| {scenario} | " + " | ".join(row) + " |")
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture",
                        default=str(HERE / "fixtures" / "admission_portfolio_v1"))
    parser.add_argument("--out",
                        default=str(HERE / "results" / "admission_portfolio_v1"))
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
