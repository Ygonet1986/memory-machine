#!/usr/bin/env python3
"""phrase-coverage-v1: W6 = W5 + mid-text phrase coverage (u3a-17).

Frozen by docs/PHRASE_COVERAGE_V1_PREREG.md. Delivery deterministic; answer
gate N=3 on u3a-17 (W5 vs W6).

    PYTHONPATH=src:.:eval python3 eval/phrase_coverage_v1.py --skip-llm
    PYTHONPATH=src:.:eval python3 eval/phrase_coverage_v1.py
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
import temporal_phrase_v1 as tp  # noqa: E402
from fact_presence import item_span  # noqa: E402

ARMS = ("W5", "W6")
TARGET = ("u3a", 17)
CONTROLS = (("u3a", 12), ("u3a", 19), ("u3a", 22), ("u3b", 27))
RUNS = 3
W5_SOURCE_SHA = "db5021c90c3c060d3c9176755d8860a6f370b10d80a0fb66f2bd8a8fd4976cb6"


def w6_window(text: str, question: str, allocation: int) -> str:
    """W5 selection + every phrase-bearing segment (distance order, uncapped)."""
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
    if tp.TEMPORAL_CUE_RE.search(question):
        temporal = [i for i, part in enumerate(parts)
                    if tp.temporal_phrases(part)]
        for index in sorted(temporal, key=lambda i: (abs(i - best), i)):
            if index not in order:
                order.append(index)
    phrase_segments = [i for i, part in enumerate(parts) if pd.phrases(part)]
    for index in sorted(phrase_segments, key=lambda i: (abs(i - best), i)):
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
        if arm == "W5":
            window = tp.w5_window if numeric else da.fact_window
        else:
            window = w6_window if numeric else da.fact_window
        windowed = window(str(record.get("why") or ""), case["question"], room)
        new_body = f"{record['summary']}\n{windowed}"[: len(frozen_body)]
        if new_body != frozen_body:
            out = out.replace(span, header + "\n" + new_body, 1)
    return out


def collect(*, skip_llm: bool) -> dict[str, Any]:
    cases, records = dc.load_fixture(HERE / "fixtures" / "composition_u4")
    selected = [c for c in cases
                if (c["block"], c["case"]) in (TARGET, *CONTROLS)]
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

    p1 = row_of(17, "W6")["ok"] and not row_of(17, "W5")["ok"]
    p2 = all(row_of(case, "W6")["ok"] >= row_of(case, "W5")["ok"]
             for case in (12, 19, 22, 27)) and all(
        row["chars"] <= len(next(c["context"] for c in selected
                                 if c["block"] == row["block"]
                                 and c["case"] == row["case"]))
        for row in rows if row["arm"] == "W6")

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
        case17 = next(c for c in selected
                      if (c["block"], c["case"]) == TARGET)
        failures = 0
        arms: dict[str, list[str]] = {}
        for arm in ARMS:
            verdicts = []
            for _ in range(RUNS):
                whiteboard = Whiteboard()
                whiteboard.subject = case17["question"]
                try:
                    reply, _m, _r = run_main_chatbot(
                        answerer, whiteboard, case17["question"],
                        extra_context=contexts[("u3a", 17, arm)],
                        temperature=0.0)
                    verdict, _reason = judge(judge_client, case17["question"],
                                             str(case17["gold"]), reply.strip())
                except Exception as error:
                    verdict = f"infra_error:{type(error).__name__}"
                    failures += 1
                verdicts.append(verdict)
            arms[arm] = verdicts
        score = {arm: sum({"correct": 1.0, "partial": 0.5}.get(v, 0.0)
                          for v in arms[arm]) / RUNS for arm in ARMS}
        answer = {"arms": arms, "score": score,
                  "llm_calls": answerer.calls + judge_client.calls,
                  "failures": failures,
                  "gates": {"P3_answers": score["W6"] >= score["W5"] - 0.05,
                            "P5_infra": failures <= 0.2 * RUNS * len(ARMS)}}

    source_sha = hashlib.sha256(inspect.getsource(tp.w5_window).encode()).hexdigest()
    report = {"prereg": "docs/PHRASE_COVERAGE_V1_PREREG.md",
              "w5_source_sha256": source_sha,
              "w5_unchanged": source_sha == W5_SOURCE_SHA,
              "rows": rows, "answer": answer,
              "gates": {"P1_target_fixed": p1, "P2_no_removals": p2}}
    return report


def render(report: dict[str, Any]) -> list[str]:
    lines = ["# phrase-coverage-v1", "",
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
    lines += ["", f"w5 frozen: {report['w5_unchanged']}",
              f"gates: {json.dumps(report['gates'], sort_keys=True)}"]
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out",
                        default=str(HERE / "results" / "phrase_coverage_v1"))
    parser.add_argument("--skip-llm", action="store_true")
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    report = collect(skip_llm=args.skip_llm)
    second = collect(skip_llm=True)
    report["gates"]["P4_determinism"] = (
        json.dumps(report["rows"], sort_keys=True)
        == json.dumps(second["rows"], sort_keys=True))
    if report["answer"]:
        report["gates"].update(report["answer"]["gates"])
    report["gates"]["P6_w5_frozen"] = report["w5_unchanged"]
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
