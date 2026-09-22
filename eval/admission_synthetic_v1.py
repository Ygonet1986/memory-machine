#!/usr/bin/env python3
"""admission-synthetic-v1 harness: competing admission policies, same cases.

Frozen by docs/ADMISSION_SYNTHETIC_V1_PREREG.md. Policies P0 top1,
P1 margin50, P2 margin90, P3 multisignal (primary). Deterministic; no LLM.

    PYTHONPATH=src:.:eval python3 eval/admission_synthetic_v1.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "src"))

from memory_machine.retrieval import rank, tokenize  # noqa: E402

POLICIES = ("P0", "P1", "P2", "P3")
BUDGET_CHARS = 4000
P3_GAIN_FLOOR = 0.50
P3_RARE_FLOOR = 0.30
P3_REDUNDANCY = 0.60
ENTITY_RE = re.compile(
    r"\b(?:[A-Z]{1,5}-?\d{2,}|v?\d+\.\d+(?:\.\d+)?"
    r"|[\w./-]+\.(?:py|js|ts|json|jsonl|md|csv|yaml|yml|toml|sh))\b")
TYPE_CUES = {
    "decision": ("decided", "decision", "decide", "migrate"),
    "lesson": ("lesson", "learned"),
    "preference": ("preference", "prefers"),
    "build": ("shipped", "version", "pinned", "build"),
}


def load_cases(fixture: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in
            (fixture / "cases.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()]


def record_text(record: dict[str, Any]) -> str:
    return f"{record['summary']} {record['why']}".strip()


def candidates_for(case: dict[str, Any]) -> list[dict[str, Any]]:
    records = case["records"]
    docs = [record_text(record) for record in records]
    out = []
    for index, score in rank(case["question"], docs, limit=5):
        out.append({"record": records[index], "rank": len(out) + 1,
                    "score": float(score)})
    return out


def _idf(records: list[dict[str, Any]]) -> dict[str, float]:
    docs = [set(tokenize(record_text(record))) for record in records]
    total = len(docs)
    df: dict[str, int] = {}
    for tokens in docs:
        for token in tokens:
            df[token] = df.get(token, 0) + 1
    return {token: math.log((total + 1) / (count + 1)) + 1.0
            for token, count in df.items()}


def _rare(question_tokens: set[str], doc_tokens: set[str],
          idf: dict[str, float]) -> float:
    if not question_tokens:
        return 0.0
    total = sum(idf.get(token, 1.0) for token in question_tokens)
    if total <= 0:
        return 0.0
    covered = sum(idf.get(token, 1.0) for token in question_tokens & doc_tokens)
    return covered / total


def _type_hint(question: str) -> str | None:
    tokens = set(tokenize(question))
    for rtype, cues in TYPE_CUES.items():
        if tokens & set(cues):
            return rtype
    return None


def _type_fit(hint: str | None, rtype: str) -> float:
    if hint is None:
        return 0.5
    return 1.0 if rtype == hint else 0.25


def _chars(candidate: dict[str, Any]) -> int:
    record = candidate["record"]
    return len(record["summary"]) + len(record["why"]) + 8


def deliver(case: dict[str, Any], candidates: list[dict[str, Any]],
            policy: str) -> list[dict[str, Any]]:
    if not candidates:
        return []
    best = candidates[0]["score"]
    if policy == "P0":
        return candidates[:1]
    if policy == "P1":
        return [c for c in candidates if c["score"] >= 0.50 * best]
    if policy == "P2":
        return [c for c in candidates if c["score"] >= 0.90 * best]

    idf = _idf(case["records"])
    question_tokens = set(tokenize(case["question"]))
    hint = _type_hint(case["question"])
    newest = max((c["record"]["created_at"] for c in candidates
                  if _rare(question_tokens,
                           set(tokenize(record_text(c["record"]))), idf) > 0),
                 default="")
    scored = []
    for candidate in candidates:
        doc_tokens = set(tokenize(record_text(candidate["record"])))
        rare = _rare(question_tokens, doc_tokens, idf)
        entity = (1.0 if set(ENTITY_RE.findall(case["question"]))
                  & set(ENTITY_RE.findall(record_text(candidate["record"])))
                  else 0.0)
        temporal = 1.0 if (rare > 0
                           and candidate["record"]["created_at"] == newest) else 0.0
        gain = (0.35 * (candidate["score"] / best) + 0.25 * rare
                + 0.15 * entity + 0.15 * temporal
                + 0.10 * _type_fit(hint, candidate["record"]["type"]))
        scored.append({**candidate, "rare": rare, "gain": gain})
    scored.sort(key=lambda c: (-c["gain"], -c["score"], c["rank"]))

    selected: list[dict[str, Any]] = []
    selected_tokens: set[str] = set()
    used = 0
    for candidate in scored:
        if candidate["rare"] < P3_RARE_FLOOR or candidate["gain"] < P3_GAIN_FLOOR:
            continue
        doc_tokens = set(tokenize(record_text(candidate["record"])))
        union = selected_tokens | doc_tokens
        jaccard = len(selected_tokens & doc_tokens) / len(union) if union else 0.0
        gain = candidate["gain"]
        if jaccard > P3_REDUNDANCY:
            gain *= 1.0 - jaccard
        if gain < P3_GAIN_FLOOR:
            continue
        cost = _chars(candidate)
        if used + cost > BUDGET_CHARS:
            continue
        selected.append({**candidate, "gain": gain})
        selected_tokens |= doc_tokens
        used += cost
    return selected


def collect(fixture: Path) -> dict[str, Any]:
    cases = load_cases(fixture)
    per_case: list[dict[str, Any]] = []
    for case in cases:
        candidates = candidates_for(case)
        entry: dict[str, Any] = {"case_id": case["case_id"],
                                 "scenario": case["scenario"],
                                 "gold": case["gold"], "expectation": case["expectation"],
                                 "candidates": [c["record"]["memory_id"] for c in candidates],
                                 "policies": {}}
        for policy in POLICIES:
            chosen = deliver(case, candidates, policy)
            entry["policies"][policy] = {
                "delivered": [c["record"]["memory_id"] for c in chosen],
                "chars": sum(_chars(c) for c in chosen),
            }
        per_case.append(entry)
    report: dict[str, Any] = {
        "prereg": "docs/ADMISSION_SYNTHETIC_V1_PREREG.md",
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
        for case, entry in zip(cases, per_case):
            mids = entry["policies"][policy]["delivered"]
            hits = [mid for mid in mids if mid in case["gold"]]
            gold_hit += len(hits)
            delivered += len(mids)
            chars += entry["policies"][policy]["chars"]
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
            "abstention_rate": round(abstain_ok / abstain_total, 4) if abstain_total else 0.0,
            "scenario_availability": {
                scenario: (round(scenario_hit[scenario] / scenario_gold[scenario], 4)
                           if scenario_gold[scenario] else None)
                for scenario in scenario_gold},
        }
    p1, p2, p3 = (report["policies"][key] for key in ("P1", "P2", "P3"))
    deliver_scenarios = [s for s, value in p3["scenario_availability"].items()
                         if value is not None]
    report["gates"] = {
        "G1_availability": p3["availability"] >= 0.90,
        "G2_precision": p3["precision"] >= 0.70,
        "G3_dual_frontier": (p3["availability"] > p2["availability"]
                             and p3["precision"] > p1["precision"]),
        "G4_abstention": p3["abstention_rate"] >= 0.80,
        "G5_scenario_floor": all(
            p3["scenario_availability"][s] >= 0.70 for s in deliver_scenarios),
    }
    return report


def content_digest(report: dict[str, Any]) -> str:
    blob = json.dumps(report, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def run(fixture: Path) -> dict[str, Any]:
    report = collect(fixture)
    first = content_digest(report)
    second = content_digest(collect(fixture))
    report["determinism"] = {"run1": first, "run2": second, "identical": first == second}
    report["gates"]["G6_determinism"] = first == second
    report["gates"]["all_pass"] = all(report["gates"].values())
    return report


def render_markdown(report: dict[str, Any]) -> list[str]:
    lines = ["# admission-synthetic-v1", "",
             f"- cases: {report['cases']} · gold occurrences: {report['gold_occurrences']}",
             "",
             "| policy | availability | precision | delivered | mean chars | abstention (S7) |",
             "|---|---:|---:|---:|---:|---:|"]
    for policy in POLICIES:
        data = report["policies"][policy]
        lines.append(f"| {policy} | {data['availability']:.3f} | {data['precision']:.3f} | "
                     f"{data['delivered']} | {data['mean_chars']:.0f} | "
                     f"{data['abstention_rate']:.3f} |")
    lines += ["", f"gates: {json.dumps(report['gates'], sort_keys=True)}", "",
              "## Per-scenario availability (P3)", "",
              "| scenario | P0 | P1 | P2 | P3 |", "|---|---:|---:|---:|---:|"]
    scenarios = sorted(report["policies"]["P3"]["scenario_availability"])
    for scenario in scenarios:
        row = []
        for policy in POLICIES:
            value = report["policies"][policy]["scenario_availability"].get(scenario)
            row.append("—" if value is None else f"{value:.2f}")
        lines.append(f"| {scenario} | " + " | ".join(row) + " |")
    lines += ["", "## P3 decisions on hard scenarios", "",
              "| case | scenario | delivered | gold |", "|---|---|---|---|"]
    for entry in report["per_case"]:
        if entry["scenario"] in {"no_answer", "multi_memory", "old_vs_recent",
                                 "corrected", "short_ambiguous"}:
            delivered = ",".join(entry["policies"]["P3"]["delivered"]) or "—"
            gold = ",".join(entry["gold"]) or "—"
            lines.append(f"| {entry['case_id']} | {entry['scenario']} | {delivered} | {gold} |")
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture",
                        default=str(HERE / "fixtures" / "admission_synthetic_v1"))
    parser.add_argument("--out",
                        default=str(HERE / "results" / "admission_synthetic_v1"))
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
