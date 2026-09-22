#!/usr/bin/env python3
"""delivery-combined-v1: W3 combined policy with two separate evaluations.

Frozen by docs/DELIVERY_COMBINED_V1_PREREG.md.
Evaluation A: fact presence (deterministic). Evaluation B: answer accuracy
with the same answerer and the frozen blind judge (LLM; key from env).

    PYTHONPATH=src:.:eval python3 eval/delivery_combined_v1.py --eval a
    PYTHONPATH=src:.:eval python3 eval/delivery_combined_v1.py --eval b
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "src"))

import delivery_anchors_v1 as da  # noqa: E402
from fact_presence import item_span  # noqa: E402

POLICIES = ("W0", "W1", "W3")


def load_fixture(fixture: Path) -> tuple[list[dict], dict[tuple[int, str], dict]]:
    cases = [json.loads(line) for line in
             (fixture / "cases.jsonl").read_text(encoding="utf-8").splitlines()
             if line.strip()]
    records: dict[tuple[int, str], dict] = {}
    for line in (fixture / "records.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            records[(int(row["case"]), str(row["id"]))] = row
    return cases, records


def _window_for(question: str, policy: str) -> Any:
    numeric = bool(da.NUM_CUE_RE.search(question))
    if policy == "W1":
        return da.fact_window
    if policy == "W3":
        return da.anchors_window if numeric else da.fact_window
    raise ValueError(policy)


def rebuild(case: dict, records: dict, policy: str) -> str:
    out = case["context"]
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
        window = _window_for(case["question"], policy)
        windowed = window(str(record.get("why") or ""), case["question"], room)
        new_body = f"{record['summary']}\n{windowed}"[: len(frozen_body)]
        if new_body != frozen_body:
            out = out.replace(span, header + "\n" + new_body, 1)
    return out


def contexts(case: dict, records: dict) -> dict[str, str]:
    return {"W0": case["context"],
            "W1": rebuild(case, records, "W1"),
            "W3": rebuild(case, records, "W3")}


def eval_a(cases: list[dict], records: dict) -> dict[str, Any]:
    per_case = []
    for case in cases:
        ctx = contexts(case, records)
        entry = {"case": case["case"], "block": case["block"],
                 "numeric": bool(da.NUM_CUE_RE.search(case["question"])),
                 "policies": {}}
        for policy in POLICIES:
            rate, all_present, missing = da.presence(case, ctx[policy])
            entry["policies"][policy] = {
                "presence": rate, "all_present": all_present,
                "missing": missing, "chars": len(ctx[policy])}
        per_case.append(entry)

    def mean(policy: str, subset: str) -> float:
        rows = [e for e in per_case
                if subset == "all" or (subset == "numeric") == e["numeric"]]
        return round(sum(e["policies"][policy]["presence"] for e in rows)
                     / len(rows), 4) if rows else 0.0

    summary = {policy: {"mean_all": mean(policy, "all"),
                        "mean_numeric": mean(policy, "numeric"),
                        "mean_nonnumeric": mean(policy, "nonnumeric")}
               for policy in POLICIES}
    gates = {
        "A1_mean": summary["W3"]["mean_all"] >= summary["W1"]["mean_all"],
        "A2_numeric": (summary["W3"]["mean_numeric"]
                       >= summary["W1"]["mean_numeric"]),
        "A3_nonnumeric_identical": all(
            e["policies"]["W3"]["presence"] == e["policies"]["W1"]["presence"]
            for e in per_case if not e["numeric"]),
        "A4_budget": all(e["policies"]["W3"]["chars"] <= e["policies"]["W0"]["chars"]
                         for e in per_case),
    }
    return {"summary": summary, "gates": gates, "per_case": per_case}


def eval_b(cases: list[dict], records: dict, *, limit: int | None) -> dict[str, Any]:
    from memory_machine.config import Config
    from memory_machine.llm import LLMClient
    from memory_machine.main_chatbot import run_main_chatbot
    from memory_machine.whiteboard import Whiteboard
    from e2e_bench import JUDGE_PROMPT_VERSION, judge
    from view_router_bench import CountingClient

    config = Config()
    answerer = CountingClient(LLMClient("https://api.deepseek.com",
                                        _api_key(), config.model, retries=1))
    judge_client = CountingClient(LLMClient("https://api.deepseek.com",
                                            _api_key(), config.model, retries=1))
    rows = cases[:limit] if limit else cases
    per_case = []
    failures = 0
    for case in rows:
        ctx = contexts(case, records)
        entry = {"case": case["case"], "block": case["block"],
                 "numeric": bool(da.NUM_CUE_RE.search(case["question"])),
                 "gold": case["gold"], "policies": {}}
        for policy in POLICIES:
            try:
                whiteboard = Whiteboard()
                whiteboard.subject = case["question"]
                answer, _mem, _reason = run_main_chatbot(
                    answerer, whiteboard, case["question"],
                    extra_context=ctx[policy], temperature=0.0)
                verdict, reason = judge(judge_client, case["question"],
                                        str(case["gold"]), answer.strip())
            except Exception as error:  # infrastructure failure, recorded
                failures += 1
                entry["policies"][policy] = {"verdict": "infra_error",
                                             "reason": type(error).__name__}
                continue
            entry["policies"][policy] = {"verdict": verdict, "reason": reason,
                                         "answer": answer.strip()[:400]}
        per_case.append(entry)

    def score(verdict: str) -> float:
        return {"correct": 1.0, "partial": 0.5}.get(verdict, 0.0)

    summary = {}
    for policy in POLICIES:
        verdicts = [entry["policies"][policy]["verdict"] for entry in per_case]
        numeric = [entry["policies"][policy]["verdict"] for entry in per_case
                   if entry["numeric"]]
        summary[policy] = {
            "score": round(sum(score(v) for v in verdicts) / len(verdicts), 4),
            "strict": round(sum(1 for v in verdicts if v == "correct") / len(verdicts), 4),
            "numeric_score": round(sum(score(v) for v in numeric) / len(numeric), 4)
            if numeric else 0.0,
            "counts": {v: verdicts.count(v) for v in
                       ("correct", "partial", "incorrect", "infra_error")},
        }
    downgrades = sum(
        1 for entry in per_case
        if score(entry["policies"]["W3"]["verdict"])
        < score(entry["policies"]["W1"]["verdict"]))
    total_calls = len(rows) * len(POLICIES)
    gates = {
        "B1_beats_W0": summary["W3"]["score"] > summary["W0"]["score"],
        "B2_vs_W1": summary["W3"]["score"] >= summary["W1"]["score"] - 0.05,
        "B3_numeric_vs_W1": (summary["W3"]["numeric_score"]
                             >= summary["W1"]["numeric_score"]),
        "B4_downgrades": downgrades <= 2,
    }
    inconclusive = failures > 0.2 * total_calls * 2
    return {"summary": summary, "gates": gates, "per_case": per_case,
            "calls": {"pairs": total_calls, "llm_calls": answerer.calls + judge_client.calls,
                      "failures": failures, "limit": len(rows),
                      "judge_prompt_version": JUDGE_PROMPT_VERSION},
            "inconclusive_infrastructure": inconclusive}


def _api_key() -> str:
    import os
    key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not key:
        raise RuntimeError("DEEPSEEK_API_KEY is not set")
    return key


def content_digest(report: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(report, sort_keys=True,
                                     ensure_ascii=False).encode("utf-8")).hexdigest()


def render(report: dict[str, Any]) -> list[str]:
    lines = ["# delivery-combined-v1", ""]
    if "evaluation_a" in report:
        a = report["evaluation_a"]
        lines += ["## Evaluation A — delivery presence", "",
                  "| arm | mean | numeric | non-numeric |", "|---|---:|---:|---:|"]
        for policy in POLICIES:
            s = a["summary"][policy]
            lines.append(f"| {policy} | {s['mean_all']:.3f} | {s['mean_numeric']:.3f} "
                         f"| {s['mean_nonnumeric']:.3f} |")
        lines += ["", f"A gates: {json.dumps(a['gates'], sort_keys=True)}", ""]
    if "evaluation_b" in report:
        b = report["evaluation_b"]
        lines += ["## Evaluation B — answer accuracy (same answerer, blind judge)", "",
                  "| arm | score | strict | numeric | counts |", "|---|---:|---:|---:|---|"]
        for policy in POLICIES:
            s = b["summary"][policy]
            lines.append(f"| {policy} | {s['score']:.3f} | {s['strict']:.3f} | "
                         f"{s['numeric_score']:.3f} | {s['counts']} |")
        lines += ["", f"B gates: {json.dumps(b['gates'], sort_keys=True)}",
                  f"calls: {json.dumps(b['calls'], sort_keys=True)}",
                  f"inconclusive_infrastructure: {b['inconclusive_infrastructure']}", ""]
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture",
                        default=str(HERE / "fixtures" / "composition_u4"))
    parser.add_argument("--out",
                        default=str(HERE / "results" / "delivery_combined_v1"))
    parser.add_argument("--eval", choices=("a", "b", "both"), default="a")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    cases, records = load_fixture(Path(args.fixture))
    report_path = out / "report.json"
    report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {}
    if args.eval in ("a", "both"):
        first = eval_a(cases, records)
        second = eval_a(cases, records)
        first["gates"]["A5_determinism"] = (json.dumps(first, sort_keys=True)
                                            == json.dumps(second, sort_keys=True))
        report["evaluation_a"] = first
    if args.eval in ("b", "both"):
        report["evaluation_b"] = eval_b(cases, records, limit=args.limit)
    report["prereg"] = "docs/DELIVERY_COMBINED_V1_PREREG.md"
    report["fixture"] = str(args.fixture)
    if "evaluation_a" in report and "evaluation_b" in report:
        report["all_pass"] = (all(report["evaluation_a"]["gates"].values())
                              and all(report["evaluation_b"]["gates"].values()))
    report_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8")
    markdown = "\n".join(render(report)) + "\n"
    (out / "report.md").write_text(markdown, encoding="utf-8")
    print(markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
