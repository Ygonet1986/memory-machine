#!/usr/bin/env python3
"""Lifecycle v3 — IDF coverage + candidacy margin (deterministic).

Frozen by docs/LIFECYCLE_V3_PREREG.md. Variants in one run:
  V3-A  IDF coverage (OR zero-overlap)          no margin
  V3-B  IDF coverage (OR zero-overlap)          margin 0.50 x best   (primary)
  V3-C  v2 plain coverage (OR zero-overlap)     margin 0.50 x best
Classifier, retriever, fixture and projection stay frozen.

    PYTHONPATH=src python3 eval/lifecycle_retroactive_v3.py [--out DIR]
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "src"))

from memory_machine import lifecycle as lc  # noqa: E402
from memory_machine.retrieval import tokenize  # noqa: E402

import lifecycle_shadow as shadow  # noqa: E402
from lifecycle_retroactive import SEARCHABLE_CLASS, TOP_K, rank  # noqa: E402
from lifecycle_retroactive_v2 import (  # noqa: E402
    COVERAGE_THRESHOLD,
    MIN_TOKEN_LEN,
    content_tokens,
    coverage as plain_coverage,
)

MARGIN = 0.50
V2_REPORT = HERE / "results" / "lifecycle_v1_retroactive_v2" / "report_v2.json"


def idf_scores(corpus_tokens: list[list[str]]) -> tuple[dict[str, float], int]:
    docs = len(corpus_tokens)
    df: Counter = Counter()
    for tokens in corpus_tokens:
        df.update(set(tokens))
    return ({token: math.log((docs + 1) / (count + 1)) + 1.0
             for token, count in df.items()}, docs)


def idf_coverage(question: str, active_texts: dict[str, str],
                 active_rank: list[dict[str, Any]],
                 corpus_tokens: list[list[str]]) -> float:
    q_tokens = content_tokens(question)
    if not q_tokens:
        return 1.0
    idf, _docs = idf_scores(corpus_tokens)
    covered: set[str] = set()
    for candidate in active_rank:
        covered |= content_tokens(active_texts.get(candidate["memory_id"], ""))
    numerator = sum(idf.get(token, 1.0) for token in q_tokens & covered)
    denominator = sum(idf.get(token, 1.0) for token in q_tokens)
    return numerator / denominator if denominator else 1.0


def with_margin(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not candidates:
        return []
    best = max(candidate["score"] for candidate in candidates)
    return [candidate for candidate in candidates
            if candidate["score"] >= MARGIN * best]


def run(fixture: Path, projection_root: Path) -> dict[str, Any]:
    records, _gold, probes = shadow.load_fixture(fixture)
    decisions = {d.memory_id: d for d in
                 (lc.Decision.from_dict(row) for row in
                  lc.LifecycleProjection(projection_root).load_decisions())}
    seq_by_id = {row["memory_id"]: row["seq"] for row in records}

    variants = ("V3-A", "V3-B", "V3-C")
    counters = {v: {"recoverable_false_negative": 0, "retroactively_found": 0,
                    "retroactively_missed": 0, "fallback_triggered": 0,
                    "fallback_not_triggered": 0, "irrelevant_retroactive_hits": 0}
                for v in variants}
    delivered = {v: 0 for v in variants}
    recovered_req = {v: 0 for v in variants}
    fires_needed = {v: 0 for v in variants}
    combined = {v: 0 for v in variants}
    needed_probes = probes_total = combined_total = 0
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
        cov_plain = plain_coverage(probe["question"], active_items, active_rank)
        zero = len(active_rank) == 0
        needed = [mid for mid in required if mid not in active_ids]
        if needed:
            needed_probes += 1
        retro_full = rank(probe["question"], event_items)
        retro_margin = with_margin(retro_full)
        combined_total += len(required)

        triggers = {
            "V3-A": cov_idf < COVERAGE_THRESHOLD or zero,
            "V3-B": cov_idf < COVERAGE_THRESHOLD or zero,
            "V3-C": cov_plain < COVERAGE_THRESHOLD or zero,
        }
        margins = {"V3-A": retro_full, "V3-B": retro_margin, "V3-C": retro_margin}

        entry = {"probe_id": probe["probe_id"], "coverage_idf": round(cov_idf, 4),
                 "coverage_plain": round(cov_plain, 4), "needed": needed,
                 "variants": {}}
        for variant in variants:
            fired = triggers[variant]
            counters[variant]["fallback_triggered" if fired
                              else "fallback_not_triggered"] += 1
            found: list[str] = []
            irrelevant = 0
            delivered_ids: list[str] = []
            if fired:
                for candidate in margins[variant]:
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
        per_probe.append(entry)

    report: dict[str, Any] = {
        "fixture": str(fixture),
        "thresholds": {"coverage_idf": COVERAGE_THRESHOLD,
                       "margin": MARGIN, "min_token_len": MIN_TOKEN_LEN,
                       "top_k": TOP_K},
        "probes_total": probes_total,
        "probes_needing_fallback": needed_probes,
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
    v2 = {}
    if V2_REPORT.exists():
        v2 = json.loads(V2_REPORT.read_text(encoding="utf-8"))["variants"]["T3"]
    primary = report["variants"]["V3-B"]
    report["gates"] = {
        "H3-1_trigger_quality": primary["trigger_quality"] >= 0.75,
        "H3-2_recovery": primary["retroactive_recovery_rate"] >= 0.80,
        "H3-3_precision": primary["retroactive_precision_at_k"] >= 0.80,
        "H3-4_combined_recall": primary["combined_recall_occurrences"] >= 0.93,
        "H3-5_selective": primary["fallback_rate"] <= 0.50,
        "H3-6_no_regression": bool(v2) and (
            primary["trigger_quality"] >= v2["trigger_quality"]
            and primary["combined_recall_occurrences"]
            >= v2["combined_recall_occurrences"]),
    }
    report["gates"]["all_pass"] = all(report["gates"].values())
    report["v2_reference"] = v2
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", default="eval/fixtures/lifecycle_v1")
    parser.add_argument("--projection",
                        default="eval/results/lifecycle_v1_report/projection")
    parser.add_argument("--out", default="eval/results/lifecycle_v1_retroactive_v3")
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    report = run(Path(args.fixture), Path(args.projection))
    (out / "report_v3.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8")
    lines = ["# Lifecycle v3 — IDF coverage + candidacy margin", "",
             f"- thresholds: {json.dumps(report['thresholds'], sort_keys=True)}", "",
             "| variant | trigger quality | fallback rate | recovery | precision@k | combined recall |",
             "|---|---:|---:|---:|---:|---:|"]
    for variant in ("V3-A", "V3-B", "V3-C"):
        v = report["variants"][variant]
        lines.append(f"| {variant} | {v['trigger_quality']:.3f} | {v['fallback_rate']:.3f} | "
                     f"{v['retroactive_recovery_rate']:.3f} | "
                     f"{v['retroactive_precision_at_k']:.3f} | "
                     f"{v['combined_recall_occurrences']:.3f} |")
    if report.get("v2_reference"):
        v2 = report["v2_reference"]
        lines.append(f"| (v2 T3) | {v2['trigger_quality']:.3f} | {v2['fallback_rate']:.3f} | "
                     f"{v2['retroactive_recovery_rate']:.3f} | "
                     f"{v2['retroactive_precision_at_k']:.3f} | "
                     f"{v2['combined_recall_occurrences']:.3f} |")
    lines += ["", f"gates: {json.dumps(report['gates'], sort_keys=True)}", "",
              "## Per probe (primary V3-B)", "",
              "| probe | cov_idf | cov_plain | T fired | needed | delivered | found |",
              "|---|---:|---:|---|---|---|---|"]
    for entry in report["per_probe"]:
        b = entry["variants"]["V3-B"]
        lines.append(f"| {entry['probe_id']} | {entry['coverage_idf']:.2f} | "
                     f"{entry['coverage_plain']:.2f} | {b['fired']} | "
                     f"{entry['needed'] or '—'} | {b['delivered'] or '—'} | "
                     f"{b['found'] or '—'} |")
    (out / "report_v3.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines[:14]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
