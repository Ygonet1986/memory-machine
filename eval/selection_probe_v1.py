#!/usr/bin/env python3
"""selection-probe-v1: why required records are not annotated (deterministic).

Frozen by docs/SELECTION_PROBE_V1_PREREG.md. No LLM; skips when the frozen
snapshots are absent (they are not versioned).

    PYTHONPATH=src:.:eval python3 eval/selection_probe_v1.py
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
from memory_machine.retrieval import bm25, tokenize  # noqa: E402


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
    case_context = {(c["block"], c["case"]): c for c in cases}

    missing_rows: list[dict[str, Any]] = []
    affected_cases: set[str] = set()
    for snap in snapshots:
        annotated = set(snap.get("agent_ids") or [])
        required = set(snap.get("required_ids") or [])
        missing = sorted(required - annotated)
        if not missing:
            continue
        case = case_context.get((snap["block"], snap["case"]))
        if case is None:
            continue
        affected_cases.add(f'{snap["block"]}:{snap["case"]}')
        case_records = [r for (c, _), r in records.items() if c == snap["case"]]
        texts = [f"{r['summary']} {r['why']}" for r in case_records]
        scores = bm25(snap["question"], texts)
        order = sorted(range(len(texts)), key=lambda i: -scores[i])
        ranked = [case_records[i]["id"] for i in order if scores[i] > 0]
        annotated_records = [r for r in case_records
                             if r["id"] in annotated]
        annotated_views = {v for r in annotated_records
                           for v in (r.get("views") or [])}
        q_tokens = set(tokenize(snap["question"]))
        for memory_id in missing:
            record = next((r for r in case_records
                           if r["id"] == memory_id), None)
            if record is None:
                missing_rows.append({"block": snap["block"],
                                     "case": snap["case"],
                                     "memory_id": memory_id,
                                     "status": "record_not_in_fixture"})
                continue
            rank = ranked.index(memory_id) + 1 if memory_id in ranked else 0
            text = f"{record['summary']} {record['why']}"
            doc_tokens = set(tokenize(text))
            overlap = (round(len(q_tokens & doc_tokens) / len(q_tokens), 4)
                       if q_tokens else 0.0)
            views = set(record.get("views") or [])
            view_overlap = bool(views & annotated_views)
            classification = ("lexically_retrievable_miss"
                              if 1 <= rank <= 5 else "lexical_gap")
            missing_rows.append({
                "block": snap["block"], "case": snap["case"],
                "memory_id": memory_id, "question": snap["question"],
                "gold": snap["gold"], "lexical_rank": rank,
                "lexical_overlap": overlap,
                "view_overlap": view_overlap,
                "view_disjoint": not view_overlap,
                "classification": classification,
                "annotated_ids": sorted(annotated),
            })

    classes = [row for row in missing_rows if "classification" in row]
    report = {
        "prereg": "docs/SELECTION_PROBE_V1_PREREG.md",
        "snapshot_rows": len(snapshots),
        "affected_cases": sorted(affected_cases),
        "missing_records": missing_rows,
        "counts": {
            "missing_records": len(classes),
            "lexically_retrievable_miss": sum(
                1 for r in classes
                if r["classification"] == "lexically_retrievable_miss"),
            "lexical_gap": sum(1 for r in classes
                               if r["classification"] == "lexical_gap"),
            "view_disjoint": sum(1 for r in classes if r["view_disjoint"]),
        },
    }
    report["gates"] = {
        "S1_classified": len(classes) == len(missing_rows),
        "S3_u3a17_visible": any(
            r["block"] == "u3a" and r["case"] == 17
            and r["memory_id"] == "M0043" for r in classes),
    }
    return report


def render(report: dict[str, Any]) -> list[str]:
    lines = ["# selection-probe-v1", "",
             f"- snapshots: {report['snapshot_rows']} cases · affected: "
             f"{len(report['affected_cases'])} · counts: "
             f"{json.dumps(report['counts'], sort_keys=True)}", "",
             "| case | missing | lex rank | overlap | view overlap | class |",
             "|---|---|---:|---:|---|---|"]
    for row in report["missing_records"]:
        if "classification" not in row:
            continue
        lines.append(f"| {row['block']}:{row['case']} | {row['memory_id']} | "
                     f"{row['lexical_rank'] or '—'} | {row['lexical_overlap']:.2f} | "
                     f"{row['view_overlap']} | **{row['classification']}** |")
    lines += ["", f"gates: {json.dumps(report['gates'], sort_keys=True)}"]
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out",
                        default=str(HERE / "results" / "selection_probe_v1"))
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    report = collect()
    second = collect()
    report["gates"]["S2_determinism"] = (
        json.dumps(report["missing_records"], sort_keys=True)
        == json.dumps(second["missing_records"], sort_keys=True))
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
