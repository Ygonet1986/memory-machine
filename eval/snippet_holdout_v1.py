#!/usr/bin/env python3
"""snippet-holdout-v1: one-shot holdout for union + query-window snippets.

Frozen by docs/SNIPPET_HOLDOUT_V1_PREREG.md. Deterministic lists and
snippets; only the agent calls are LLM (12 cases x 2 arms x 3 runs).

    PYTHONPATH=src:.:eval python3 eval/snippet_holdout_v1.py
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

import annotation_union_v2 as v2  # noqa: E402
import snippet_window_v3 as sw  # noqa: E402
from memory_machine.retrieval import bm25  # noqa: E402

RUNS = 3
ARMS = ("S-head", "S-query")
EXCERPT = 400
FIXTURE = HERE / "fixtures" / "snippet_holdout_v1"


def load_cases() -> list[dict[str, Any]]:
    cases = [json.loads(line) for line in
             (FIXTURE / "cases.jsonl").read_text(encoding="utf-8").splitlines()
             if line.strip()]
    for case in cases:
        by_id = {r["memory_id"]: r for r in case["records"]}
        case["by_id"] = by_id
        scores = bm25(case["question"], [f"{r['summary']} {r['why']}"
                                         for r in case["records"]])
        order = sorted(range(len(case["records"])), key=lambda i: -scores[i])
        ranked = [case["records"][i]["memory_id"] for i in order
                  if scores[i] > 0]
        case["lists"] = {"U": list(dict.fromkeys(
            case["simulated_annotations"] + ranked[:5]))}
    return cases


def snippet(case: dict[str, Any], memory_id: str, arm: str) -> str:
    return sw.snippet(case, memory_id, arm)


def render_list(case: dict[str, Any], arm: str) -> str:
    return "\n".join(
        f"[{memory_id} | {case['by_id'][memory_id]['type']}] "
        f"{snippet(case, memory_id, arm)}"
        for memory_id in case["lists"]["U"])


def run_agent(client: Any, case: dict[str, Any], arm: str) -> set[str] | None:
    from memory_machine.llm import extract_json_object

    messages = [
        {"role": "system", "content": "You are a memory agent."},
        {"role": "user", "content": v2.AGENT_PROMPT.format(
            records=render_list(case, arm), question=case["question"])},
    ]
    content = client.complete(messages, temperature=0.0)
    obj = extract_json_object(content)
    if not isinstance(obj, dict):
        return None
    out = {str(a.get("memory_id")) for a in (obj.get("annotations") or [])
           if isinstance(a, dict)}
    return out & set(case["lists"]["U"])


def collect() -> dict[str, Any]:
    from memory_machine.config import Config
    from memory_machine.llm import LLMClient
    from view_router_bench import CountingClient
    import os

    key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not key:
        raise RuntimeError("DEEPSEEK_API_KEY is not set")
    config = Config()
    client = CountingClient(LLMClient("https://api.deepseek.com", key,
                                      config.model, retries=1))
    cases = load_cases()
    per_case: list[dict[str, Any]] = []
    failures = 0
    for case in cases:
        entry: dict[str, Any] = {"case_id": case["case_id"],
                                 "required": case["required"],
                                 "runs": {arm: [] for arm in ARMS}}
        for arm in ARMS:
            for _ in range(RUNS):
                try:
                    output = run_agent(client, case, arm)
                except Exception:
                    output = None
                if output is None:
                    failures += 1
                    entry["runs"][arm].append({"ok": False})
                    continue
                covered = sorted(set(case["required"]) & output)
                entry["runs"][arm].append({
                    "ok": True, "output": sorted(output),
                    "coverage": round(len(covered) / len(case["required"]), 4),
                    "undue": sorted(output - set(case["required"])),
                })
        per_case.append(entry)

    def mean(values: list[float]) -> float:
        return round(sum(values) / len(values), 4) if values else 0.0

    aggregates: dict[str, Any] = {}
    for arm in ARMS:
        coverages = [run["coverage"] for e in per_case for run in e["runs"][arm]
                     if run.get("ok")]
        undues = [len(run["undue"]) for e in per_case for run in e["runs"][arm]
                  if run.get("ok")]
        aggregates[arm] = {
            "mean_coverage": mean(coverages),
            "total_undue_mean_per_case": round(
                sum(undues) / (len(per_case) * RUNS), 4) if per_case else 0.0,
        }
    recovered_cases = sum(
        1 for e in per_case
        if sum(1 for run in e["runs"]["S-query"]
               if run.get("ok") and set(e["required"]).issubset(run["output"])) >= 2)
    report = {"prereg": "docs/SNIPPET_HOLDOUT_V1_PREREG.md",
              "cases": len(per_case), "runs": RUNS,
              "aggregates": aggregates,
              "recovered_cases_s_query": recovered_cases,
              "llm_calls": client.calls, "failures": failures,
              "per_case": per_case}
    report["gates"] = {
        "X1_coverage": (aggregates["S-query"]["mean_coverage"]
                        > aggregates["S-head"]["mean_coverage"]),
        "X2_generalization": recovered_cases >= 10,
        "X3_undue": (aggregates["S-query"]["total_undue_mean_per_case"]
                     <= aggregates["S-head"]["total_undue_mean_per_case"]
                     + 6 / 12),
        "X4_infra": failures <= 0.2 * len(per_case) * RUNS * len(ARMS),
    }
    report["all_pass"] = all(report["gates"].values())
    return report


def render(report: dict[str, Any]) -> list[str]:
    lines = ["# snippet-holdout-v1", "",
             f"- cases: {report['cases']} · calls: {report['llm_calls']} · "
             f"failures: {report['failures']}",
             f"- recovered cases (S-query, >=2/3 runs): "
             f"{report['recovered_cases_s_query']}/12", "",
             "| arm | mean coverage | undue/case |", "|---|---:|---:|"]
    for arm in ARMS:
        agg = report["aggregates"][arm]
        lines.append(f"| {arm} | {agg['mean_coverage']:.3f} | "
                     f"{agg['total_undue_mean_per_case']:.3f} |")
    lines += ["", f"gates: {json.dumps(report['gates'], sort_keys=True)}",
              f"all_pass: {report['all_pass']}"]
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out",
                        default=str(HERE / "results" / "snippet_holdout_v1"))
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    report = collect()
    (out / "report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8")
    markdown = "\n".join(render(report)) + "\n"
    (out / "report.md").write_text(markdown, encoding="utf-8")
    print(markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
