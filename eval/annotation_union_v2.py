#!/usr/bin/env python3
"""annotation-union-v2: offer A and A∪L5 to the agents, N=3 (hypothesis 2).

Frozen by docs/ANNOTATION_UNION_V2_PREREG.md. Deterministic candidate lists
from the frozen snapshots + fixture; only the agent calls are LLM.

    PYTHONPATH=src:.:eval python3 eval/annotation_union_v2.py
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

import delivery_combined_v1 as dc  # noqa: E402
from memory_machine.retrieval import bm25  # noqa: E402

RUNS = 3
ARMS = ("A", "U")
EXCERPT = 400
AGENT_PROMPT = """You are a memory agent. You watch a set of persistent memory records.

Your memories (only these; never invent others):

{records}

Question: {question}

Identify which of YOUR memories MUST be remembered for the current work and
annotate them.

Return ONLY a JSON object, nothing else:

{{"annotations":[{{"memory_id":"M0001","note":"<why this matters now>","relevance":0.0}}]}}

Rules:
- Only annotate memory ids that appear in YOUR list above.
- relevance is a number from 0.0 (marginal) to 1.0 (critical).
- If nothing must be remembered, return "annotations":[]."""


def load_snapshots() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for name in ("u3a", "u3b"):
        path = HERE / "graph_out" / f"u_diag_longmemeval_{name}.jsonl"
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                row["block"] = name
                rows.append(row)
    return rows


def build_cases() -> list[dict[str, Any]]:
    snapshots = load_snapshots()
    cases, records = dc.load_fixture(HERE / "fixtures" / "composition_u4")
    built: list[dict[str, Any]] = []
    for snap in snapshots:
        case = next((c for c in cases if c["block"] == snap["block"]
                     and c["case"] == snap["case"]), None)
        if case is None:
            continue
        case_records = [r for (c, _), r in records.items() if c == snap["case"]]
        texts = [f"{r['summary']} {r['why']}" for r in case_records]
        scores = bm25(snap["question"], texts)
        order = sorted(range(len(texts)), key=lambda i: -scores[i])
        ranked = [case_records[i]["id"] for i in order if scores[i] > 0]
        by_id = {r["id"]: r for r in case_records}
        required = [mid for mid in snap["required_ids"] if mid in by_id]
        annotated = [mid for mid in snap.get("agent_ids") or [] if mid in by_id]
        if not required or not annotated:
            continue
        union = list(dict.fromkeys(annotated + ranked[:5]))
        built.append({"block": snap["block"], "case": snap["case"],
                      "question": snap["question"], "required": required,
                      "lists": {"A": annotated, "U": union},
                      "by_id": by_id})
    return built


def render_list(case: dict[str, Any], arm: str) -> str:
    lines = []
    for memory_id in case["lists"][arm]:
        record = case["by_id"][memory_id]
        text = f"{record['summary']} {record['why']}".strip()
        lines.append(f"[{memory_id} | {record['type']}] {text[:EXCERPT]}")
    return "\n".join(lines)


def run_agent(client: Any, case: dict[str, Any], arm: str) -> set[str] | None:
    from memory_machine.llm import extract_json_object

    messages = [
        {"role": "system", "content": "You are a memory agent."},
        {"role": "user", "content": AGENT_PROMPT.format(
            records=render_list(case, arm), question=case["question"])},
    ]
    content = client.complete(messages, temperature=0.0)
    obj = extract_json_object(content)
    if not isinstance(obj, dict):
        return None
    out = {str(a.get("memory_id")) for a in (obj.get("annotations") or [])
           if isinstance(a, dict)}
    allowed = set(case["lists"][arm])
    return out & allowed


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
    cases = build_cases()
    per_case: list[dict[str, Any]] = []
    failures = 0
    for case in cases:
        entry: dict[str, Any] = {"block": case["block"], "case": case["case"],
                                 "question": case["question"],
                                 "required": case["required"],
                                 "runs": {"A": [], "U": []}}
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
                    "recovered": sorted((set(case["required"]) - set(case["lists"]["A"]))
                                        & output),
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
    recovered_total = sum(len(run["recovered"])
                          for e in per_case for run in e["runs"]["U"]
                          if run.get("ok"))
    u3a17 = next(e for e in per_case
                 if e["block"] == "u3a" and e["case"] == 17)
    u3a17_hits = sum(1 for run in u3a17["runs"]["U"]
                     if run.get("ok") and "M0043" in run["output"])
    report = {"prereg": "docs/ANNOTATION_UNION_V2_PREREG.md",
              "cases": len(per_case), "runs": RUNS,
              "aggregates": aggregates,
              "recovered_required_runs": recovered_total,
              "u3a17": {"runs": u3a17["runs"]["U"], "m0043_hits": u3a17_hits},
              "llm_calls": client.calls, "failures": failures,
              "per_case": per_case}
    report["gates"] = {
        "H2-1_coverage": (aggregates["U"]["mean_coverage"]
                          > aggregates["A"]["mean_coverage"]),
        "H2-2_undue": (aggregates["U"]["total_undue_mean_per_case"]
                       <= aggregates["A"]["total_undue_mean_per_case"] + 10 / 30),
        "H2-3_u3a17": u3a17_hits >= 2,
        "H2-4_infra": failures <= 0.2 * len(per_case) * RUNS * len(ARMS),
    }
    report["all_pass"] = all(report["gates"].values())
    return report


def render(report: dict[str, Any]) -> list[str]:
    lines = ["# annotation-union-v2", "",
             f"- cases: {report['cases']} · runs/arm: {report['runs']} · "
             f"calls: {report['llm_calls']} · failures: {report['failures']}",
             "",
             "| arm | mean coverage | undue/case |", "|---|---:|---:|"]
    for arm in ARMS:
        agg = report["aggregates"][arm]
        lines.append(f"| {arm} | {agg['mean_coverage']:.3f} | "
                     f"{agg['total_undue_mean_per_case']:.3f} |")
    lines += ["", f"- recovered required (U, all runs): "
              f"{report['recovered_required_runs']}",
              f"- u3a-17: M0043 hits under U = {report['u3a17']['m0043_hits']}/3",
              "", f"gates: {json.dumps(report['gates'], sort_keys=True)}",
              f"all_pass: {report['all_pass']}"]
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out",
                        default=str(HERE / "results" / "annotation_union_v2"))
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
