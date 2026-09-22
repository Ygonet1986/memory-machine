#!/usr/bin/env python3
"""snippet-window-v3: question-windowed candidate snippets, N=3.

Frozen by docs/SNIPPET_WINDOW_V3_PREREG.md. Same union list U for both arms;
only the per-candidate snippet strategy changes.

    PYTHONPATH=src:.:eval python3 eval/snippet_window_v3.py
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
import delivery_combined_v1 as dc  # noqa: E402
import phrase_delivery_v1 as pd  # noqa: E402
from memory_machine.payload import fact_window  # noqa: E402

RUNS = 3
ARMS = ("S-head", "S-query")
EXCERPT = 400


def snippet(case: dict[str, Any], memory_id: str, arm: str) -> str:
    record = case["by_id"][memory_id]
    text = f"{record['summary']} {record['why']}".strip()
    if arm == "S-head":
        return text[:EXCERPT]
    return fact_window(text, case["question"], EXCERPT)


def render_list(case: dict[str, Any], arm: str) -> str:
    return "\n".join(
        f"[{memory_id} | {case['by_id'][memory_id]['type']}] "
        f"{snippet(case, memory_id, arm)}"
        for memory_id in case["lists"]["U"])


def input_snippet_coverage(cases: list[dict[str, Any]]) -> dict[str, Any]:
    """Informational: does the snippet contain the gold phrase (when the gold
    has a phrase)?"""
    fixture_cases, _records = dc.load_fixture(HERE / "fixtures" / "composition_u4")
    gold_by_case = {(c["block"], c["case"]): str(c["gold"]) for c in fixture_cases}
    rows = []
    for case in cases:
        phrases = pd.gold_phrases(gold_by_case.get((case["block"], case["case"]), ""))
        if not phrases:
            continue
        for arm in ARMS:
            found = 0
            for memory_id in case["required"]:
                text = snippet(case, memory_id, arm)
                if all(pd.phrase_present(phrase, text) for phrase in phrases):
                    found += 1
            rows.append({"block": case["block"], "case": case["case"],
                         "arm": arm, "phrases": [f"{v}{u}" for v, u in phrases],
                         "required": len(case["required"]),
                         "snippet_contains": found})
    return {"rows": rows}



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
    cases = v2.build_cases()
    per_case: list[dict[str, Any]] = []
    failures = 0
    for case in cases:
        entry: dict[str, Any] = {"block": case["block"], "case": case["case"],
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
    u3a17 = next(e for e in per_case
                 if e["block"] == "u3a" and e["case"] == 17)
    hits = {arm: sum(1 for run in u3a17["runs"][arm]
                     if run.get("ok") and "M0043" in run["output"])
            for arm in ARMS}
    report = {"prereg": "docs/SNIPPET_WINDOW_V3_PREREG.md",
              "cases": len(per_case), "runs": RUNS,
              "input_snippet_coverage": input_snippet_coverage(cases),
              "aggregates": aggregates,
              "u3a17": {"m0043_hits": hits, "runs": u3a17["runs"]},
              "llm_calls": client.calls, "failures": failures,
              "per_case": per_case}
    report["gates"] = {
        "H3-1_coverage": (aggregates["S-query"]["mean_coverage"]
                          > aggregates["S-head"]["mean_coverage"]),
        "H3-2_undue": (aggregates["S-query"]["total_undue_mean_per_case"]
                       <= aggregates["S-head"]["total_undue_mean_per_case"]
                       + 10 / 30),
        "H3-3_u3a17": hits["S-query"] >= 2,
        "H3-4_infra": failures <= 0.2 * len(per_case) * RUNS * len(ARMS),
    }
    report["all_pass"] = all(report["gates"].values())
    return report


def render(report: dict[str, Any]) -> list[str]:
    lines = ["# snippet-window-v3", "",
             f"- cases: {report['cases']} · calls: {report['llm_calls']} · "
             f"failures: {report['failures']}", "",
             "| arm | mean coverage | undue/case |", "|---|---:|---:|"]
    for arm in ARMS:
        agg = report["aggregates"][arm]
        lines.append(f"| {arm} | {agg['mean_coverage']:.3f} | "
                     f"{agg['total_undue_mean_per_case']:.3f} |")
    lines += ["", f"- u3a-17 M0043 hits: {report['u3a17']['m0043_hits']}",
              "", f"gates: {json.dumps(report['gates'], sort_keys=True)}",
              f"all_pass: {report['all_pass']}"]
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out",
                        default=str(HERE / "results" / "snippet_window_v3"))
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
