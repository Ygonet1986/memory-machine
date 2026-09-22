#!/usr/bin/env python3
"""Lifecycle v1 — retroactive recovery (step 6, deterministic, contract in
docs/LIFECYCLE_V1_PREREG.md Addendum 2).

Gold never enters the query, the ranking or the trigger. Per probe:

1. temporal filter (seq < after_seq);
2. active recall over the promoted set (product BM25, top_k=5);
3. trigger: no positive score in the active top_k;
4. event-log search over non-promoted, searchable records (event_only only);
5. candidates preserved with their full ranking;
6. only after retrieval, compare with required_ids (reporting only).

Run: PYTHONPATH=src python3 eval/lifecycle_retroactive.py [--out DIR]
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
from memory_machine.retrieval import bm25  # noqa: E402

import lifecycle_shadow as shadow  # noqa: E402

TOP_K = 5  # product default (config.view_top_k)
SEARCHABLE_CLASS = "event_only"


def rank(query: str, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Product BM25 ranking, stable tie-break, positive scores only."""
    if not items:
        return []
    scores = bm25(query, [row["text"] for row in items])
    ranked = sorted(zip(scores, items),
                    key=lambda pair: (-pair[0], pair[1]["seq"], pair[1]["memory_id"]))
    return [{"memory_id": row["memory_id"], "score": round(score, 4), "seq": row["seq"]}
            for score, row in ranked[:TOP_K] if score > 0]


def run(fixture: Path, projection_root: Path) -> dict[str, Any]:
    records, gold, probes = shadow.load_fixture(fixture)
    decisions = {d.memory_id: d for d in
                 (lc.Decision.from_dict(row) for row in
                  lc.LifecycleProjection(projection_root).load_decisions())}
    seq_by_id = {row["memory_id"]: row["seq"] for row in records}

    counters: dict[str, int] = {
        "recoverable_false_negative": 0,
        "retroactively_found": 0,
        "retroactively_missed": 0,
        "unrecoverable_due_to_ingestion": 0,
        "fallback_triggered": 0,
        "fallback_not_triggered": 0,
        "irrelevant_retroactive_hits": 0,
    }
    candidates_delivered = 0
    required_recovered = 0
    trigger_needed = trigger_fired_when_needed = 0
    retriever_opportunities = retriever_hits = 0
    per_probe: list[dict[str, Any]] = []

    for probe in probes:
        if probe.get("unrecoverable"):
            counters["unrecoverable_due_to_ingestion"] += 1
            per_probe.append({"probe_id": probe["probe_id"],
                              "skipped": "unrecoverable_due_to_ingestion"})
            continue
        required = [mid for mid in probe["required_ids"] if mid in seq_by_id]
        active_items = [row for row in records
                        if decisions[row["memory_id"]].promoted
                        and seq_by_id[row["memory_id"]] < probe["after_seq"]]
        event_items = [row for row in records
                       if decisions[row["memory_id"]].target_class == SEARCHABLE_CLASS
                       and seq_by_id[row["memory_id"]] < probe["after_seq"]]

        active_rank = rank(probe["question"], active_items)
        trigger = len(active_rank) == 0
        if trigger:
            counters["fallback_triggered"] += 1
        else:
            counters["fallback_not_triggered"] += 1

        # diagnostic: unconditional opportunity for the event-log retriever
        opportunity = rank(probe["question"], event_items)
        opportunity_ids = [c["memory_id"] for c in opportunity]
        if trigger:
            # protocol: only a triggered fallback may deliver retro candidates
            for candidate in opportunity:
                candidates_delivered += 1
                if candidate["memory_id"] in required:
                    required_recovered += 1
                else:
                    counters["irrelevant_retroactive_hits"] += 1

        # gold-only reporting after retrieval
        active_ids = [c["memory_id"] for c in active_rank]
        needed = [mid for mid in required if mid not in active_ids]
        if needed:
            trigger_needed += 1
            trigger_fired_when_needed += int(trigger)
        for mid in needed:
            if decisions[mid].target_class != SEARCHABLE_CLASS:
                counters.setdefault("required_not_searchable", 0)
                counters["required_not_searchable"] += 1
                continue
            counters["recoverable_false_negative"] += 1
            retriever_opportunities += 1
            if mid in opportunity_ids:
                retriever_hits += 1
                if trigger:
                    counters["retroactively_found"] += 1
                else:
                    counters["retroactively_missed"] += 1
            else:
                counters["retroactively_missed"] += 1
        per_probe.append({
            "probe_id": probe["probe_id"],
            "after_seq": probe["after_seq"],
            "required": required,
            "active_topk": active_rank,
            "trigger_fired": trigger,
            "retro_rank": opportunity,
            "gold_needed": needed,
        })

    recoverable = counters["recoverable_false_negative"]
    report = {
        "fixture": str(fixture),
        "retriever": {"name": "bm25", "k1": 1.5, "b": 0.75, "top_k": TOP_K,
                      "tokenizer": "memory_machine.retrieval.tokenize",
                      "searchable_class": SEARCHABLE_CLASS,
                      "tie_break": "score desc, seq asc, memory_id asc",
                      "threshold": "positive scores only"},
        "counters": counters,
        "metrics": {
            "retroactive_recovery_rate": round(
                counters["retroactively_found"] / recoverable, 4) if recoverable else 0.0,
            "retroactive_precision_at_k": round(
                required_recovered / candidates_delivered, 4)
            if candidates_delivered else 0.0,
        },
        "trigger_quality": {
            "probes_needing_fallback": trigger_needed,
            "fired_when_needed": trigger_fired_when_needed,
            "rate": round(trigger_fired_when_needed / trigger_needed, 4)
            if trigger_needed else 0.0,
        },
        "retriever_capability": {
            "required_checked": retriever_opportunities,
            "required_found_with_opportunity": retriever_hits,
            "rate": round(retriever_hits / retriever_opportunities, 4)
            if retriever_opportunities else 0.0,
        },
        "per_probe": per_probe,
    }
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", default="eval/fixtures/lifecycle_v1")
    parser.add_argument("--projection", default="eval/results/lifecycle_v1_report/projection")
    parser.add_argument("--out", default="eval/results/lifecycle_v1_retroactive")
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    report = run(Path(args.fixture), Path(args.projection))
    (out / "retro_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8")
    counters = report["counters"]
    metrics = report["metrics"]
    lines = [
        "# Lifecycle v1 — retroactive recovery (step 6)",
        "",
        f"- counters: {json.dumps(counters, sort_keys=True)}",
        f"- retroactive recovery rate: {metrics['retroactive_recovery_rate']:.3f}",
        f"- retroactive precision@k: {metrics['retroactive_precision_at_k']:.3f}",
        f"- trigger quality: {report['trigger_quality']}",
        f"- retriever capability: {report['retriever_capability']}",
        "",
        "| probe | trigger | needed | retro top-k |",
        "|---|---|---|---|",
    ]
    for probe in report["per_probe"]:
        if "skipped" in probe:
            lines.append(f"| {probe['probe_id']} | — | — | skipped (ingestion) |")
            continue
        topk = ", ".join(f"{c['memory_id']}({c['score']})" for c in probe["retro_rank"]) or "—"
        lines.append(f"| {probe['probe_id']} | {probe['trigger_fired']} | "
                     f"{probe['gold_needed'] or '—'} | {topk} |")
    (out / "retro_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines[:10]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
