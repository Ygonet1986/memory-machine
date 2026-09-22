#!/usr/bin/env python3
"""Lifecycle v2 — coverage-trigger variants T1/T2/T3 (deterministic).

Frozen by docs/LIFECYCLE_V2_PREREG.md. Changes ONLY the coverage trigger;
classifier, promoted set, retriever and fixture stay frozen (v1 harness and
projection untouched).

    PYTHONPATH=src python3 eval/lifecycle_retroactive_v2.py [--out DIR]
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

COVERAGE_THRESHOLD = 0.50
MIN_TOKEN_LEN = 4


def content_tokens(text: str) -> set[str]:
    return {token for token in tokenize(text) if len(token) >= MIN_TOKEN_LEN}


def coverage(question: str, active_items: list[dict[str, Any]],
             active_rank: list[dict[str, Any]]) -> float:
    q_tokens = content_tokens(question)
    if not q_tokens:
        return 1.0
    texts = {row["memory_id"]: row["text"] for row in active_items}
    covered: set[str] = set()
    for candidate in active_rank:
        covered |= content_tokens(texts.get(candidate["memory_id"], ""))
    return len(q_tokens & covered) / len(q_tokens)


def variant_fires(variant: str, t1: bool, cov: float) -> bool:
    if variant == "T1":
        return t1
    if variant == "T2":
        return cov < COVERAGE_THRESHOLD
    return t1 or cov < COVERAGE_THRESHOLD


def run(fixture: Path, projection_root: Path) -> dict[str, Any]:
    records, gold, probes = shadow.load_fixture(fixture)
    decisions = {d.memory_id: d for d in
                 (lc.Decision.from_dict(row) for row in
                  lc.LifecycleProjection(projection_root).load_decisions())}
    seq_by_id = {row["memory_id"]: row["seq"] for row in records}

    variants = ("T1", "T2", "T3")
    counters = {v: {"recoverable_false_negative": 0, "retroactively_found": 0,
                    "retroactively_missed": 0, "fallback_triggered": 0,
                    "fallback_not_triggered": 0, "irrelevant_retroactive_hits": 0}
                for v in variants}
    delivered = {v: 0 for v in variants}
    recovered_req = {v: 0 for v in variants}
    needed_probes = 0
    fires_when_needed = {v: 0 for v in variants}
    probes_total = 0
    combined_found = {v: 0 for v in variants}
    combined_total = 0
    per_probe: list[dict[str, Any]] = []
    unrecoverable = 0

    for probe in probes:
        if probe.get("unrecoverable"):
            unrecoverable += 1
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
        cov = coverage(probe["question"], active_items, active_rank)
        t1 = len(active_rank) == 0
        needed = [mid for mid in required if mid not in active_ids]
        if needed:
            needed_probes += 1
        opportunity = rank(probe["question"], event_items)
        opportunity_ids = [c["memory_id"] for c in opportunity]
        combined_total += len(required)

        entry = {"probe_id": probe["probe_id"], "coverage": round(cov, 4),
                 "t1_zero_overlap": t1, "needed": needed, "variants": {}}
        for variant in variants:
            fired = variant_fires(variant, t1, cov)
            counters[variant]["fallback_triggered" if fired
                              else "fallback_not_triggered"] += 1
            found: list[str] = []
            irrelevant = 0
            if fired:
                for candidate in opportunity:
                    if candidate["memory_id"] in required:
                        found.append(candidate["memory_id"])
                    else:
                        irrelevant += 1
                delivered[variant] += len(opportunity)
                recovered_req[variant] += len(found)
                counters[variant]["irrelevant_retroactive_hits"] += irrelevant
            if needed:
                fires_when_needed[variant] += int(fired)
            for mid in needed:
                if decisions[mid].target_class != SEARCHABLE_CLASS:
                    continue
                counters[variant]["recoverable_false_negative"] += 1
                if fired and mid in opportunity_ids:
                    counters[variant]["retroactively_found"] += 1
                else:
                    counters[variant]["retroactively_missed"] += 1
            available = set(active_ids) | set(found)
            combined_found[variant] += sum(1 for mid in required if mid in available)
            entry["variants"][variant] = {
                "fired": fired,
                "retro_ids": [c["memory_id"] for c in opportunity] if fired else [],
                "found": found,
                "required_available": sorted(mid for mid in required if mid in available),
            }
        per_probe.append(entry)

    report: dict[str, Any] = {
        "fixture": str(fixture),
        "thresholds": {"coverage": COVERAGE_THRESHOLD, "min_token_len": MIN_TOKEN_LEN,
                       "top_k": TOP_K},
        "probes_total": probes_total,
        "probes_needing_fallback": needed_probes,
        "unrecoverable_due_to_ingestion": unrecoverable,
        "variants": {},
        "per_probe": per_probe,
    }
    for variant in variants:
        recoverable = counters[variant]["recoverable_false_negative"]
        report["variants"][variant] = {
            "counters": counters[variant],
            "trigger_quality": round(fires_when_needed[variant] / needed_probes, 4)
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
            "combined_recall_occurrences": round(
                combined_found[variant] / combined_total, 4)
            if combined_total else 0.0,
        }
    t3 = report["variants"]["T3"]
    report["gates"] = {
        "H2-1_trigger_quality": t3["trigger_quality"] >= 0.75,
        "H2-2_recovery": t3["retroactive_recovery_rate"] >= 0.80,
        "H2-3_precision": t3["retroactive_precision_at_k"] >= 0.80,
        "H2-4_combined_recall": t3["combined_recall_occurrences"] >= 0.93,
        "H2-5_selective": t3["fallback_rate"] <= 0.50,
    }
    report["gates"]["all_pass"] = all(report["gates"].values())
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", default="eval/fixtures/lifecycle_v1")
    parser.add_argument("--projection",
                        default="eval/results/lifecycle_v1_report/projection")
    parser.add_argument("--out", default="eval/results/lifecycle_v1_retroactive_v2")
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    report = run(Path(args.fixture), Path(args.projection))
    (out / "report_v2.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8")
    lines = ["# Lifecycle v2 — coverage-trigger variants (frozen pre-registration)", "",
             f"- probes: {report['probes_total']} · needing fallback: "
             f"{report['probes_needing_fallback']} · thresholds: "
             f"{json.dumps(report['thresholds'], sort_keys=True)}", "",
             "| variant | trigger quality | fallback rate | recovery | precision@k | combined recall |",
             "|---|---:|---:|---:|---:|---:|"]
    for variant in ("T1", "T2", "T3"):
        v = report["variants"][variant]
        lines.append(f"| {variant} | {v['trigger_quality']:.3f} | {v['fallback_rate']:.3f} | "
                     f"{v['retroactive_recovery_rate']:.3f} | "
                     f"{v['retroactive_precision_at_k']:.3f} | "
                     f"{v['combined_recall_occurrences']:.3f} |")
    lines += ["", f"gates: {json.dumps(report['gates'], sort_keys=True)}", "",
              "## Per probe (T3)", "",
              "| probe | coverage | T1 | T3 fired | needed | found |",
              "|---|---:|---|---|---|---|"]
    for entry in report["per_probe"]:
        t3 = entry["variants"]["T3"]
        lines.append(f"| {entry['probe_id']} | {entry['coverage']:.2f} | "
                     f"{entry['t1_zero_overlap']} | {t3['fired']} | "
                     f"{entry['needed'] or '—'} | {t3['found'] or '—'} |")
    (out / "report_v2.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines[:12]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
