#!/usr/bin/env python3
"""admission-causal-v1 lab harness: causal relation retrieval vs baseline.

Frozen by docs/ADMISSION_CAUSAL_V1_PREREG.md. Isolated lab track.
Policies: B (P3v4 over lexical top-5), K (P3v4 over relation-expanded
candidates, causal cue only), K-abl (expansion for every query).

    PYTHONPATH=src:.:eval python3 eval/admission_causal_v1.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "src"))

from memory_machine import admission_p3v4 as p3v4  # noqa: E402
from memory_machine.retrieval import bm25, tokenize  # noqa: E402

POLICIES = ("B", "K", "K-abl")
CAUSAL_CUES = ("why", "reason", "led", "motivo", "justificativa", "because",
               "justification", "explain")
RELATION_KEYS = ("justified_by", "based_on")
TOP_FACTUAL = 3


def load_cases(fixture: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in
            (fixture / "cases.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()]


def _wrap(records: list[dict[str, Any]]) -> list[Any]:
    return [SimpleNamespace(id=record["memory_id"], type=record["type"],
                            summary=record["summary"], why=record["why"],
                            created_at=record["created_at"], status="active")
            for record in records]


def _by_id(case: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {record["memory_id"]: record for record in case["records"]}


def _has_causal_cue(question: str) -> bool:
    return bool(set(tokenize(question)) & set(CAUSAL_CUES))


def _fresh(candidate: Any) -> Any:
    return p3v4.Candidate(memory_id=candidate.memory_id, rank=candidate.rank,
                          score=candidate.score, type=candidate.type,
                          created_at=candidate.created_at, text=candidate.text)


def _lexical_candidates(question: str, records: list[Any]) -> list[Any]:
    return p3v4.build_candidates(question, records)


def expanded_pool(question: str, case: dict[str, Any], records: list[Any],
                  candidates: list[Any]) -> list[Any]:
    """Candidates + depth-1 justified_by/based_on targets of the top hits."""
    index = {record["memory_id"]: record for record in case["records"]}
    texts = [f"{record.summary} {record.why}".strip() for record in records]
    scores = bm25(question, texts)
    pool = [_fresh(candidate) for candidate in candidates]
    known = {candidate.memory_id for candidate in candidates}
    position = len(pool)
    for candidate in candidates[:TOP_FACTUAL]:
        relations = (index.get(candidate.memory_id) or {}).get("relations") or {}
        for key in RELATION_KEYS:
            for target in relations.get(key, []):
                if target in known or target not in index:
                    continue
                record = next(item for item in records if item.id == target)
                position += 1
                pool.append(p3v4.Candidate(
                    memory_id=target, rank=position,
                    score=float(scores[texts.index(f"{record.summary} {record.why}".strip())]),
                    type=record.type, created_at=record.created_at,
                    text=f"{record.summary} {record.why}".strip()))
                known.add(target)
    return pool


def collect(fixture: Path) -> dict[str, Any]:
    cases = load_cases(fixture)
    per_case: list[dict[str, Any]] = []
    for case in cases:
        records = _wrap(case["records"])
        lexical = _lexical_candidates(case["question"], records)

        baseline = [_fresh(candidate) for candidate in lexical]
        p3v4.decide(case["question"], baseline, records)
        b_ids = p3v4.delivered_ids(baseline)

        pool = (expanded_pool(case["question"], case, records, lexical)
                if _has_causal_cue(case["question"]) else baseline)
        p3v4.decide(case["question"], pool, records)
        k_ids = p3v4.delivered_ids(pool)

        pool_abl = expanded_pool(case["question"], case, records, lexical)
        p3v4.decide(case["question"], pool_abl, records)
        kabl_ids = p3v4.delivered_ids(pool_abl)

        per_case.append({"case_id": case["case_id"],
                         "scenario": case["scenario"],
                         "gold": case["gold"],
                         "policies": {"B": b_ids, "K": k_ids,
                                      "K-abl": kabl_ids}})

    report: dict[str, Any] = {
        "prereg": "docs/ADMISSION_CAUSAL_V1_PREREG.md",
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
        absent_undue = absent_delivered = 0
        for case, entry in zip(cases, per_case):
            mids = entry["policies"][policy]
            hits = [mid for mid in mids if mid in case["gold"]]
            gold_hit += len(hits)
            delivered += len(mids)
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
    b, k, kabl = (report["policies"][key] for key in POLICIES)
    report["gates"] = {
        "G1_availability": k["availability"] >= 0.90,
        "G2_precision": k["precision"] >= 0.70,
        "G3_causal_wins": (
            k["scenario_availability"]["causal_buried"]
            > b["scenario_availability"]["causal_buried"]
            and k["scenario_availability"]["causal_chain"]
            > b["scenario_availability"]["causal_chain"]),
        "G4_factual_unharmed": (
            k["scenario_availability"]["factual_control"]
            >= b["scenario_availability"]["factual_control"]
            and k["scenario_precision"]["factual_control"]
            >= b["scenario_precision"]["factual_control"] - 0.05),
        "G5_negatives": (
            k["scenario_availability"]["causal_absent"]
            >= b["scenario_availability"]["causal_absent"]
            and k["undue_rate"] <= b["undue_rate"] + 0.05),
        "G6_gating_matters": (
            k["undue_rate"] <= kabl["undue_rate"]
            or k["scenario_precision"]["factual_control"]
            >= kabl["scenario_precision"]["factual_control"]),
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
    lines = ["# admission-causal-v1 (lab)", "",
             f"- cases: {report['cases']} · gold occurrences: {report['gold_occurrences']}",
             "",
             "| policy | availability | precision | delivered | undue (absent) |",
             "|---|---:|---:|---:|---:|"]
    for policy in POLICIES:
        data = report["policies"][policy]
        lines.append(f"| {policy} | {data['availability']:.3f} | {data['precision']:.3f} | "
                     f"{data['delivered']} | {data['undue_rate']:.3f} |")
    lines += ["", f"gates: {json.dumps(report['gates'], sort_keys=True)}", "",
              "## Per-scenario availability", "",
              "| scenario | B | K | K-abl |", "|---|---:|---:|---:|"]
    for scenario in sorted(report["policies"]["K"]["scenario_availability"]):
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
                        default=str(HERE / "results" / "admission_causal_v1"))
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
