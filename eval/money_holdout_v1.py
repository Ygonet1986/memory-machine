#!/usr/bin/env python3
"""money-holdout-v1: frozen W4 tested once on the money holdout fixture.

Frozen by docs/MONEY_HOLDOUT_V1_PREREG.md. The rule is imported unchanged
from numeral_inclusion_v1 (source hash pinned). Deterministic delivery
stage; repeated answer stage on H01-H03.

    PYTHONPATH=src:.:eval python3 eval/money_holdout_v1.py --skip-llm
    PYTHONPATH=src:.:eval python3 eval/money_holdout_v1.py
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

ALLOCATION = 3600
ARMS = ("W1", "W4")
ANSWER_CASES = ("H01", "H02", "H03")
RUNS = 3
W4_SOURCE_SHA = "9023e734b94684bd9fdbb2b413c43b85a9f40ee6862465a45b146e4e4da5a707"


def load_holdout(fixture: Path) -> list[dict]:
    return [json.loads(line) for line in
            (fixture / "cases.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()]


def delivered_item(case: dict, arm: str) -> str:
    record = case["records"][0]
    room = ALLOCATION - len(record["summary"]) - 1
    window = da.fact_window if arm == "W1" else ni.w4_window
    body = window(str(record["why"]), case["question"], room)
    return f"{record['summary']}\n{body}"


def delivery_stage(cases: list[dict]) -> dict[str, Any]:
    rows = []
    for case in cases:
        for arm in ARMS:
            text = delivered_item(case, arm)
            present = pd.phrase_present((str(case["target"]), "$"), text)
            rows.append({"case_id": case["case_id"], "arm": arm,
                         "position": case["position"], "gold": case["gold"],
                         "present": present, "chars": len(text)})
    # external check: u3a-24 from the composition fixture
    comp_cases, comp_records = dc.load_fixture(HERE / "fixtures" / "composition_u4")
    case24 = next(c for c in comp_cases if (c["block"], c["case"]) == ("u3a", 24))
    contexts = {"W1": dc.contexts(case24, comp_records)["W1"],
                "W4": ni.rebuild(case24, comp_records, "W4")}
    external = {}
    for arm in ARMS:
        result = pd.check(case24, contexts[arm], comp_records)
        external[arm] = {"ok": result["ok"], "basis": result["basis"]}

    def present_count(arm: str) -> int:
        return sum(1 for row in rows if row["arm"] == arm and row["present"])

    w1_count, w4_count = present_count("W1"), present_count("W4")
    positions = {}
    for position in ("early", "middle", "late"):
        w1_miss = [r for r in rows if r["arm"] == "W1"
                   and r["position"] == position and not r["present"]]
        w4_hit = [r for r in rows if r["arm"] == "W4"
                  and r["position"] == position and r["present"]]
        positions[position] = {"w1_missing": len(w1_miss),
                               "w4_present": len(w4_hit)}
    h1 = w4_count >= 10 and w4_count > w1_count
    fails = {p: v for p, v in positions.items() if v["w1_missing"] > 0}
    h2 = all(v["w4_present"] >= 1 for v in fails.values()) if fails else False
    h3 = external["W4"]["ok"]
    h4 = all(row["chars"] <= ALLOCATION for row in rows)
    return {"rows": rows, "w1_present": w1_count, "w4_present": w4_count,
            "positions": positions, "external_u3a24": external,
            "gates": {"H1_new_fixture": h1, "H2_positions": h2,
                      "H3_external": h3, "H4_budget": h4}}


def answer_stage(cases: list[dict]) -> dict[str, Any]:
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

    total = sum(score(case_id, arm) for case_id in ANSWER_CASES for arm in ARMS)
    h5 = sum(score(case_id, "W4") for case_id in ANSWER_CASES) >= \
        sum(score(case_id, "W1") for case_id in ANSWER_CASES) - 0.05 * len(ANSWER_CASES)
    return {"cases": entries, "llm_calls": answerer.calls + judge_client.calls,
            "failures": failures, "mean_score": round(total / (2 * len(ANSWER_CASES)), 4),
            "gates": {"H5_answers": h5}}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture",
                        default=str(HERE / "fixtures" / "money_holdout_v1"))
    parser.add_argument("--out",
                        default=str(HERE / "results" / "money_holdout_v1"))
    parser.add_argument("--skip-llm", action="store_true")
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    cases = load_holdout(Path(args.fixture))
    source_sha = hashlib.sha256(inspect.getsource(ni.w4_window).encode()).hexdigest()
    report: dict[str, Any] = {
        "prereg": "docs/MONEY_HOLDOUT_V1_PREREG.md",
        "w4_source_sha256": source_sha,
        "w4_unchanged": source_sha == W4_SOURCE_SHA,
        "delivery": delivery_stage(cases),
    }
    if report["w4_unchanged"] and not args.skip_llm:
        report["answer"] = answer_stage(cases)
    gates = dict(report["delivery"]["gates"])
    if "answer" in report:
        gates.update(report["answer"]["gates"])
    gates["H6_w4_frozen"] = report["w4_unchanged"]
    report["gates"] = gates
    report["all_pass"] = all(gates.values())
    (out / "report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8")
    lines = ["# money-holdout-v1", "",
             f"- W4 frozen: {report['w4_unchanged']} · present W1/W4: "
             f"{report['delivery']['w1_present']}//{report['delivery']['w4_present']} de 12",
             "",
             "| case | pos | arm | gold | present |", "|---|---|---|---|---|"]
    for row in report["delivery"]["rows"]:
        lines.append(f"| {row['case_id']} | {row['position']} | {row['arm']} | "
                     f"{row['gold']} | {'ok' if row['present'] else 'MISS'} |")
    if "answer" in report:
        lines += ["", "| case | W1 | W4 |", "|---|---|---|"]
        for entry in report["answer"]["cases"]:
            lines.append(f"| {entry['case_id']} | {'/'.join(entry['arms']['W1'])} "
                         f"| {'/'.join(entry['arms']['W4'])} |")
        lines += [f"llm calls: {report['answer']['llm_calls']} · failures: "
                  f"{report['answer']['failures']}"]
    lines += ["", f"gates: {json.dumps(report['gates'], sort_keys=True)}",
              f"all_pass: {report['all_pass']}"]
    markdown = "\n".join(lines) + "\n"
    (out / "report.md").write_text(markdown, encoding="utf-8")
    print(markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
