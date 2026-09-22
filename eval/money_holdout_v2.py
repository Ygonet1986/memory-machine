#!/usr/bin/env python3
"""money-holdout-v2: corrected W4 holdout (Y1-Y6).

Frozen by docs/MONEY_HOLDOUT_V2_PREREG.md. Deterministic delivery stage plus
a 36-call repeated-answer gate on three cases.

    PYTHONPATH=src:.:eval python3 eval/money_holdout_v2.py --skip-llm
    PYTHONPATH=src:.:eval python3 eval/money_holdout_v2.py
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

import delivery_anchors_v1 as da  # noqa: E402
import delivery_combined_v1 as dc  # noqa: E402
import numeral_inclusion_v1 as ni  # noqa: E402
import phrase_delivery_v1 as pd  # noqa: E402
from fact_presence import item_span, norm  # noqa: E402

FIXTURE = HERE / "fixtures" / "money_holdout_v2"
ALLOCATION = 3600
ARMS = ("W1", "W4")
ANSWER_CASES = ("G01", "G02", "G03")
RUNS = 3
W4_SOURCE_SHA = "9023e734b94684bd9fdbb2b413c43b85a9f40ee6862465a45b146e4e4da5a707"


def load_cases() -> list[dict[str, Any]]:
    return [json.loads(line) for line in
            (FIXTURE / "cases.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()]


def delivered_item(case: dict[str, Any], arm: str) -> str:
    record = case["records"][0]
    room = ALLOCATION - len(record["summary"]) - 1
    window = da.fact_window if arm == "W1" else ni.w4_window
    body = window(str(record["why"]), case["question"], room)
    return f"{record['summary']}\n{body}"


def delivery_stage(cases: list[dict[str, Any]]) -> dict[str, Any]:
    rows = []
    for case in cases:
        for arm in ARMS:
            text = delivered_item(case, arm)
            present = pd.phrase_present((str(case["target"]), "$"), text)
            rows.append({"case_id": case["case_id"], "arm": arm,
                         "position": case["position"], "gold": case["gold"],
                         "present": present, "chars": len(text)})
    w1 = [r for r in rows if r["arm"] == "W1"]
    w4 = [r for r in rows if r["arm"] == "W4"]
    w1_hits = sum(1 for r in w1 if r["present"])
    w4_hits = sum(1 for r in w4 if r["present"])
    middle_late = [r for r in w4 if r["position"] in ("middle", "late")]
    w1_middle_late = [r for r in w1 if r["position"] in ("middle", "late")]
    y2 = (w4_hits > w1_hits
          and all(r["present"] for r in middle_late)
          and all(not r["present"] for r in w1_middle_late))

    # external component check (u3a-24)
    comp_cases, comp_records = dc.load_fixture(HERE / "fixtures" / "composition_u4")
    case24 = next(c for c in comp_cases
                  if (c["block"], c["case"]) == ("u3a", 24))
    contexts = {"W1": dc.contexts(case24, comp_records)["W1"],
                "W4": ni.rebuild(case24, comp_records, "W4")}
    external = {}
    for arm, ctx in contexts.items():
        union = " ".join(norm(item_span(ctx, mid)[0])
                         for mid in case24["required_ids"])
        external[arm] = {"1000": "1000" in union, "300": "300" in union}
    y3 = external["W4"]["1000"] and external["W4"]["300"]

    source_sha = hashlib.sha256(inspect.getsource(ni.w4_window).encode()).hexdigest()
    report = {
        "prereg": "docs/MONEY_HOLDOUT_V2_PREREG.md",
        "w4_source_sha256": source_sha,
        "w4_unchanged": source_sha == W4_SOURCE_SHA,
        "rows": rows, "w1_hits": w1_hits, "w4_hits": w4_hits,
        "external_u3a24": external,
        "gates": {"Y1_w4_full": w4_hits == 12,
                  "Y2_beats_w1": y2,
                  "Y3_components": y3,
                  "Y4_budget": all(r["chars"] <= ALLOCATION for r in rows)},
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

    y5 = sum(score(case_id, "W4") for case_id in ANSWER_CASES) >= \
        sum(score(case_id, "W1") for case_id in ANSWER_CASES) - \
        0.05 * len(ANSWER_CASES)
    return {"cases": entries, "llm_calls": answerer.calls + judge_client.calls,
            "failures": failures,
            "gates": {"Y5_answers": y5,
                      "Y6_infra": failures <= 0.2 * RUNS * len(ARMS) * len(ANSWER_CASES)}}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out",
                        default=str(HERE / "results" / "money_holdout_v2"))
    parser.add_argument("--skip-llm", action="store_true")
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    cases = load_cases()
    report = delivery_stage(cases)
    second = delivery_stage(cases)
    report["gates"]["Y4_determinism"] = (
        json.dumps(report["rows"], sort_keys=True)
        == json.dumps(second["rows"], sort_keys=True))
    if report["w4_unchanged"] and not args.skip_llm:
        report["answer"] = answer_stage(cases)
        report["gates"].update(report["answer"]["gates"])
    report["all_pass"] = all(report["gates"].values())
    (out / "report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8")
    lines = ["# money-holdout-v2", "",
             f"- W1 hits: {report['w1_hits']}/12 · W4 hits: "
             f"{report['w4_hits']}/12 · external: "
             f"{json.dumps(report['external_u3a24'], sort_keys=True)}", "",
             "| case | pos | W1 | W4 |", "|---|---|---|---|"]
    for case in cases:
        w1 = next(r for r in report["rows"]
                  if r["case_id"] == case["case_id"] and r["arm"] == "W1")
        w4 = next(r for r in report["rows"]
                  if r["case_id"] == case["case_id"] and r["arm"] == "W4")
        lines.append(f"| {case['case_id']} | {case['position']} | "
                     f"{'ok' if w1['present'] else 'MISS'} | "
                     f"{'ok' if w4['present'] else 'MISS'} |")
    if "answer" in report:
        lines += ["", "| case | W1 | W4 |", "|---|---|---|"]
        for entry in report["answer"]["cases"]:
            lines.append(f"| {entry['case_id']} | "
                         f"{'/'.join(entry['arms']['W1'])} | "
                         f"{'/'.join(entry['arms']['W4'])} |")
    lines += ["", f"gates: {json.dumps(report['gates'], sort_keys=True)}",
              f"all_pass: {report['all_pass']}"]
    markdown = "\n".join(lines) + "\n"
    (out / "report.md").write_text(markdown, encoding="utf-8")
    print(markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
