#!/usr/bin/env python3
"""agent-index-v1: metadata routing vs all vs union (G1-G6).

Frozen by docs/AGENT_INDEX_V1_PREREG.md (+ Amendment 1). Routing is
deterministic; the answer gate runs 4 declared cases across 3 arms N=3.

    PYTHONPATH=src:.:eval python3 eval/agent_index_v1.py --skip-llm
    PYTHONPATH=src:.:eval python3 eval/agent_index_v1.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "src"))

import delivery_combined_v1 as dc  # noqa: E402
from memory_machine.payload import fact_window  # noqa: E402
from memory_machine.retrieval import bm25  # noqa: E402

FIXTURE = HERE / "fixtures" / "agent_index_v1"
ARMS = ("A0", "A1", "A2")
RUNS = 3


def load_cases() -> list[dict[str, Any]]:
    return [json.loads(line) for line in
            (FIXTURE / "cases.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()]


def consulted_partitions(case: dict[str, Any], arm: str) -> list[str]:
    checks = case["checks"]
    if arm == "A0":
        return [p["partition_id"] for p in case["partitions"]]
    if arm == "A1":
        return [checks["top1_partition"]]
    return sorted({checks["top1_partition"],
                   *checks["lexical_partitions_top3"]})


def context_for(case: dict[str, Any], arm: str,
                records: dict[tuple[int, str], dict]) -> tuple[str, list[str]]:
    selected = set(consulted_partitions(case, arm))
    items = [rid for part in case["partitions"]
             if part["partition_id"] in selected for rid in part["record_ids"]]
    texts = {rid: f"{records[(case['case'], rid)]['summary']} "
                 f"{records[(case['case'], rid)]['why']}".strip()
             for rid in items}
    scores = bm25(case["question"], [texts[rid] for rid in items])
    order = sorted(range(len(items)), key=lambda i: -scores[i])
    top = [items[i] for i in order[:5]]
    blocks = []
    for rid in top:
        snippet = fact_window(texts[rid], case["question"], 400)
        blocks.append(f"[{rid} | memory] {snippet}")
    return "\n\n".join(blocks), top


def routing_stage(cases: list[dict[str, Any]]) -> dict[str, Any]:
    rows = []
    for case in cases:
        required = set(case["required"])
        entry = {"block": case["block"], "case": case["case"],
                 "required": sorted(required), "arms": {}}
        for arm in ARMS:
            selected = consulted_partitions(case, arm)
            hosted = {rid for part in case["partitions"]
                      if part["partition_id"] in set(selected)
                      for rid in part["record_ids"]}
            entry["arms"][arm] = {
                "consulted": selected,
                "routing_coverage": round(len(required & hosted) / len(required), 4)
                if required else 1.0,
                "covered": required.issubset(hosted),
            }
        rows.append(entry)

    def coverage(arm: str) -> float:
        values = [e["arms"][arm]["routing_coverage"] for e in rows]
        return round(sum(values) / len(values), 4) if values else 0.0

    calls = {arm: sum(len(e["arms"][arm]["consulted"]) for e in rows)
             for arm in ARMS}
    report = {
        "prereg": "docs/AGENT_INDEX_V1_PREREG.md",
        "cases": len(rows), "rows": rows,
        "routing_coverage": {arm: coverage(arm) for arm in ARMS},
        "consulted_partitions": calls,
        "gates": {
            "G1_no_case_lost": all(e["arms"]["A2"]["covered"]
                                   or not e["arms"]["A0"]["covered"]
                                   for e in rows),
            "G2_advantage": coverage("A2") > coverage("A1"),
            "G3_fewer_calls": calls["A2"] < calls["A0"],
        },
    }
    return report


def answer_cases(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    misses = [e for e in cases if e["checks"]["a1_miss"]]
    hits = [e for e in cases if not e["checks"]["a1_miss"]]
    misses.sort(key=lambda e: (e["block"], e["case"]))
    hits.sort(key=lambda e: (e["block"], e["case"]))
    return misses[:3] + hits[:1]


def answer_stage(report: dict[str, Any]) -> dict[str, Any]:
    from memory_machine.config import Config
    from memory_machine.llm import LLMClient
    from memory_machine.main_chatbot import run_main_chatbot
    from memory_machine.whiteboard import Whiteboard
    from e2e_bench import judge
    from view_router_bench import CountingClient
    import os

    key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not key:
        raise RuntimeError("DEEPSEEK_API_KEY is not set")
    cases = load_cases()
    source_cases, records = dc.load_fixture(HERE / "fixtures" / "composition_u4")
    gold_by_case = {(c["block"], c["case"]): str(c["gold"])
                    for c in source_cases}
    selected = answer_cases(cases)
    config = Config()
    answerer = CountingClient(LLMClient("https://api.deepseek.com", key,
                                        config.model, retries=1))
    judge_client = CountingClient(LLMClient("https://api.deepseek.com", key,
                                            config.model, retries=1))
    entries = []
    failures = 0
    for case in selected:
        gold = gold_by_case[(case["block"], case["case"])]
        entry = {"block": case["block"], "case": case["case"],
                 "gold": gold, "question": case["question"], "arms": {}}
        for arm in ARMS:
            context, _top = context_for(case, arm, records)
            verdicts = []
            for _ in range(RUNS):
                whiteboard = Whiteboard()
                whiteboard.subject = case["question"]
                try:
                    reply, _m, _r = run_main_chatbot(
                        answerer, whiteboard, case["question"],
                        extra_context=context, temperature=0.0)
                    verdict, _reason = judge(judge_client, case["question"],
                                             gold, reply.strip())
                except Exception as error:
                    verdict = f"infra_error:{type(error).__name__}"
                    failures += 1
                verdicts.append(verdict)
            entry["arms"][arm] = verdicts
        entries.append(entry)

    def score(arm: str) -> float:
        total = 0.0
        for entry in entries:
            total += sum({"correct": 1.0, "partial": 0.5}.get(v, 0.0)
                         for v in entry["arms"][arm]) / RUNS
        return round(total / len(entries), 4) if entries else 0.0

    scores = {arm: score(arm) for arm in ARMS}
    report["answer"] = {
        "cases": entries, "scores": scores,
        "llm_calls": answerer.calls + judge_client.calls,
        "failures": failures,
    }
    report["gates"]["G4_answers"] = scores["A2"] >= scores["A0"] - 0.05
    report["gates"]["G6_infra"] = failures <= 0.2 * RUNS * len(ARMS) * len(selected)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out",
                        default=str(HERE / "results" / "agent_index_v1"))
    parser.add_argument("--skip-llm", action="store_true")
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    cases = load_cases()
    report = routing_stage(cases)
    second = routing_stage(cases)
    report["gates"]["G5_determinism"] = (
        json.dumps(report["rows"], sort_keys=True)
        == json.dumps(second["rows"], sort_keys=True))
    if not args.skip_llm:
        report = answer_stage(report)
    report["all_pass"] = all(report["gates"].values())
    report["scope_limit"] = ("K=2 artificial partitions per case test the "
                             "routing mechanism; no real-tape call savings "
                             "are demonstrated")
    (out / "report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8")
    lines = ["# agent-index-v1", "",
             f"- cases: {report['cases']} · routing coverage: "
             f"{json.dumps(report['routing_coverage'], sort_keys=True)}",
             f"- consulted partitions: "
             f"{json.dumps(report['consulted_partitions'], sort_keys=True)}"]
    if "answer" in report:
        lines += [f"- answer scores: {json.dumps(report['answer']['scores'], sort_keys=True)}",
                  f"- calls: {report['answer']['llm_calls']} · failures: "
                  f"{report['answer']['failures']}"]
    lines += ["", f"gates: {json.dumps(report['gates'], sort_keys=True)}",
              f"all_pass: {report['all_pass']}",
              "", f"scope: {report['scope_limit']}"]
    markdown = "\n".join(lines) + "\n"
    (out / "report.md").write_text(markdown, encoding="utf-8")
    print(markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
