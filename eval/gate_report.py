#!/usr/bin/env python3
"""G1-G8 report for a harness run — tri-state, informational (L10 scientific CI).

    PASS                        quality criteria met
    FAIL_QUALITY                run completed but the quality gate failed
    INCONCLUSIVE_INFRASTRUCTURE run incomplete / provider failure / no summary

Provider, network and rate-limit failures are reported as infrastructure, never
as a scientific regression. Criteria that this harness does not measure are
reported as NOT_MEASURED instead of being guessed.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SUMMARY_FILES = ("e4_summary.json", "e5_summary.json", "e2_summary.json")


def load_summary(run: Path) -> tuple[str, dict | None]:
    for name in SUMMARY_FILES:
        path = run / name
        if path.exists():
            return name, json.loads(path.read_text(encoding="utf-8"))
    return "", None


def load_answers(run: Path) -> list[dict]:
    path = run / "answers.jsonl"
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def build_report(run: Path) -> dict:
    name, data = load_summary(run)
    answers = load_answers(run)
    if data is None:
        return {
            "run": str(run), "summary": None, "answers": len(answers),
            "verdict": "INCONCLUSIVE_INFRASTRUCTURE",
            "reason": "no harness summary found (run did not complete)",
            "gates": {},
        }

    gate = data.get("gate", {})
    ledger = data.get("accuracy", {}).get("ledger", [])
    arms = data.get("arms", [])
    replicates = int(data.get("n", 0) or 0)
    expected = len(ledger) * max(1, len(arms)) * max(1, replicates) if ledger else 0
    answered = [row for row in answers if row.get("verdict")]
    infra_ok = bool(answers) and len(answered) == len(answers)
    if expected:
        infra_ok = infra_ok and len(answers) >= expected

    guards_ok = (int(gate.get("provenance_failures", 0)) == 0
                 and bool(gate.get("deterministic", False))
                 and bool(gate.get("budget_ok", False)))
    primary = bool(gate.get("primary_pass", gate.get("promote", False)))

    if not infra_ok:
        verdict = "INCONCLUSIVE_INFRASTRUCTURE"
        reason = (f"incomplete run: {len(answers)} answers "
                  f"(expected {expected or 'unknown'})")
    elif primary and guards_ok:
        verdict = "PASS"
        reason = "primary quality gate passed; structural guards green"
    elif primary and not guards_ok:
        verdict = "FAIL_QUALITY"
        reason = "primary passed but a structural guard failed"
    else:
        verdict = "FAIL_QUALITY"
        reason = "primary quality gate failed"

    gates = {
        "G1_response_regression": {
            "status": "PASS" if primary else "FAIL",
            "metric": "paired net vs measured floor",
            "value": gate.get("net", data.get("scaffold_vs_control", {}).get("net")),
            "floor": gate.get("effective_floor"),
        },
        "G2_evidence_recall": {"status": "NOT_MEASURED",
                               "note": "needs the frozen public harness"},
        "G3_composition_recall": {"status": "NOT_MEASURED",
                                  "note": "needs the frozen public harness"},
        "G4_category_floors": {"status": "NOT_MEASURED",
                               "note": "needs the frozen public harness"},
        "G5_calls_online": {"status": "NOT_MEASURED",
                            "note": "needs call telemetry in the public harness"},
        "G6_latency": {"status": "NOT_MEASURED",
                       "note": "needs p50/p95 telemetry"},
        "G7_data_safety": {
            "status": "PASS" if guards_ok else "FAIL",
            "provenance_failures": gate.get("provenance_failures"),
            "deterministic": gate.get("deterministic"),
            "budget_ok": gate.get("budget_ok"),
        },
        "G8_rollback": {"status": "NOT_MEASURED",
                        "note": "manual checklist item"},
    }
    return {
        "run": str(run), "summary": name, "answers": len(answers),
        "expected_answers": expected, "verdict": verdict, "reason": reason,
        "gates": gates,
    }


def render_markdown(report: dict) -> str:
    lines = [
        "# Scientific gate report (G1-G8, informational)",
        "",
        f"- run: `{report['run']}`",
        f"- summary: `{report['summary']}` · answers: {report['answers']}"
        + (f"/{report['expected_answers']}" if report.get("expected_answers") else ""),
        f"- **verdict: {report['verdict']}** — {report['reason']}",
        "",
        "| gate | status | detail |",
        "|---|---|---|",
    ]
    for name, data in report.get("gates", {}).items():
        detail = data.get("note") or json.dumps(
            {k: v for k, v in data.items() if k != "status"}, ensure_ascii=False)
        lines.append(f"| {name} | {data['status']} | {detail} |")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True, help="harness output directory")
    parser.add_argument("--out", default="", help="write report files here")
    args = parser.parse_args()
    run = Path(args.run)
    if not run.exists():
        print(f"INCONCLUSIVE_INFRASTRUCTURE: run directory missing: {run}")
        return 0
    report = build_report(run)
    markdown = render_markdown(report)
    print(markdown)
    out = Path(args.out) if args.out else run
    out.mkdir(parents=True, exist_ok=True)
    (out / "gate_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (out / "gate_report.md").write_text(markdown, encoding="utf-8")
    # Informational only: never fail the caller on quality; only on real errors.
    return 0


if __name__ == "__main__":
    sys.exit(main())
