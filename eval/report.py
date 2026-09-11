"""Consolidate every archived benchmark into docs/RESULTS.md and CSV tables.

Reads only ``eval/archive`` and ``eval/out`` and never re-runs anything: these
are the frozen numbers reported in the v1.0 paper. Deterministic.

Run:  python3 eval/report.py
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ARCHIVE = HERE / "archive"
OUT = HERE / "out"
TABLES = HERE / "tables"
DOCS = HERE.parent / "docs"

HYPOTHESES = [
    ("H1", "Perspective agents over views retrieve better than partition agents",
     "confirmed", "1.00 complete evidence @ 5.0 calls (7 categories); group agents 15.2 calls; lexical 0.97 @ 3.0"),
    ("H2", "Delivering factual content (not only notes) improves answers",
     "confirmed", "strict 0.72 -> 0.88, AUR 0.74 -> 0.90 at equal evidence (0.97) and cost (4.0-4.1)"),
    ("H3", "A budgeted payload preserves accuracy with far less context",
     "confirmed (relative)", "6000: 0.60 @ 5.5k vs full 0.58 @ 12.9k (-57%); 4000: 0.56 @ 3.8k (-70%); knee ~4000"),
    ("H4", "A memory-aware answer prompt fixes the remaining gap",
     "refuted", "payload 0.56 -> 0.50; gold-evidence condition 0.52 both"),
    ("H5", "Multi-session evidence aggregation is the bottleneck",
     "refuted", "multi-session was the easiest category (0.77); temporal-reasoning the worst (0.29)"),
    ("H5'", "Restoring real session/question timestamps improves temporal reasoning",
     "confirmed", "temporal-reasoning 0.29 -> 0.64; temporal | evidence complete 0.44 -> 1.00 (9/9); overall 0.56 -> 0.64, AUR 0.76 -> 0.89"),
    ("H6a", "An explicit temporal-computation procedure fixes the rest",
     "refuted (on temporal)", "temporal 0.64 -> 0.64; overall 0.64 -> 0.70 from small-n non-temporal cases"),
]


def mean(rows: list[dict[str, Any]], key: str) -> float:
    return sum(float(r.get(key) or 0) for r in rows) / len(rows) if rows else 0.0


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def rows_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    complete = [r for r in rows if r.get("evidence_complete") == 1]
    strict = sum(1 for r in rows if r["judge"]["verdict"] == "correct")
    lenient = sum(1 for r in rows if r["judge"]["verdict"] in {"correct", "partial"})
    aur = (
        sum(1 for r in complete if r["judge"]["verdict"] == "correct") / len(complete)
        if complete
        else None
    )
    gfr = [r.get("gfr") for r in rows if r.get("gfr") is not None]
    chars = [max(r.get("context_chars", 0), r.get("payload_chars", 0)) for r in rows]
    return {
        "n": len(rows),
        "evidence": len(complete) / len(rows) if rows else 0.0,
        "strict": strict / len(rows) if rows else 0.0,
        "lenient": lenient / len(rows) if rows else 0.0,
        "aur": aur if aur is not None else "",
        "gfr": (sum(gfr) / len(gfr)) if gfr else "",
        "fact_coverage": mean(rows, "fact_coverage"),
        "chars": (sum(chars) / len(chars)) if chars else 0.0,
        "calls": mean(rows, "calls"),
    }


def write_csv(name: str, header: list[str], rows: list[list[Any]]) -> None:
    TABLES.mkdir(parents=True, exist_ok=True)
    with (TABLES / name).open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(header)
        writer.writerows(rows)


def verify_checksums() -> list[str]:
    path = ARCHIVE / "CHECKSUMS.txt"
    if not path.exists():
        return ["no CHECKSUMS.txt"]
    bad: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        digest, rel = line.split("  ", 1)
        target = HERE.parent / rel
        if not target.exists():
            bad.append(f"missing: {rel}")
            continue
        actual = hashlib.sha256(target.read_bytes()).hexdigest()
        if actual != digest:
            bad.append(f"changed: {rel}")
    return bad


# ------------------------------------------------------------------ routing


def routing_table() -> list[list[Any]]:
    rows: list[list[Any]] = []
    for path in sorted((ARCHIVE / "routing").glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        for arm, arm_rows in data.get("arms", {}).items():
            rows.append(
                [
                    arm, len(arm_rows),
                    round(mean(arm_rows, "view_recall"), 2),
                    round(mean(arm_rows, "view_precision"), 2),
                    round(mean(arm_rows, "dimension_recall"), 2),
                    round(mean(arm_rows, "dimension_precision"), 2),
                    round(mean(arm_rows, "recovery_redundancy"), 2),
                    round(mean(arm_rows, "complete_evidence"), 2),
                    round(mean(arm_rows, "agent_recall"), 2),
                    round(mean(arm_rows, "reduction"), 2),
                    round(mean(arm_rows, "calls"), 1),
                    round(mean(arm_rows, "latency"), 1),
                ]
            )
    return rows


# ---------------------------------------------------------------- attention


STAB_RE = re.compile(
    r"^(view_\w+)\s+(\d+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+(\d+)\s+(\d+)\s+(\d+)\s*$"
)
CONV_RE = re.compile(
    r"^(\w+)\s+(\w+)\s+(\d+)\s+(\w+)\s+(\d+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s*$"
)


def attention_tables() -> tuple[list[list[Any]], list[list[Any]]]:
    stability: list[list[Any]] = []
    conversation: list[list[Any]] = []
    for path in sorted((ARCHIVE / "logs").glob("view_*.log")):
        for line in path.read_text(encoding="utf-8").splitlines():
            m = STAB_RE.match(line.strip())
            if m:
                arm, task, modal, jac, ecomp, calls, router, attn, both = m.groups()
                stability.append([arm, int(task), float(modal), float(jac), float(ecomp),
                                  float(calls), int(router), int(attn), int(both)])
    for path in sorted((ARCHIVE / "logs").glob("mm-conv[0-9]*.log")):
        for line in path.read_text(encoding="utf-8").splitlines():
            m = CONV_RE.match(line.strip())
            if m and m.group(2) in {"anaphora", "topic_shift"}:
                arm, conv, turn, kind, ecomp, arec, calls, churn, top, old = m.groups()
                conversation.append([arm, conv, int(turn), kind, int(ecomp), float(arec),
                                     float(calls), float(churn), float(top), float(old)])
    return stability, conversation


# ----------------------------------------------------------------- e2e rows


def e2e_tables() -> tuple[list[list[Any]], list[list[Any]]]:
    synthetic: list[list[Any]] = []
    external: list[list[Any]] = []
    header = ["arm", "dataset_variant", "n", "evidence", "strict", "lenient", "AUR", "GFR",
              "fact_cov", "chars", "calls"]
    for path in sorted(OUT.glob("e2e_*.jsonl")):
        name = path.stem[len("e2e_"):]
        if "longmemeval" in name or "BUGGY" in name:
            continue
        rows = load_jsonl(path)
        if not rows:
            continue
        s = rows_summary(rows)
        synthetic.append([rows[0]["arm"], "synthetic", s["n"], round(s["evidence"], 2),
                          round(s["strict"], 2), round(s["lenient"], 2),
                          round(s["aur"], 2) if s["aur"] != "" else "",
                          round(s["gfr"], 2) if s["gfr"] != "" else "",
                          round(s["fact_coverage"], 2), round(s["chars"]), round(s["calls"], 1)])
    for path in sorted(OUT.glob("e2e_*longmemeval*.jsonl")):
        name = path.stem[len("e2e_"):]
        if "BUGGY" in name:
            continue
        rows = load_jsonl(path)
        if not rows:
            continue
        s = rows_summary(rows)
        external.append([rows[0]["arm"], name, s["n"], round(s["evidence"], 2),
                         round(s["strict"], 2), round(s["lenient"], 2),
                         round(s["aur"], 2) if s["aur"] != "" else "",
                         round(s["gfr"], 2) if s["gfr"] != "" else "",
                         round(s["fact_coverage"], 2), round(s["chars"]), round(s["calls"], 1)])
    return synthetic, external


# ------------------------------------------------------------------- audits


def audit_table() -> list[list[Any]]:
    rows: list[list[Any]] = []
    for path in sorted(OUT.glob("judge_audit_*.jsonl")):
        if "BUGGY" in path.stem:
            continue
        items = load_jsonl(path)
        if not items:
            continue
        agree = sum(1 for r in items if r["first_verdict"] == r["audit_verdict"])
        rows.append([path.stem[len("judge_audit_"):], len(items), agree, round(agree / len(items), 2)])
    return rows


def main() -> None:
    DOCS.mkdir(parents=True, exist_ok=True)
    routing = routing_table()
    stability, conversation = attention_tables()
    synthetic, external = e2e_tables()
    audits = audit_table()
    problems = verify_checksums()

    write_csv("routing.csv",
              ["arm", "n", "view_recall", "view_precision", "dim_recall", "dim_precision",
               "recovery", "complete_evidence", "agent_recall", "reduction", "calls", "latency"],
              routing)
    write_csv("attention_stability.csv",
              ["arm", "task", "modal", "jaccard", "ecomp", "calls", "router", "attention", "both"],
              stability)
    write_csv("attention_conversation.csv",
              ["arm", "conversation", "turn", "kind", "ecomp", "arec", "calls", "churn",
               "attention_top", "old_residual"],
              conversation)
    write_csv("e2e_synthetic.csv",
              ["arm", "dataset", "n", "evidence", "strict", "lenient", "AUR", "GFR", "fact_cov",
               "chars", "calls"],
              synthetic)
    write_csv("e2e_longmemeval.csv",
              ["arm", "variant", "n", "evidence", "strict", "lenient", "AUR", "GFR", "fact_cov",
               "chars", "calls"],
              external)
    write_csv("judge_audit.csv", ["arm", "n", "agree", "rate"], audits)

    lines: list[str] = [
        "# Memory Machine v1.0 — consolidated results",
        "",
        "Generated by `eval/report.py` from the frozen archive (`eval/archive`) and the",
        "e2e snapshots (`eval/out`). Do not re-run the experiments for these tables.",
        "",
        "## Hypotheses",
        "",
        "| # | Hypothesis | Outcome | Key numbers |",
        "|---|------------|---------|-------------|",
    ]
    for hid, text, outcome, numbers in HYPOTHESES:
        lines.append(f"| {hid} | {text} | {outcome} | {numbers} |")

    def table(title: str, header: list[str], rows: list[list[Any]]) -> None:
        lines.append("")
        lines.append(f"## {title}")
        lines.append("")
        lines.append("| " + " | ".join(header) + " |")
        lines.append("|" + "|".join(["---"] * len(header)) + "|")
        for row in rows:
            lines.append("| " + " | ".join(str(x) for x in row) + " |")

    table("View / dimension routing benchmark (frozen fixture)",
          ["arm", "n", "view_recall", "view_precision", "dim_recall", "dim_precision",
           "recovery", "complete_evidence", "agent_recall", "reduction", "calls", "latency"],
          routing)
    table("Attention stability (N=5 x 8 focused tasks)",
          ["arm", "task", "modal", "jaccard", "ecomp", "calls", "router", "attention", "both"],
          stability)
    table("Attention conversation",
          ["arm", "conversation", "turn", "kind", "ecomp", "arec", "calls", "churn",
           "attention_top", "old_residual"],
          conversation)
    table("End-to-end answer accuracy — synthetic fixture",
          ["arm", "dataset", "n", "evidence", "strict", "lenient", "AUR", "GFR", "fact_cov",
           "chars", "calls"],
          synthetic)
    table("End-to-end answer accuracy — LongMemEval (50q unless the variant says otherwise)",
          ["arm", "variant", "n", "evidence", "strict", "lenient", "AUR", "GFR", "fact_cov",
           "chars", "calls"],
          external)
    table("Judge audit agreement", ["arm", "n", "agree", "rate"], audits)

    lines += [
        "",
        "## Reproducibility",
        "",
        f"- Archive checksums verified: {len(problems)} problem(s).",
        "- Raw snapshots: `eval/out/*.jsonl` (gitignored) with sha256 in",
        "  `eval/archive/CHECKSUMS.txt`.",
        "- Harnesses: `eval/view_router_bench.py`, `eval/stability_bench.py`,",
        "  `eval/conversation_bench.py`, `eval/continuity_bench.py`,",
        "  `eval/external_bench.py`, `eval/e2e_bench.py`.",
        "- The continuity benchmark output was not archived; see the manual, section 40.8.",
    ]
    (DOCS / "RESULTS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote docs/RESULTS.md and {len(list(TABLES.glob('*.csv')))} CSV tables")
    if problems:
        print("checksum problems:", problems)


if __name__ == "__main__":
    main()
