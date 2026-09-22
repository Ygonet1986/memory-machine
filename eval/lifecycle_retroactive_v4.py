#!/usr/bin/env python3
"""Lifecycle v4 — comparative coverage signal (deterministic).

Frozen by docs/LIFECYCLE_V4_PREREG.md. Adds to v3:
comparative trigger: event best score >= 1.25 x active best score.
Variants: V4-A (v3 reference), V4-B (primary, v3 OR comparative),
V4-C (comparative only). Everything else frozen.

    PYTHONPATH=src python3 eval/lifecycle_retroactive_v4.py [--out DIR]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "src"))

from memory_machine import lifecycle as lc  # noqa: E402
from memory_machine.retrieval import tokenize  # noqa: E402

import lifecycle_shadow as shadow  # noqa: E402
from lifecycle_retroactive import SEARCHABLE_CLASS, TOP_K, rank  # noqa: E402
from lifecycle_retroactive_v2 import COVERAGE_THRESHOLD, MIN_TOKEN_LEN  # noqa: E402
from lifecycle_retroactive_v3 import (  # noqa: E402
    MARGIN,
    idf_coverage,
    idf_scores,
    with_margin,
)

COMPARATIVE_FACTOR = 1.25
V3_REPORT = HERE / "results" / "lifecycle_v1_retroactive_v3" / "report_v3.json"


def run(fixture: Path, projection_root: Path) -> dict[str, Any]:
    records, _gold, probes = shadow.load_fixture(fixture)
    decisions = {d.memory_id: d for d in
                 (lc.Decision.from_dict(row) for row in
                  lc.LifecycleProjection(projection_root).load_decisions())}
    seq_by_id = {row["memory_id"]: row["seq"] for row in records}

    variants = ("V4-A", "V4-B", "V4-C")
    counters = {v: {"recoverable_false_negative": 0, "retroactively_found": 0,
                    "retroactively_missed": 0, "fallback_triggered": 0,
                    "fallback_not_triggered": 0, "irrelevant_retroactive_hits": 0}
                for v in variants}
    delivered = {v: 0 for v in variants}
    recovered_req = {v: 0 for v in variants}
    fires_needed = {v: 0 for v in variants}
    combined = {v: 0 for v in variants}
    needed_probes = probes_total = combined_total = 0
    comparative_fires = extra_fires = extra_recovered = extra_irrelevant = 0
    per_probe: list[dict[str, Any]] = []

    for probe in probes:
        if probe.get("unrecoverable"):
            continue
        probes_total += 1
        required = [mid for mid in probe["required_ids"] if mid in seq_by_id]
        active_items = [row for row in records
                        if decisions[row["memory_id"]].promoted
                        and seq_by_id[row["memory_id"]] < probe["after_seq"]]
        event_items = [row for row in records
                       if decisions[row["memory_id"]].target_class == SEARCHABLE_CLASS
                       and seq_by_id[row["memory_id"]] < probe["after_seq"]]
        active_rank = rank(probe["question"], active_items)
        active_ids = [c["memory_id"] for c in active_rank]
        active_texts = {row["memory_id"]: row["text"] for row in active_items}
        corpus_tokens = [tokenize(row["text"]) for row in active_items + event_items]
        cov_idf = idf_coverage(probe["question"], active_texts, active_rank,
                               corpus_tokens)
        zero = len(active_rank) == 0
        v3_trigger = cov_idf < COVERAGE_THRESHOLD or zero
        event_rank = rank(probe["question"], event_items)
        a_star = active_rank[0]["score"] if active_rank else 0.0
        e_star = event_rank[0]["score"] if event_rank else 0.0
        comparative = e_star > 0 and (a_star == 0 or e_star >= COMPARATIVE_FACTOR * a_star)

        needed = [mid for mid in required if mid not in active_ids]
        if needed:
            needed_probes += 1
        candidates = with_margin(event_rank)
        combined_total += len(required)

        triggers = {"V4-A": v3_trigger, "V4-B": v3_trigger or comparative,
                    "V4-C": comparative}
        entry = {"probe_id": probe["probe_id"], "coverage_idf": round(cov_idf, 4),
                 "A_star": a_star, "E_star": e_star, "comparative": comparative,
                 "needed": needed, "variants": {}}
        for variant in variants:
            fired = triggers[variant]
            counters[variant]["fallback_triggered" if fired
                              else "fallback_not_triggered"] += 1
            found: list[str] = []
            irrelevant = 0
            delivered_ids: list[str] = []
            if fired:
                for candidate in candidates:
                    delivered_ids.append(candidate["memory_id"])
                    if candidate["memory_id"] in required:
                        found.append(candidate["memory_id"])
                    else:
                        irrelevant += 1
                delivered[variant] += len(delivered_ids)
                recovered_req[variant] += len(found)
                counters[variant]["irrelevant_retroactive_hits"] += irrelevant
            if needed:
                fires_needed[variant] += int(fired)
            for mid in needed:
                if decisions[mid].target_class != SEARCHABLE_CLASS:
                    continue
                counters[variant]["recoverable_false_negative"] += 1
                if fired and mid in delivered_ids:
                    counters[variant]["retroactively_found"] += 1
                else:
                    counters[variant]["retroactively_missed"] += 1
            available = set(active_ids) | set(found)
            combined[variant] += sum(1 for mid in required if mid in available)
            entry["variants"][variant] = {"fired": fired,
                                          "delivered": delivered_ids,
                                          "found": found}
        # comparative diagnostics
        if comparative:
            comparative_fires += 1
            if not v3_trigger:
                extra_fires += 1
                extra_recovered += len(entry["variants"]["V4-B"]["found"])
                extra_irrelevant += sum(
                    1 for mid in entry["variants"]["V4-B"]["delivered"]
                    if mid not in required)
        per_probe.append(entry)

    report: dict[str, Any] = {
        "fixture": str(fixture),
        "thresholds": {"coverage_idf": COVERAGE_THRESHOLD, "margin": MARGIN,
                       "comparative_factor": COMPARATIVE_FACTOR,
                       "min_token_len": MIN_TOKEN_LEN, "top_k": TOP_K},
        "probes_total": probes_total,
        "probes_needing_fallback": needed_probes,
        "comparative_diagnostics": {
            "comparative_fires": comparative_fires,
            "extra_triggers_vs_v3": extra_fires,
            "extra_recovered": extra_recovered,
            "extra_irrelevant": extra_irrelevant,
        },
        "variants": {},
        "per_probe": per_probe,
    }
    for variant in variants:
        recoverable = counters[variant]["recoverable_false_negative"]
        report["variants"][variant] = {
            "counters": counters[variant],
            "trigger_quality": round(fires_needed[variant] / needed_probes, 4)
            if needed_probes else 0.0,
            "fallback_rate": round(
                counters[variant]["fallback_triggered"] / probes_total, 4)
            if probes_total else 0.0,
            "retroactive_recovery_rate": round(
                counters[variant]["retroactively_found"] / recoverable, 4)
            if recoverable else 0.0,
            "retroactive_precision_at_k": round(
                recovered_req[variant] / delivered[variant], 4)
            if delivered[variant] else 0.0,
            "combined_recall_occurrences": round(combined[variant] / combined_total, 4)
            if combined_total else 0.0,
        }
    v3 = {}
    if V3_REPORT.exists():
        v3 = json.loads(V3_REPORT.read_text(encoding="utf-8"))["variants"]["V3-B"]
    primary = report["variants"]["V4-B"]
    report["gates"] = {
        "H4-1_trigger_quality": primary["trigger_quality"] >= 0.75,
        "H4-2_recovery": primary["retroactive_recovery_rate"] >= 0.80,
        "H4-3_precision": primary["retroactive_precision_at_k"] >= 0.80,
        "H4-4_combined_recall": primary["combined_recall_occurrences"] >= 0.93,
        "H4-5_selective": primary["fallback_rate"] <= 0.50,
        "H4-6_no_regression": bool(v3) and (
            primary["trigger_quality"] >= v3["trigger_quality"]
            and primary["retroactive_precision_at_k"] >= v3["retroactive_precision_at_k"]
            and primary["combined_recall_occurrences"]
            >= v3["combined_recall_occurrences"]),
    }
    report["gates"]["all_pass"] = all(report["gates"].values())
    report["v3_reference"] = v3
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", default="eval/fixtures/lifecycle_v1")
    parser.add_argument("--projection",
                        default="eval/results/lifecycle_v1_report/projection")
    parser.add_argument("--out", default="eval/results/lifecycle_v1_retroactive_v4")
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    report = run(Path(args.fixture), Path(args.projection))
    (out / "report_v4.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8")
    lines = ["# Lifecycle v4 — comparative coverage signal", "",
             f"- thresholds: {json.dumps(report['thresholds'], sort_keys=True)}",
             f"- comparative diagnostics: {json.dumps(report['comparative_diagnostics'], sort_keys=True)}",
             "",
             "| variant | trigger quality | fallback rate | recovery | precision@k | combined recall |",
             "|---|---:|---:|---:|---:|---:|"]
    for variant in ("V4-A", "V4-B", "V4-C"):
        v = report["variants"][variant]
        lines.append(f"| {variant} | {v['trigger_quality']:.3f} | {v['fallback_rate']:.3f} | "
                     f"{v['retroactive_recovery_rate']:.3f} | "
                     f"{v['retroactive_precision_at_k']:.3f} | "
                     f"{v['combined_recall_occurrences']:.3f} |")
    if report.get("v3_reference"):
        v3 = report["v3_reference"]
        lines.append(f"| (v3 B) | {v3['trigger_quality']:.3f} | {v3['fallback_rate']:.3f} | "
                     f"{v3['retroactive_recovery_rate']:.3f} | "
                     f"{v3['retroactive_precision_at_k']:.3f} | "
                     f"{v3['combined_recall_occurrences']:.3f} |")
    lines += ["", f"gates: {json.dumps(report['gates'], sort_keys=True)}", "",
              "## Per probe (primary V4-B)", "",
              "| probe | cov_idf | A* | E* | comparative | T fired | needed | delivered | found |",
              "|---|---:|---:|---:|---|---|---|---|---|"]
    for entry in report["per_probe"]:
        b = entry["variants"]["V4-B"]
        lines.append(f"| {entry['probe_id']} | {entry['coverage_idf']:.2f} | "
                     f"{entry['A_star']:.2f} | {entry['E_star']:.2f} | "
                     f"{entry['comparative']} | {b['fired']} | "
                     f"{entry['needed'] or '—'} | {b['delivered'] or '—'} | "
                     f"{b['found'] or '—'} |")
    (out / "report_v4.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines[:15]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
