#!/usr/bin/env python3
"""annotation-coverage-v1: annotated vs lexical top-k required coverage.

Frozen by docs/ANNOTATION_COVERAGE_V1_PREREG.md. Deterministic, no LLM;
skips when the frozen snapshots are absent (not versioned).

    PYTHONPATH=src:.:eval python3 eval/annotation_coverage_v1.py
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

KS = (3, 5, 8, 10)


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


def collect() -> dict[str, Any]:
    snapshots = load_snapshots()
    cases, records = dc.load_fixture(HERE / "fixtures" / "composition_u4")
    per_case: list[dict[str, Any]] = []
    totals = {"required": 0, "annotated_hit": 0,
              **{f"L{k}_hit": 0 for k in KS}, "U5_hit": 0, "undue_proxy": 0}
    for snap in snapshots:
        case = next((c for c in cases
                     if c["block"] == snap["block"] and c["case"] == snap["case"]),
                    None)
        if case is None:
            continue
        case_records = [r for (c, _), r in records.items() if c == snap["case"]]
        texts = [f"{r['summary']} {r['why']}" for r in case_records]
        scores = bm25(snap["question"], texts)
        order = sorted(range(len(texts)), key=lambda i: -scores[i])
        ranked = [case_records[i]["id"] for i in order if scores[i] > 0]
        present = {r["id"] for r in case_records}
        required = [mid for mid in snap["required_ids"] if mid in present]
        annotated = [mid for mid in snap.get("agent_ids") or [] if mid in present]
        if not required:
            continue
        lists = {f"L{k}": ranked[:k] for k in KS}
        lists["U5"] = list(dict.fromkeys(annotated + lists["L5"]))
        entry: dict[str, Any] = {
            "block": snap["block"], "case": snap["case"],
            "question": snap["question"], "required": required,
            "annotated": annotated, "required_absent_from_fixture":
                [mid for mid in snap["required_ids"] if mid not in present],
            "coverage": {},
        }
        totals["required"] += len(required)
        for name, lst in [("A", annotated), *lists.items()]:
            hit = len(set(required) & set(lst))
            entry["coverage"][name] = round(hit / len(required), 4)
        totals["annotated_hit"] += len(set(required) & set(annotated))
        for k in KS:
            totals[f"L{k}_hit"] += len(set(required) & set(lists[f"L{k}"]))
        totals["U5_hit"] += len(set(required) & set(lists["U5"]))
        totals["undue_proxy"] += len((set(lists["L5"]) - set(annotated))
                                     - set(required))
        entry["missing"] = sorted(set(required) - set(annotated))
        entry["missing_covered_by_L5"] = sorted(
            (set(required) - set(annotated)) & set(lists["L5"]))
        per_case.append(entry)

    missing_total = sum(len(e["missing"]) for e in per_case)
    missing_covered = sum(len(e["missing_covered_by_L5"]) for e in per_case)
    report = {
        "prereg": "docs/ANNOTATION_COVERAGE_V1_PREREG.md",
        "cases": len(per_case),
        "per_case": per_case,
        "aggregate": {
            "required_total": totals["required"],
            "coverage_A": round(totals["annotated_hit"] / totals["required"], 4),
            "coverage_L3": round(totals["L3_hit"] / totals["required"], 4),
            "coverage_L5": round(totals["L5_hit"] / totals["required"], 4),
            "coverage_L8": round(totals["L8_hit"] / totals["required"], 4),
            "coverage_L10": round(totals["L10_hit"] / totals["required"], 4),
            "coverage_U5": round(totals["U5_hit"] / totals["required"], 4),
            "missing_total": missing_total,
            "missing_covered_by_L5": missing_covered,
            "undue_proxy": totals["undue_proxy"],
        },
    }
    u3a17 = next(e for e in per_case
                 if e["block"] == "u3a" and e["case"] == 17)
    report["gates"] = {
        "A1_processed": len(per_case) == 30,
        "A3_u3a17_visible": u3a17["coverage"]["L5"] == 1.0
        and u3a17["missing"] == ["M0043"],
    }
    return report


def render(report: dict[str, Any]) -> list[str]:
    agg = report["aggregate"]
    lines = ["# annotation-coverage-v1", "",
             f"- cases: {report['cases']} · aggregate: "
             f"{json.dumps(agg, sort_keys=True)}", "",
             "| case | required | A | L3 | L5 | U5 | missing | covered by L5 |",
             "|---|---:|---:|---:|---:|---:|---|---|"]
    for entry in report["per_case"]:
        cov = entry["coverage"]
        lines.append(f"| {entry['block']}:{entry['case']} | {len(entry['required'])} | "
                     f"{cov['A']:.2f} | {cov['L3']:.2f} | {cov['L5']:.2f} | "
                     f"{cov['U5']:.2f} | {','.join(entry['missing']) or '—'} | "
                     f"{','.join(entry['missing_covered_by_L5']) or '—'} |")
    lines += ["", f"gates: {json.dumps(report['gates'], sort_keys=True)}"]
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out",
                        default=str(HERE / "results" / "annotation_coverage_v1"))
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    report = collect()
    second = collect()
    report["gates"]["A2_determinism"] = (
        json.dumps(report["per_case"], sort_keys=True)
        == json.dumps(second["per_case"], sort_keys=True))
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
