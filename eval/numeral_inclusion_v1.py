#!/usr/bin/env python3
"""numeral-inclusion-v1: W4 = W3 with nearest-4 data-number anchors.

Frozen by docs/NUMERAL_INCLUSION_V1_PREREG.md. Delivery gate uses the phrase
metric; answer gate N=3 on u3a-19/u3a-22 (same answerer, blind judge).

    PYTHONPATH=src:.:eval python3 eval/numeral_inclusion_v1.py --skip-llm
    PYTHONPATH=src:.:eval python3 eval/numeral_inclusion_v1.py
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
ANSWER_CASES = (("u3a", 19), ("u3a", 22))
ARMS = ("W3", "W4")
RUNS = 3
NEAREST_NUMBERS = 4
MONEY_CUE_RE = re.compile(r"amount|spent|cost|price|paid|dollars|budget|\$",
                          re.IGNORECASE)
CURRENCY_RE = re.compile(r"\$\s*\d|\d+\s*(?:dollars?|usd)", re.IGNORECASE)


def w4_window(text: str, question: str, allocation: int) -> str:
    """anchors_window with the numeric anchor set = nearest N data-number segments."""
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
        if MONEY_CUE_RE.search(question):
            currency = [i for i, part in enumerate(parts)
                        if CURRENCY_RE.search(part)]
            if currency:
                for index in sorted(currency, key=lambda i: (abs(i - best), i)):
                    if index not in order:
                        order.append(index)
        else:
            numeric = [i for i, part in enumerate(parts)
                       if da.data_numbers(part)]
            numeric.sort(key=lambda i: (-scores[i], abs(i - best), i))
            for index in numeric[:NEAREST_NUMBERS]:
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
        if arm == "W3":
            window = da.anchors_window if numeric else da.fact_window
        else:
            window = w4_window if numeric else da.fact_window
        windowed = window(str(record.get("why") or ""), case["question"], room)
        new_body = f"{record['summary']}\n{windowed}"[: len(frozen_body)]
        if new_body != frozen_body:
            out = out.replace(span, header + "\n" + new_body, 1)
    return out


def collect(*, skip_llm: bool) -> tuple[dict[str, Any], dict[str, Any]]:
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
                         "arm": arm, "question": case["question"],
                         "gold": case["gold"], "chars": len(ctx), **result})

    def row_of(case: int, arm: str) -> dict:
        return next(r for r in rows if r["case"] == case and r["arm"] == arm)

    n1 = row_of(19, "W4")["ok"] and not row_of(19, "W3")["ok"]
    n2 = all(row_of(case, "W4")["ok"] >= row_of(case, "W3")["ok"]
             for case in (12, 27)) and row_of(22, "W4")["ok"] == row_of(22, "W3")["ok"]
    n2 = n2 and all(row["chars"] <= len(next(c["context"] for c in selected
                                              if c["block"] == row["block"]
                                              and c["case"] == row["case"]))
                    for row in rows if row["arm"] == "W4")

    answer: dict[str, Any] = {"runs": RUNS, "cases": []}
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
        for case in selected:
            if (case["block"], case["case"]) not in ANSWER_CASES:
                continue
            entry = {"block": case["block"], "case": case["case"],
                     "question": case["question"], "gold": case["gold"],
                     "arms": {}}
            for arm in ARMS:
                ctx = contexts[(case["block"], case["case"], arm)]
                verdicts = []
                for _ in range(RUNS):
                    whiteboard = Whiteboard()
                    whiteboard.subject = case["question"]
                    try:
                        reply, _m, _r = run_main_chatbot(
                            answerer, whiteboard, case["question"],
                            extra_context=ctx, temperature=0.0)
                        verdict, _reason = judge(judge_client, case["question"],
                                                 str(case["gold"]), reply.strip())
                    except Exception as error:
                        verdict = f"infra_error:{type(error).__name__}"
                    verdicts.append(verdict)
                entry["arms"][arm] = verdicts
            answer["cases"].append(entry)
        answer["llm_calls"] = answerer.calls + judge_client.calls
        answer["failures"] = sum(
            1 for entry in answer["cases"] for arm in ARMS
            for verdict in entry["arms"][arm] if verdict.startswith("infra_error"))

    def score_of(case: int, arm: str) -> float:
        for entry in answer["cases"]:
            if entry["case"] == case:
                verdicts = entry["arms"][arm]
                return sum({"correct": 1.0, "partial": 0.5}.get(v, 0.0)
                           for v in verdicts) / len(verdicts)
        return 0.0

    n3 = True
    if not skip_llm:
        n3 = (score_of(19, "W4") > score_of(19, "W3")
              and score_of(22, "W4") >= score_of(22, "W3") - 0.05)
    n5 = (answer.get("failures", 0) <= 0.2 * (len(ANSWER_CASES) * len(ARMS) * RUNS)
          if not skip_llm else True)

    report = {"prereg": "docs/NUMERAL_INCLUSION_V1_PREREG.md",
              "rows": rows, "answer": answer,
              "gates": {"N1_fixes_u3a19": n1, "N2_no_new_regressions": n2,
                        "N3_answers": n3, "N5_infra": n5}}
    return report, {"contexts": {f"{k[0]}:{k[1]}:{k[2]}": len(v)
                                 for k, v in contexts.items()}}


def render(report: dict[str, Any]) -> list[str]:
    lines = ["# numeral-inclusion-v1", "",
             "| case | arm | basis | gold | present |", "|---|---|---|---|---|"]
    for row in report["rows"]:
        info = ",".join(row.get("gold_phrases") or row.get("missing") or [])
        lines.append(f"| {row['block']}:{row['case']} | {row['arm']} | "
                     f"{row['basis']} | {info} | {'ok' if row['ok'] else 'MISS'} |")
    answer = report.get("answer", {})
    if answer.get("cases"):
        lines += ["", "| case | " + " | ".join(ARMS) + " |",
                  "|---|" + "---|" * len(ARMS)]
        for entry in answer["cases"]:
            cells = " | ".join("/".join(entry["arms"][arm]) for arm in ARMS)
            lines.append(f"| {entry['block']}:{entry['case']} | {cells} |")
        lines += [f"llm calls: {answer.get('llm_calls')} · "
                  f"failures: {answer.get('failures')}"]
    lines += ["", f"gates: {json.dumps(report['gates'], sort_keys=True)}"]
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out",
                        default=str(HERE / "results" / "numeral_inclusion_v1"))
    parser.add_argument("--skip-llm", action="store_true")
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    report, _meta = collect(skip_llm=args.skip_llm)
    second, _meta2 = collect(skip_llm=True)
    report["gates"]["N4_determinism"] = (
        json.dumps(report["rows"], sort_keys=True)
        == json.dumps(second["rows"], sort_keys=True))
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
