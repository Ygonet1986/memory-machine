#!/usr/bin/env python3
"""Two-tier retrieval v1 — unconditional cheap event-log search.

Frozen by docs/TWO_TIER_RETRIEVAL_V1_PREREG.md. Arms:
T2-A promote_only, T2-B trigger_v4b (frozen v4 harness output),
T2-C two_tier_combined (PRIMARY, single index over non-rejected records),
T2-CRRF two-index reciprocal-rank fusion (k=60), T2-U unfiltered.
Deterministic; timing is informational only.

    PYTHONPATH=src:.:eval python3 eval/two_tier_retrieval_v1.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Callable

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "src"))

from memory_machine import lifecycle as lc  # noqa: E402
from memory_machine.retrieval import tokenize  # noqa: E402

import lifecycle_shadow as shadow  # noqa: E402
import lifecycle_retroactive_v4 as v4  # noqa: E402
from lifecycle_retroactive import SEARCHABLE_CLASS, TOP_K, rank  # noqa: E402
from lifecycle_retroactive_v3 import (  # noqa: E402
    COVERAGE_THRESHOLD,
    MARGIN,
    MIN_TOKEN_LEN,
    idf_coverage,
    with_margin,
)

RRF_K = 60
WARMUP = 10
REPS = 100
ARMS = ("T2-A", "T2-B", "T2-C", "T2-CRRF", "T2-U")
DEFAULT_FIXTURE = ROOT / "eval" / "fixtures" / "lifecycle_v1"
DEFAULT_PROJECTION = ROOT / "eval" / "results" / "lifecycle_v1_report" / "projection"


def rrf_fuse(lists: list[list[dict[str, Any]]],
             seq_by_id: dict[str, int]) -> list[str]:
    fused: dict[str, float] = {}
    for lst in lists:
        for position, candidate in enumerate(lst, start=1):
            fused[candidate["memory_id"]] = (
                fused.get(candidate["memory_id"], 0.0) + 1.0 / (RRF_K + position))
    ordered = sorted(fused.items(),
                     key=lambda kv: (-kv[1], seq_by_id[kv[0]], kv[0]))
    if not ordered:
        return []
    best = ordered[0][1]
    return [mid for mid, score in ordered if score >= MARGIN * best][:TOP_K]


def arm_b_retrieve(question: str, active_items: list[dict[str, Any]],
                   event_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The frozen v4-B path: v3 trigger OR comparative, then margin."""
    active_rank = rank(question, active_items)
    active_texts = {row["memory_id"]: row["text"] for row in active_items}
    corpus_tokens = [tokenize(row["text"]) for row in active_items + event_items]
    cov_idf = idf_coverage(question, active_texts, active_rank, corpus_tokens)
    zero = len(active_rank) == 0
    trigger = cov_idf < COVERAGE_THRESHOLD or zero
    event_rank = rank(question, event_items)
    a_star = active_rank[0]["score"] if active_rank else 0.0
    e_star = event_rank[0]["score"] if event_rank else 0.0
    comparative = e_star > 0 and (a_star == 0
                                  or e_star >= v4.COMPARATIVE_FACTOR * a_star)
    if trigger or comparative:
        return with_margin(event_rank)
    return []


def percentile(samples: list[float], fraction: float) -> float:
    ordered = sorted(samples)
    index = min(len(ordered) - 1, max(0, round(fraction * (len(ordered) - 1))))
    return ordered[index]


def collect(fixture: Path, projection_root: Path) -> dict[str, Any]:
    records, _gold, probes = shadow.load_fixture(fixture)
    decisions = {d.memory_id: d for d in
                 (lc.Decision.from_dict(row) for row in
                  lc.LifecycleProjection(projection_root).load_decisions())}
    seq_by_id = {row["memory_id"]: row["seq"] for row in records}
    v4_report = v4.run(fixture, projection_root)
    v4_probe = {entry["probe_id"]: entry for entry in v4_report["per_probe"]}

    counters = {arm: {"delivered": 0, "found": 0, "chars": 0, "corpus_records": []}
                for arm in ARMS}
    occurrences_total = 0
    probes_used = 0
    per_probe: list[dict[str, Any]] = []

    for probe in probes:
        if probe.get("unrecoverable"):
            continue
        probes_used += 1
        required = [mid for mid in probe["required_ids"] if mid in seq_by_id]
        occurrences_total += len(required)
        cutoff = [row for row in records if seq_by_id[row["memory_id"]] < probe["after_seq"]]
        active_items = [row for row in cutoff
                        if decisions[row["memory_id"]].promoted]
        event_items = [row for row in cutoff
                       if decisions[row["memory_id"]].target_class == SEARCHABLE_CLASS]
        union_items = [row for row in cutoff
                       if decisions[row["memory_id"]].promoted
                       or decisions[row["memory_id"]].target_class == SEARCHABLE_CLASS]
        assert len(active_items) + len(event_items) == len(union_items)

        q = probe["question"]
        active_delivered = [c["memory_id"] for c in with_margin(rank(q, active_items))]
        fallback_b = v4_probe[probe["probe_id"]]["variants"]["V4-B"]["delivered"]
        live_b = [c["memory_id"] for c in
                  arm_b_retrieve(q, active_items, event_items)]
        assert live_b == fallback_b, probe["probe_id"]
        delivered = {
            "T2-A": active_delivered,
            "T2-B": list(dict.fromkeys(active_delivered + fallback_b)),
            "T2-C": [c["memory_id"] for c in with_margin(rank(q, union_items))],
            "T2-CRRF": rrf_fuse([rank(q, active_items), rank(q, event_items)],
                                seq_by_id),
            "T2-U": [c["memory_id"] for c in with_margin(rank(q, cutoff))],
        }

        entry = {"probe_id": probe["probe_id"], "required": required}
        for arm in ARMS:
            mids = delivered[arm]
            found = [mid for mid in mids if mid in required]
            chars = sum(len(next(row["text"] for row in records
                                 if row["memory_id"] == mid)) for mid in mids)
            counters[arm]["delivered"] += len(mids)
            counters[arm]["found"] += len(found)
            counters[arm]["chars"] += chars
            counters[arm]["corpus_records"].append({
                "T2-A": len(active_items), "T2-B": len(active_items),
                "T2-C": len(union_items), "T2-CRRF": len(union_items),
                "T2-U": len(cutoff)}[arm])
            entry[arm] = {"delivered": mids, "found": found, "chars": chars}
        per_probe.append(entry)

    assert probes_used == 19 and occurrences_total == 21, (probes_used, occurrences_total)

    report: dict[str, Any] = {
        "prereg": "docs/TWO_TIER_RETRIEVAL_V1_PREREG.md",
        "fixture": str(fixture),
        "projection": str(projection_root),
        "thresholds": {"top_k": TOP_K, "margin": MARGIN, "rrf_k": RRF_K,
                       "coverage_idf": COVERAGE_THRESHOLD,
                       "comparative_factor": v4.COMPARATIVE_FACTOR,
                       "min_token_len": MIN_TOKEN_LEN},
        "probes_used": probes_used,
        "required_occurrences": occurrences_total,
        "calls_added": 0,
        "index_stats": {
            arm: {"mean_records": round(statistics.fmean(
                counters[arm]["corpus_records"]), 2),
                "persistent_index": False}
            for arm in ARMS},
        "arms": {}, "per_probe": per_probe, "gates": {},
    }
    for arm in ARMS:
        data = counters[arm]
        report["arms"][arm] = {
            "delivered": data["delivered"],
            "found": data["found"],
            "availability": round(data["found"] / occurrences_total, 4),
            "precision_at_k": round(data["found"] / data["delivered"], 4)
            if data["delivered"] else 0.0,
            "mean_chars": round(data["chars"] / probes_used, 2),
        }
    c = report["arms"]["T2-C"]
    u = report["arms"]["T2-U"]
    b = report["arms"]["T2-B"]
    report["gates"] = {
        "H2T-1_availability": c["availability"] >= 1.0
        and c["availability"] > b["availability"],
        "H2T-2_precision": c["precision_at_k"] >= 0.80,
        "H2T-3_budget": c["mean_chars"] <= 1.25 * report["arms"]["T2-A"]["mean_chars"],
        "H2T-4_no_regression_vs_unfiltered": c["precision_at_k"]
        >= u["precision_at_k"] - 0.05,
    }
    report["v4_reference"] = {
        "T2-B_combined_recall": v4_report["variants"]["V4-B"]["combined_recall_occurrences"],
        "T2-B_precision": v4_report["variants"]["V4-B"]["retroactive_precision_at_k"],
    }
    assert report["arms"]["T2-B"]["availability"] == report["v4_reference"]["T2-B_combined_recall"]
    return report


def add_timing(report: dict[str, Any], fixture: Path,
               projection_root: Path) -> None:
    records, _gold, probes = shadow.load_fixture(fixture)
    decisions = {d.memory_id: d for d in
                 (lc.Decision.from_dict(row) for row in
                  lc.LifecycleProjection(projection_root).load_decisions())}
    seq_by_id = {row["memory_id"]: row["seq"] for row in records}

    def make_callable(arm: str, question: str,
                      active_items: list[dict[str, Any]],
                      event_items: list[dict[str, Any]],
                      union_items: list[dict[str, Any]],
                      cutoff: list[dict[str, Any]]) -> Callable[[], Any]:
        if arm == "T2-A":
            return lambda: with_margin(rank(question, active_items))
        if arm == "T2-B":
            return lambda: arm_b_retrieve(question, active_items, event_items)
        if arm == "T2-C":
            return lambda: with_margin(rank(question, union_items))
        if arm == "T2-CRRF":
            return lambda: rrf_fuse([rank(question, active_items),
                                     rank(question, event_items)], seq_by_id)
        return lambda: with_margin(rank(question, cutoff))

    samples: dict[str, list[float]] = {arm: [] for arm in ARMS}
    for probe in probes:
        if probe.get("unrecoverable"):
            continue
        cutoff = [row for row in records
                  if seq_by_id[row["memory_id"]] < probe["after_seq"]]
        active_items = [row for row in cutoff
                        if decisions[row["memory_id"]].promoted]
        event_items = [row for row in cutoff
                       if decisions[row["memory_id"]].target_class == SEARCHABLE_CLASS]
        union_items = [row for row in cutoff
                       if decisions[row["memory_id"]].promoted
                       or decisions[row["memory_id"]].target_class == SEARCHABLE_CLASS]
        for arm in ARMS:
            call = make_callable(arm, probe["question"], active_items,
                                 event_items, union_items, cutoff)
            for _ in range(WARMUP):
                call()
            for _ in range(REPS):
                start = time.perf_counter()
                call()
                samples[arm].append((time.perf_counter() - start) * 1000.0)
    report["latency_ms"] = {
        arm: {"p50": round(percentile(samples[arm], 0.50), 3),
              "p95": round(percentile(samples[arm], 0.95), 3),
              "samples": len(samples[arm])}
        for arm in ARMS}


def content_digest(report: dict[str, Any]) -> str:
    payload = {k: v for k, v in report.items() if k != "latency_ms"}
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def run(fixture: Path, projection_root: Path) -> dict[str, Any]:
    report = collect(fixture, projection_root)
    first = content_digest(report)
    second = content_digest(collect(fixture, projection_root))
    report["determinism"] = {"run1": first, "run2": second, "identical": first == second}
    report["gates"]["H2T-5_determinism"] = first == second
    report["gates"]["all_pass"] = all(report["gates"].values())
    add_timing(report, fixture, projection_root)
    return report


def render_markdown(report: dict[str, Any]) -> str:
    lines = ["# Two-tier retrieval v1", "",
             f"- fixture: {report['fixture']}",
             f"- thresholds: {json.dumps(report['thresholds'], sort_keys=True)}",
             f"- probes: {report['probes_used']} · required occurrences: "
             f"{report['required_occurrences']} · calls added: {report['calls_added']}",
             "",
             "| arm | availability | precision@k | delivered | found | mean chars | p50 ms | p95 ms |",
             "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for arm in ARMS:
        a = report["arms"][arm]
        lat = report["latency_ms"][arm]
        lines.append(f"| {arm} | {a['availability']:.3f} | {a['precision_at_k']:.3f} | "
                     f"{a['delivered']} | {a['found']} | {a['mean_chars']:.0f} | "
                     f"{lat['p50']:.3f} | {lat['p95']:.3f} |")
    lines += ["", f"gates: {json.dumps(report['gates'], sort_keys=True)}",
              f"determinism: {report['determinism']['identical']}", "",
              "## Per probe", "",
              "| probe | required | " + " | ".join(ARMS) + " |",
              "|---|---|" + "---|" * len(ARMS)]
    for entry in report["per_probe"]:
        cells = " | ".join(
            ",".join(entry[arm]["found"]) or "-" for arm in ARMS)
        lines.append(f"| {entry['probe_id']} | {','.join(entry['required'])} | {cells} |")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", default=str(DEFAULT_FIXTURE))
    parser.add_argument("--projection", default=str(DEFAULT_PROJECTION))
    parser.add_argument("--out", default=str(ROOT / "eval" / "results" / "two_tier_v1"))
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    report = run(Path(args.fixture), Path(args.projection))
    (out / "report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8")
    markdown = render_markdown(report)
    (out / "report.md").write_text(markdown, encoding="utf-8")
    print(markdown)
    return 0


if __name__ == "__main__":
    sys.exit(main())
