#!/usr/bin/env python3
"""temporal-breadth-v1: is the u3a-22 class recurring? (delivery-only, no LLM)

Frozen by docs/TEMPORAL_BREADTH_V1_PREREG.md. Compares W1/W3/W5 delivery of
temporal phrases across the 13 temporal-cue cases; W5 pinned by source hash.

    PYTHONPATH=src:.:eval python3 eval/temporal_breadth_v1.py
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

import delivery_combined_v1 as dc  # noqa: E402
import phrase_delivery_v1 as pd  # noqa: E402
import temporal_phrase_v1 as tp  # noqa: E402
from fact_presence import item_span  # noqa: E402

ARMS = ("W1", "W3", "W5")
W5_SOURCE_SHA = hashlib.sha256(
    inspect.getsource(tp.w5_window).encode()).hexdigest()
DEV = ("u3a", 22)


def collect() -> dict[str, Any]:
    cases, records = dc.load_fixture(HERE / "fixtures" / "composition_u4")
    temporal = [c for c in cases if tp.TEMPORAL_CUE_RE.search(c["question"])]
    rows = []
    for case in temporal:
        contexts = {arm: tp.rebuild(case, records, arm) for arm in ARMS}
        ingested = []
        for memory_id in case["required_ids"]:
            record = records.get((int(case["case"]), memory_id))
            if record is not None:
                ingested.append(f"{record['summary']} {record['why']}")
        gold_phrases = pd.gold_phrases(str(case["gold"]))
        if gold_phrases:
            ingestion_ok = all(
                pd.phrase_present(phrase, " ".join(ingested))
                for phrase in gold_phrases)
        else:
            from fact_presence import atom_present, item_fact_atoms, norm
            atoms = item_fact_atoms(str(case["gold"]))
            ingestion_ok = all(
                atom_present(atom, norm(" ".join(ingested))) for atom in atoms)
        entry: dict[str, Any] = {
            "block": case["block"], "case": case["case"],
            "dev": (case["block"], case["case"]) == DEV,
            "basis": "phrase" if gold_phrases else "atom_fallback",
            "gold": case["gold"], "ingestion_ok": ingestion_ok,
            "arms": {},
        }
        for arm in ARMS:
            result = pd.check(case, contexts[arm], records)
            entry["arms"][arm] = {"ok": result["ok"], "chars": len(contexts[arm])}
        w1, w3, w5 = (entry["arms"][arm]["ok"] for arm in ARMS)
        entry.update({
            "delivery_loss_w1": ingestion_ok and not w1,
            "fixed_by_w5": ingestion_ok and not w1 and w5,
            "w3_regression": w1 and not w3,
            "w5_recovers_w3": w1 and not w3 and w5,
            "w5_regression": w1 and not w5,
        })
        rows.append(entry)

    fixed_non_dev = [r for r in rows if r["fixed_by_w5"] and not r["dev"]]
    losses = [r for r in rows if r["delivery_loss_w1"]]
    w3_regs = [r for r in rows if r["w3_regression"]]
    report = {
        "prereg": "docs/TEMPORAL_BREADTH_V1_PREREG.md",
        "w5_source_sha256": W5_SOURCE_SHA,
        "temporal_cases": len(rows),
        "phrase_cases": sum(1 for r in rows if r["basis"] == "phrase"),
        "rows": rows,
        "counts": {
            "delivery_loss_w1": len(losses),
            "delivery_loss_w1_non_dev": sum(1 for r in losses if not r["dev"]),
            "fixed_by_w5": sum(1 for r in rows if r["fixed_by_w5"]),
            "fixed_by_w5_non_dev": len(fixed_non_dev),
            "w3_regressions": len(w3_regs),
            "w5_recovers_w3": sum(1 for r in rows if r["w5_recovers_w3"]),
            "w5_regressions": sum(1 for r in rows if r["w5_regression"]),
        },
    }
    report["verdict"] = ("recurring_class" if fixed_non_dev else "singleton")
    w0_lengths = {f"{c['block']}:{c['case']}": len(c["context"]) for c in temporal}
    report["gates"] = {
        "V1_consistent": all(
            (not r["fixed_by_w5"] or r["delivery_loss_w1"]) for r in rows),
        "V3_w5_no_regression": all(not r["w5_regression"] for r in rows),
        "V4_budget": all(
            r["arms"][arm]["chars"] <= w0_lengths[f"{r['block']}:{r['case']}"]
            for r in rows for arm in ARMS),
    }
    return report


def render(report: dict[str, Any]) -> list[str]:
    lines = ["# temporal-breadth-v1", "",
             f"- temporal cases: {report['temporal_cases']} · phrase cases: "
             f"{report['phrase_cases']} · verdict: **{report['verdict']}**",
             f"- counts: {json.dumps(report['counts'], sort_keys=True)}", "",
             "| case | dev | basis | ingestion | W1 | W3 | W5 | flags |",
             "|---|---|---|---|---|---|---|---|"]
    for row in report["rows"]:
        flags = ",".join(name for name in
                         ("delivery_loss_w1", "fixed_by_w5", "w3_regression",
                          "w5_recovers_w3", "w5_regression") if row[name]) or "-"
        lines.append(
            f"| {row['block']}:{row['case']} | {'DEV' if row['dev'] else ''} | "
            f"{row['basis']} | {'ok' if row['ingestion_ok'] else 'MISS'} | "
            f"{'ok' if row['arms']['W1']['ok'] else 'MISS'} | "
            f"{'ok' if row['arms']['W3']['ok'] else 'MISS'} | "
            f"{'ok' if row['arms']['W5']['ok'] else 'MISS'} | {flags} |")
    lines += ["", f"gates: {json.dumps(report['gates'], sort_keys=True)}"]
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out",
                        default=str(HERE / "results" / "temporal_breadth_v1"))
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    report = collect()
    second = collect()
    report["gates"]["V2_determinism"] = (
        json.dumps(report["rows"], sort_keys=True)
        == json.dumps(second["rows"], sort_keys=True))
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
