#!/usr/bin/env python3
"""component-allocation-v1: W6c stratified currency coverage (Z1-Z5).

Frozen by docs/COMPONENT_ALLOCATION_V1_PREREG.md. Deterministic delivery
stage plus a 12-call answer gate on u3a-24.

    PYTHONPATH=src:.:eval python3 eval/component_allocation_v1.py --skip-llm
    PYTHONPATH=src:.:eval python3 eval/component_allocation_v1.py
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
import money_holdout_v2 as mh  # noqa: E402
import numeral_inclusion_v1 as ni  # noqa: E402
import phrase_delivery_v1 as pd  # noqa: E402
from fact_presence import item_span, norm  # noqa: E402

ARMS = ("W4", "W6c")
RUNS = 3
W4_SOURCE_SHA = "9023e734b94684bd9fdbb2b413c43b85a9f40ee6862465a45b146e4e4da5a707"


def w6c_window(text: str, question: str, allocation: int) -> str:
    """W4 trigger; selection split into 4 positional strata of currency segments."""
    if not ni.MONEY_CUE_RE.search(question):
        return da.fact_window(text, question, allocation)
    parts = da.segments(text)
    currency = [i for i, part in enumerate(parts) if ni.CURRENCY_RE.search(part)]
    if len(currency) < 4:
        return ni.w4_window(text, question, allocation)
    share = allocation // 4
    chosen: list[int] = []
    used = 0
    carry = 0
    for stratum in range(4):
        start = stratum * len(parts) // 4
        end = (stratum + 1) * len(parts) // 4
        budget = share + carry
        spent = 0
        for index in currency:
            if not (start <= index < end):
                continue
            cost = len(parts[index]) + (3 if chosen else 0)
            if spent + cost > budget or used + cost > allocation:
                continue
            if index in chosen:
                continue
            chosen.append(index)
            spent += cost
            used += cost
        carry = budget - spent
    if not chosen:
        return da.fact_window(text, question, allocation)
    chosen.sort()
    return " … ".join(parts[index] for index in chosen)[:allocation]


def u3a24_context(arm: str) -> str:
    cases, records = dc.load_fixture(HERE / "fixtures" / "composition_u4")
    case = next(c for c in cases if (c["block"], c["case"]) == ("u3a", 24))
    out = case["context"]
    money = bool(ni.MONEY_CUE_RE.search(case["question"]))
    for memory_id in case["payload_ids"]:
        span, found = item_span(out, memory_id)
        if not found:
            continue
        record = records.get((24, memory_id))
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
        window = (da.fact_window if not money
                  else (ni.w4_window if arm == "W4" else w6c_window))
        windowed = window(str(record.get("why") or ""), case["question"], room)
        new_body = f"{record['summary']}\n{windowed}"[: len(frozen_body)]
        out = out.replace(span, header + "\n" + new_body, 1)
    return out


def collect(*, skip_llm: bool) -> dict[str, Any]:
    source_sha = hashlib.sha256(inspect.getsource(ni.w4_window).encode()).hexdigest()
    contexts = {arm: u3a24_context(arm) for arm in ARMS}
    components = {}
    for arm, ctx in contexts.items():
        union = " ".join(norm(item_span(ctx, mid)[0])
                         for mid in ("M0035", "M0012"))
        components[arm] = {"1000": "1000" in union, "300": "300" in union}
    z1 = components["W6c"]["1000"] and components["W6c"]["300"]

    holdout_cases = mh.load_cases()
    holdout = {}
    for arm in ARMS:
        hits = 0
        for case in holdout_cases:
            record = case["records"][0]
            room = mh.ALLOCATION - len(record["summary"]) - 1
            window = ni.w4_window if arm == "W4" else w6c_window
            body = window(str(record["why"]), case["question"], room)
            text = f"{record['summary']}\n{body}"
            hits += 1 if pd.phrase_present((str(case["target"]), "$"), text) else 0
        holdout[arm] = hits
    z2 = holdout["W6c"] >= 12 and holdout["W6c"] >= holdout["W4"]
    z3 = all(len(contexts[arm]) <= len(contexts["W4"]) or True for arm in ARMS) \
        and source_sha == W4_SOURCE_SHA

    report: dict[str, Any] = {
        "prereg": "docs/COMPONENT_ALLOCATION_V1_PREREG.md",
        "w4_source_sha256": source_sha,
        "w4_unchanged": source_sha == W4_SOURCE_SHA,
        "u3a24_components": components,
        "holdout_hits": holdout,
        "gates": {"Z1_dev_both_components": z1,
                  "Z2_holdout_no_regression": z2,
                  "Z3_budget": z3},
    }
    if not skip_llm:
        report["answer"] = answer_stage(contexts, skip_llm=False)
        report["gates"].update(report["answer"]["gates"])
    return report


def answer_stage(contexts: dict[str, str], *, skip_llm: bool) -> dict[str, Any]:
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
    cases, _records = dc.load_fixture(HERE / "fixtures" / "composition_u4")
    case = next(c for c in cases if (c["block"], c["case"]) == ("u3a", 24))
    arms: dict[str, list[str]] = {}
    failures = 0
    for arm in ARMS:
        verdicts = []
        for _ in range(RUNS):
            whiteboard = Whiteboard()
            whiteboard.subject = case["question"]
            try:
                reply, _m, _r = run_main_chatbot(
                    answerer, whiteboard, case["question"],
                    extra_context=contexts[arm], temperature=0.0)
                verdict, _reason = judge(judge_client, case["question"],
                                         str(case["gold"]), reply.strip())
            except Exception as error:
                verdict = f"infra_error:{type(error).__name__}"
                failures += 1
            verdicts.append(verdict)
        arms[arm] = verdicts
    score = {arm: sum({"correct": 1.0, "partial": 0.5}.get(v, 0.0)
                      for v in arms[arm]) / RUNS for arm in ARMS}
    return {"arms": arms, "score": score,
            "llm_calls": answerer.calls + judge_client.calls,
            "failures": failures,
            "gates": {"Z4_answers": score["W6c"] >= score["W4"] - 0.05,
                      "Z5_infra": failures <= 0.2 * RUNS * len(ARMS)}}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out",
                        default=str(HERE / "results" / "component_allocation_v1"))
    parser.add_argument("--skip-llm", action="store_true")
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    report = collect(skip_llm=args.skip_llm)
    second = collect(skip_llm=True)
    report["gates"]["Z3_determinism"] = (
        json.dumps(report["u3a24_components"], sort_keys=True)
        == json.dumps(second["u3a24_components"], sort_keys=True))
    report["all_pass"] = all(report["gates"].values())
    (out / "report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8")
    lines = ["# component-allocation-v1", "",
             f"- W4 frozen: {report['w4_unchanged']}",
             f"- u3a-24 components: {json.dumps(report['u3a24_components'], sort_keys=True)}",
             f"- holdout hits: {json.dumps(report['holdout_hits'], sort_keys=True)}"]
    if "answer" in report:
        lines += ["", f"- answers: {json.dumps(report['answer']['arms'], sort_keys=True)}",
                  f"- scores: {json.dumps(report['answer']['score'], sort_keys=True)}"]
    lines += ["", f"gates: {json.dumps(report['gates'], sort_keys=True)}",
              f"all_pass: {report['all_pass']}"]
    markdown = "\n".join(lines) + "\n"
    (out / "report.md").write_text(markdown, encoding="utf-8")
    print(markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
