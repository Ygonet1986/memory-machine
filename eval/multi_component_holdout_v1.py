#!/usr/bin/env python3
"""multi-component-holdout-v1: W6c on two-distant-value questions (M1-M5).

Frozen by docs/MULTI_COMPONENT_HOLDOUT_V1_PREREG.md. Deterministic delivery
stage plus a 36-call answer gate on L01-L03.

    PYTHONPATH=src:.:eval python3 eval/multi_component_holdout_v1.py --skip-llm
    PYTHONPATH=src:.:eval python3 eval/multi_component_holdout_v1.py
"""

from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "src"))

import component_allocation_v1 as ca  # noqa: E402
import delivery_combined_v1 as dc  # noqa: E402
import numeral_inclusion_v1 as ni  # noqa: E402

FIXTURE = HERE / "fixtures" / "multi_component_holdout_v1"
ALLOCATION = 3600
ARMS = ("W4", "W6c")
ANSWER_CASES = ("L01", "L02", "L03")
RUNS = 3
W6C_SOURCE_SHA = hashlib.sha256(
    inspect.getsource(ca.w6c_window).encode()).hexdigest()


def load_cases() -> list[dict[str, Any]]:
    return [json.loads(line) for line in
            (FIXTURE / "cases.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()]


def delivered_item(case: dict[str, Any], arm: str) -> str:
    record = case["records"][0]
    room = ALLOCATION - len(record["summary"]) - 1
    window = ni.w4_window if arm == "W4" else ca.w6c_window
    body = window(str(record["why"]), case["question"], room)
    return f"{record['summary']}\n{body}"


def delivery_stage(cases: list[dict[str, Any]]) -> dict[str, Any]:
    rows = []
    for case in cases:
        value_a, value_b = case["components"]
        for arm in ARMS:
            text = delivered_item(case, arm)
            both = f"${value_a}" in text and f"${value_b}" in text
            rows.append({"case_id": case["case_id"], "arm": arm,
                         "both": both, "chars": len(text),
                         "gold": case["gold"]})
    w4_both = sum(1 for r in rows if r["arm"] == "W4" and r["both"])
    w6c_both = sum(1 for r in rows if r["arm"] == "W6c" and r["both"])
    report = {
        "prereg": "docs/MULTI_COMPONENT_HOLDOUT_V1_PREREG.md",
        "w6c_source_sha256": W6C_SOURCE_SHA,
        "rows": rows, "w4_both": w4_both, "w6c_both": w6c_both,
        "gates": {"M1_w6c_both": w6c_both >= 10,
                  "M2_strict_advantage": w6c_both > w4_both,
                  "M4_budget": all(r["chars"] <= ALLOCATION for r in rows)},
    }
    return report


def answer_stage(cases: list[dict[str, Any]]) -> dict[str, Any]:
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
    config = Config()
    answerer = CountingClient(LLMClient("https://api.deepseek.com", key,
                                        config.model, retries=1))
    judge_client = CountingClient(LLMClient("https://api.deepseek.com", key,
                                            config.model, retries=1))
    by_id = {case["case_id"]: case for case in cases}
    entries = []
    failures = 0
    for case_id in ANSWER_CASES:
        case = by_id[case_id]
        entry = {"case_id": case_id, "gold": case["gold"], "arms": {}}
        for arm in ARMS:
            text = delivered_item(case, arm)
            verdicts = []
            for _ in range(RUNS):
                whiteboard = Whiteboard()
                whiteboard.subject = case["question"]
                try:
                    reply, _m, _r = run_main_chatbot(
                        answerer, whiteboard, case["question"],
                        extra_context=text, temperature=0.0)
                    verdict, _reason = judge(judge_client, case["question"],
                                             str(case["gold"]), reply.strip())
                except Exception as error:
                    verdict = f"infra_error:{type(error).__name__}"
                    failures += 1
                verdicts.append(verdict)
            entry["arms"][arm] = verdicts
        entries.append(entry)

    def score(case_id: str, arm: str) -> float:
        entry = next(e for e in entries if e["case_id"] == case_id)
        return sum({"correct": 1.0, "partial": 0.5}.get(v, 0.0)
                   for v in entry["arms"][arm]) / RUNS

    score_w4 = sum(score(cid, "W4") for cid in ANSWER_CASES)
    score_w6c = sum(score(cid, "W6c") for cid in ANSWER_CASES)
    return {"cases": entries, "score_w4": round(score_w4, 4),
            "score_w6c": round(score_w6c, 4),
            "llm_calls": answerer.calls + judge_client.calls,
            "failures": failures,
            "gates": {"M3_answers": score_w6c > score_w4,
                      "M5_infra": failures <= 0.2 * RUNS * len(ARMS) * len(ANSWER_CASES)}}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out",
                        default=str(HERE / "results" / "multi_component_holdout_v1"))
    parser.add_argument("--skip-llm", action="store_true")
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    cases = load_cases()
    report = delivery_stage(cases)
    second = delivery_stage(cases)
    report["gates"]["M4_determinism"] = (
        json.dumps(report["rows"], sort_keys=True)
        == json.dumps(second["rows"], sort_keys=True))
    if not args.skip_llm:
        report["answer"] = answer_stage(cases)
        report["gates"].update(report["answer"]["gates"])
    report["all_pass"] = all(report["gates"].values())
    (out / "report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8")
    lines = ["# multi-component-holdout-v1", "",
             f"- both-components: W4 {report['w4_both']}/12 vs W6c "
             f"{report['w6c_both']}/12", ""]
    if "answer" in report:
        lines += ["| case | W4 | W6c |", "|---|---|---|"]
        for entry in report["answer"]["cases"]:
            lines.append(f"| {entry['case_id']} | "
                         f"{'/'.join(entry['arms']['W4'])} | "
                         f"{'/'.join(entry['arms']['W6c'])} |")
        lines += [f"- scores: W4 {report['answer']['score_w4']} vs W6c "
                  f"{report['answer']['score_w6c']}", ""]
    lines += [f"gates: {json.dumps(report['gates'], sort_keys=True)}",
              f"all_pass: {report['all_pass']}"]
    markdown = "\n".join(lines) + "\n"
    (out / "report.md").write_text(markdown, encoding="utf-8")
    print(markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
