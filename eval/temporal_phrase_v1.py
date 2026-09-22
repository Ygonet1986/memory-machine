#!/usr/bin/env python3
"""temporal-phrase-v1: W5 = W3 + temporal-phrase anchors (step 2).

Frozen by docs/TEMPORAL_PHRASE_V1_PREREG.md. Delivery stage uses the phrase
metric; answer gate N=3 on u3a-22 with W1/W3/W5.

    PYTHONPATH=src:.:eval python3 eval/temporal_phrase_v1.py --skip-llm
    PYTHONPATH=src:.:eval python3 eval/temporal_phrase_v1.py
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "src"))

import delivery_anchors_v1 as da  # noqa: E402
import delivery_combined_v1 as dc  # noqa: E402
import phrase_delivery_v1 as pd  # noqa: E402
from fact_presence import item_span  # noqa: E402

TRACKED = (("u3a", 12), ("u3a", 19), ("u3a", 22), ("u3b", 27))
ARMS = ("W1", "W3", "W5")
RUNS = 3
TEMPORAL_CUE_RE = re.compile(
    r"how long|when|duration|weeks?|days?|months?|years?|hours?|minutes?"
    r"|before|after|ago|since", re.IGNORECASE)
TEMPORAL_UNITS = (r"days?|weeks?|months?|years?|hours?|minutes?")


def temporal_phrases(text: str) -> bool:
    t = pd.norm(text)
    if re.search(rf"(\d+(?:[.,]\d+)?)\s*({TEMPORAL_UNITS})\b", t):
        return True
    if re.search(rf"\b({'|'.join(pd.NUMBER_WORDS)})\s+({TEMPORAL_UNITS})\b", t):
        return True
    return False


def w5_window(text: str, question: str, allocation: int) -> str:
    """anchors_window + temporal-phrase segments for temporal questions."""
    if allocation <= 0 or not text:
        return text[: max(0, allocation)]
    parts = da.segments(text)
    if not parts or sum(len(part) + 1 for part in parts) <= allocation:
        return text[:allocation]
    from memory_machine.retrieval import tokenize
    q_tokens = set(tokenize(question))
    scores = [len(q_tokens & set(tokenize(part))) for part in parts]
    best = max(range(len(parts)), key=lambda i: (scores[i], -i))

    order: list[int] = [best]
    for neighbor in (best - 1, best + 1):
        if 0 <= neighbor < len(parts) and neighbor not in order:
            order.append(neighbor)
    for index, part in enumerate(parts):
        if da.DATE_RE.search(part) and index not in order:
            order.append(index)
    if da.NUM_CUE_RE.search(question):
        numeric = [i for i, part in enumerate(parts) if da.data_numbers(part)]
        numeric.sort(key=lambda i: (abs(i - best), i))
        for index in numeric[:4]:
            if index not in order:
                order.append(index)
    if TEMPORAL_CUE_RE.search(question):
        temporal = [i for i, part in enumerate(parts) if temporal_phrases(part)]
        for index in sorted(temporal, key=lambda i: (abs(i - best), i)):
            if index not in order:
                order.append(index)
    for index in sorted(range(len(parts)), key=lambda i: (-scores[i], i)):
        if index not in order:
            order.append(index)

    chosen: list[int] = []
    used = 0
    for index in order:
        cost = len(parts[index]) + (3 if chosen else 0)
        if used + cost <= allocation:
            chosen.append(index)
            used += cost
    chosen.sort()
    return " … ".join(parts[index] for index in chosen)[:allocation]


def rebuild(case: dict, records: dict, arm: str) -> str:
    out = case["context"]
    numeric = bool(da.NUM_CUE_RE.search(case["question"]))
    for memory_id in case["payload_ids"]:
        span, found = item_span(out, memory_id)
        if not found:
            continue
        record = records.get((int(case["case"]), memory_id))
        if record is None:
            continue
        body_start = span.find("\n")
        header = span[:body_start]
        frozen_body = span[body_start + 1:]
        full_body = f"{record['summary']}\n{record['why']}"
        if len(full_body) <= len(frozen_body):
            continue
        room = len(frozen_body) - len(record["summary"]) - 1
        if room < 120:
            continue
        if arm == "W1":
            window = da.fact_window
        elif arm == "W3":
            window = da.anchors_window if numeric else da.fact_window
        else:
            window = w5_window if numeric else da.fact_window
        windowed = window(str(record.get("why") or ""), case["question"], room)
        new_body = f"{record['summary']}\n{windowed}"[: len(frozen_body)]
        if new_body != frozen_body:
            out = out.replace(span, header + "\n" + new_body, 1)
    return out


def collect(*, skip_llm: bool) -> dict[str, Any]:
    cases, records = dc.load_fixture(HERE / "fixtures" / "composition_u4")
    selected = [c for c in cases if (c["block"], c["case"]) in TRACKED]
    contexts = {(case["block"], case["case"], arm): rebuild(case, records, arm)
                for case in selected for arm in ARMS}
    rows = []
    for case in selected:
        for arm in ARMS:
            ctx = contexts[(case["block"], case["case"], arm)]
            result = pd.check(case, ctx, records)
            rows.append({"block": case["block"], "case": case["case"],
                         "arm": arm, "gold": case["gold"],
                         "chars": len(ctx), **result})

    def row_of(case: int, arm: str) -> dict:
        return next(r for r in rows if r["case"] == case and r["arm"] == arm)

    t1 = row_of(22, "W5")["ok"] and not row_of(22, "W3")["ok"]
    t2 = all(row_of(case, "W5")["ok"] >= row_of(case, "W3")["ok"]
             for case in (12, 19, 27)) and \
        all(row["chars"] <= len(next(c["context"] for c in selected
                                     if c["block"] == row["block"]
                                     and c["case"] == row["case"]))
            for row in rows if row["arm"] == "W5")
    answer: dict[str, Any] = {}
    if not skip_llm:
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
        case22 = next(c for c in selected
                      if (c["block"], c["case"]) == ("u3a", 22))
        failures = 0
        arms: dict[str, list[str]] = {}
        for arm in ARMS:
            verdicts = []
            for _ in range(RUNS):
                whiteboard = Whiteboard()
                whiteboard.subject = case22["question"]
                try:
                    reply, _m, _r = run_main_chatbot(
                        answerer, whiteboard, case22["question"],
                        extra_context=contexts[("u3a", 22, arm)],
                        temperature=0.0)
                    verdict, _reason = judge(judge_client, case22["question"],
                                             str(case22["gold"]), reply.strip())
                except Exception as error:
                    verdict = f"infra_error:{type(error).__name__}"
                    failures += 1
                verdicts.append(verdict)
            arms[arm] = verdicts
        score = {arm: sum({"correct": 1.0, "partial": 0.5}.get(v, 0.0)
                          for v in arms[arm]) / RUNS for arm in ARMS}
        t3 = score["W5"] > score["W3"] and score["W5"] >= score["W1"] - 0.05
        answer = {"arms": arms, "score": score,
                  "llm_calls": answerer.calls + judge_client.calls,
                  "failures": failures,
                  "gates": {"T3_answers": t3,
                            "T5_infra": failures <= 0.2 * RUNS * len(ARMS)}}
    report = {"prereg": "docs/TEMPORAL_PHRASE_V1_PREREG.md",
              "rows": rows,
              "answer": answer,
              "gates": {"T1_fixes_u3a22": t1, "T2_no_new_regressions": t2}}
    return report



def render(report: dict[str, Any]) -> list[str]:
    lines = ["# temporal-phrase-v1", "",
             "| case | arm | gold | present |", "|---|---|---|---|"]
    for row in report["rows"]:
        info = ",".join(row.get("gold_phrases") or row.get("missing") or [])
        lines.append(f"| {row['block']}:{row['case']} | {row['arm']} | {info} | "
                     f"{'ok' if row['ok'] else 'MISS'} |")
    answer = report.get("answer", {})
    if answer:
        lines += ["", "| arm | verdicts (N=3) | score |", "|---|---|---:|"]
        for arm, verdicts in answer["arms"].items():
            lines.append(f"| {arm} | {'/'.join(verdicts)} | {answer['score'][arm]:.2f} |")
        lines += [f"llm calls: {answer['llm_calls']} · failures: {answer['failures']}"]
    lines += ["", f"gates: {json.dumps(report['gates'], sort_keys=True)}"]
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out",
                        default=str(HERE / "results" / "temporal_phrase_v1"))
    parser.add_argument("--skip-llm", action="store_true")
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    report = collect(skip_llm=args.skip_llm)
    second = collect(skip_llm=True)
    report["gates"]["T4_determinism"] = (
        json.dumps(report["rows"], sort_keys=True)
        == json.dumps(second["rows"], sort_keys=True))
    if report["answer"]:
        report["gates"].update(report["answer"]["gates"])
    report["all_pass"] = all(report["gates"].values())
    (out / "report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8")
    markdown = "\n".join(render(report)) + "\n"
    (out / "report.md").write_text(markdown, encoding="utf-8")
    print(markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
