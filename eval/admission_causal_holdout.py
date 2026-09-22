#!/usr/bin/env python3
"""admission-causal holdout runner: the single frozen-policy evaluation.

Frozen by docs/ADMISSION_CAUSAL_HOLDOUT_PREREG.md. Runs S vs B once on the
holdout fixture and evaluates gates H1-H6.

    PYTHONPATH=src:.:eval python3 eval/admission_causal_holdout.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "src"))

import admission_causal_v2 as policy  # noqa: E402


def evaluate(fixture: Path) -> dict:
    report = policy.collect(fixture)
    b = report["policies"]["B"]
    s = report["policies"]["S"]
    digest = policy.content_digest(report)
    again = policy.content_digest(policy.collect(fixture))
    gates = {
        "H1_availability": (s["availability"] >= 0.90
                            and s["availability"] > b["availability"]),
        "H2_precision": (s["precision"] >= 0.70 and s["precision"] >= b["precision"]),
        "H3_factual_control": (
            s["scenario_availability"]["factual_control"]
            >= b["scenario_availability"]["factual_control"]
            and s["scenario_precision"]["factual_control"]
            >= b["scenario_precision"]["factual_control"] - 0.05),
        "H4_absence": (
            s["scenario_availability"]["causal_absent"]
            >= b["scenario_availability"]["causal_absent"]
            and s["undue_rate"] <= b["undue_rate"] + 0.05),
        "H5_budget": s["max_items"] <= 3,
        "H6_determinism": digest == again,
    }
    report["gates"] = gates
    report["all_pass"] = all(gates.values())
    report["evaluation"] = "single (holdout, frozen policy)"
    return report


def render(report: dict) -> list[str]:
    lines = ["# admission-causal holdout (single evaluation)", "",
             f"- cases: {report['cases']} · gold: {report['gold_occurrences']}"
             f" · slot used: {report['slot_used_total']}",
             "",
             "| policy | availability | precision | delivered | max items | undue (absent) |",
             "|---|---:|---:|---:|---:|---:|"]
    for name in ("B", "S"):
        data = report["policies"][name]
        lines.append(f"| {name} | {data['availability']:.3f} | {data['precision']:.3f} | "
                     f"{data['delivered']} | {data['max_items']} | {data['undue_rate']:.3f} |")
    lines += ["", f"gates: {json.dumps(report['gates'], sort_keys=True)}",
              f"all_pass: {report['all_pass']}", "",
              "## Per-scenario availability", "",
              "| scenario | B | S |", "|---|---:|---:|"]
    for scenario in sorted(report["policies"]["S"]["scenario_availability"]):
        row = []
        for name in ("B", "S"):
            value = report["policies"][name]["scenario_availability"].get(scenario)
            row.append("—" if value is None else f"{value:.2f}")
        lines.append(f"| {scenario} | " + " | ".join(row) + " |")
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture",
                        default=str(HERE / "fixtures" / "admission_causal_holdout"))
    parser.add_argument("--out",
                        default=str(HERE / "results" / "admission_causal_holdout"))
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    report = evaluate(Path(args.fixture))
    (out / "report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8")
    markdown = "\n".join(render(report)) + "\n"
    (out / "report.md").write_text(markdown, encoding="utf-8")
    print(markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
