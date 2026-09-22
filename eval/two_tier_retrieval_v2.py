#!/usr/bin/env python3
"""Two-tier retrieval v2 — bounded candidacy over the unconditional index.

Frozen by docs/TWO_TIER_RETRIEVAL_V2_PREREG.md. Primary T2v2-P: rank-1 +
score >= 0.90 x best over the combined non-rejected index. Variants B2
(exact top-2) and M70 (margin 0.70); references U90 (unfiltered) and A90
(promoted). Deterministic; timing informational.

    PYTHONPATH=src:.:eval python3 eval/two_tier_retrieval_v2.py
"""

from __future__ import annotations

import argparse
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

import lifecycle_shadow as shadow  # noqa: E402
import two_tier_retrieval_v1 as v1  # noqa: E402
from lifecycle_retroactive import SEARCHABLE_CLASS, TOP_K, rank  # noqa: E402

MARGIN_PRIMARY = 0.90
MARGIN_VARIANT = 0.70
WARMUP = 10
REPS = 100
ARMS = ("T2v2-P", "T2v2-B2", "T2v2-M70", "T2v2-U90", "T2v2-A90")
DEFAULT_FIXTURE = v1.DEFAULT_FIXTURE
DEFAULT_PROJECTION = v1.DEFAULT_PROJECTION
V1_REPORT = ROOT / "eval" / "results" / "two_tier_v1" / "report.json"


def bounded(candidates: list[dict[str, Any]], margin: float | None = None,
            budget: int | None = None) -> list[str]:
    if not candidates:
        return []
    if budget is not None:
        return [c["memory_id"] for c in candidates[:budget]]
    assert margin is not None
    best = candidates[0]["score"]
    return [c["memory_id"] for c in candidates
            if c["score"] >= margin * best]


def collect(fixture: Path, projection_root: Path) -> dict[str, Any]:
    records, _gold, probes = shadow.load_fixture(fixture)
    decisions = {d.memory_id: d for d in
                 (lc.Decision.from_dict(row) for row in
                  lc.LifecycleProjection(projection_root).load_decisions())}
    seq_by_id = {row["memory_id"]: row["seq"] for row in records}

    counters = {arm: {"delivered": 0, "found": 0, "chars": 0} for arm in ARMS}
    sensitivity: dict[str, dict[str, dict[str, int]]] = {
        "margin": {f"{m:.2f}": {"delivered": 0, "found": 0}
                   for m in (0.50, 0.70, 0.90, 1.00)},
        "budget": {str(b): {"delivered": 0, "found": 0} for b in (1, 2, 3)},
    }
    occurrences_total = 0
    per_probe: list[dict[str, Any]] = []

    for probe in probes:
        if probe.get("unrecoverable"):
            continue
        required = [mid for mid in probe["required_ids"] if mid in seq_by_id]
        occurrences_total += len(required)
        cutoff = [row for row in records
                  if seq_by_id[row["memory_id"]] < probe["after_seq"]]
        active_items = [row for row in cutoff
                        if decisions[row["memory_id"]].promoted]
        union_items = [row for row in cutoff
                       if decisions[row["memory_id"]].promoted
                       or decisions[row["memory_id"]].target_class == SEARCHABLE_CLASS]
        q = probe["question"]
        delivered = {
            "T2v2-P": bounded(rank(q, union_items), margin=MARGIN_PRIMARY),
            "T2v2-B2": bounded(rank(q, union_items), budget=2),
            "T2v2-M70": bounded(rank(q, union_items), margin=MARGIN_VARIANT),
            "T2v2-U90": bounded(rank(q, cutoff), margin=MARGIN_PRIMARY),
            "T2v2-A90": bounded(rank(q, active_items), margin=MARGIN_PRIMARY),
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
            entry[arm] = {"delivered": mids, "found": found, "chars": chars}
        for margin_key in sensitivity["margin"]:
            mids = bounded(rank(q, union_items), margin=float(margin_key))
            sensitivity["margin"][margin_key]["delivered"] += len(mids)
            sensitivity["margin"][margin_key]["found"] += sum(
                1 for mid in mids if mid in required)
        for budget_key in sensitivity["budget"]:
            mids = bounded(rank(q, union_items), budget=int(budget_key))
            sensitivity["budget"][budget_key]["delivered"] += len(mids)
            sensitivity["budget"][budget_key]["found"] += sum(
                1 for mid in mids if mid in required)
        per_probe.append(entry)

    assert len(per_probe) == 19 and occurrences_total == 21
    probes_used = len(per_probe)

    report: dict[str, Any] = {
        "prereg": "docs/TWO_TIER_RETRIEVAL_V2_PREREG.md",
        "fixture": str(fixture),
        "projection": str(projection_root),
        "thresholds": {"top_k": TOP_K, "margin_primary": MARGIN_PRIMARY,
                       "margin_variant": MARGIN_VARIANT},
        "probes_used": probes_used,
        "required_occurrences": occurrences_total,
        "calls_added": 0,
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

    report["sensitivity"] = {
        group: {
            key: [round(data["found"] / occurrences_total, 4),
                  round(data["found"] / data["delivered"], 4)
                  if data["delivered"] else 0.0]
            for key, data in values.items()}
        for group, values in sensitivity.items()}

    primary = report["arms"]["T2v2-P"]
    u90 = report["arms"]["T2v2-U90"]
    a90 = report["arms"]["T2v2-A90"]
    report["gates"] = {
        "H6-1_availability": primary["availability"] >= 0.952,
        "H6-2_precision": primary["precision_at_k"] >= 0.80,
        "H6-3_budget": primary["mean_chars"] <= 1.25 * a90["mean_chars"],
        "H6-4_no_regression_vs_unfiltered": primary["precision_at_k"]
        >= u90["precision_at_k"] - 0.05,
    }
    v1_report = json.loads(V1_REPORT.read_text(encoding="utf-8"))
    report["v1_reference"] = {
        "T2-B_availability": v1_report["arms"]["T2-B"]["availability"],
        "T2-B_precision": v1_report["arms"]["T2-B"]["precision_at_k"],
        "T2-C_precision": v1_report["arms"]["T2-C"]["precision_at_k"],
    }
    return report


def run(fixture: Path, projection_root: Path) -> dict[str, Any]:
    report = collect(fixture, projection_root)
    first = v1.content_digest(report)
    second = v1.content_digest(collect(fixture, projection_root))
    report["determinism"] = {"run1": first, "run2": second,
                             "identical": first == second}
    report["gates"]["H6-5_determinism"] = first == second
    report["gates"]["all_pass"] = all(report["gates"].values())
    add_timing(report, fixture, projection_root)
    return report


def add_timing(report: dict[str, Any], fixture: Path,
               projection_root: Path) -> None:
    records, _gold, probes = shadow.load_fixture(fixture)
    decisions = {d.memory_id: d for d in
                 (lc.Decision.from_dict(row) for row in
                  lc.LifecycleProjection(projection_root).load_decisions())}
    seq_by_id = {row["memory_id"]: row["seq"] for row in records}

    def callable_for(arm: str, question: str, active_items, union_items,
                     cutoff) -> Callable[[], Any]:
        if arm == "T2v2-A90":
            return lambda: bounded(rank(question, active_items),
                                   margin=MARGIN_PRIMARY)
        if arm == "T2v2-U90":
            return lambda: bounded(rank(question, cutoff),
                                   margin=MARGIN_PRIMARY)
        if arm == "T2v2-B2":
            return lambda: bounded(rank(question, union_items), budget=2)
        if arm == "T2v2-M70":
            return lambda: bounded(rank(question, union_items),
                                   margin=MARGIN_VARIANT)
        return lambda: bounded(rank(question, union_items),
                               margin=MARGIN_PRIMARY)

    samples: dict[str, list[float]] = {arm: [] for arm in ARMS}
    for probe in probes:
        if probe.get("unrecoverable"):
            continue
        cutoff = [row for row in records
                  if seq_by_id[row["memory_id"]] < probe["after_seq"]]
        active_items = [row for row in cutoff
                        if decisions[row["memory_id"]].promoted]
        union_items = [row for row in cutoff
                       if decisions[row["memory_id"]].promoted
                       or decisions[row["memory_id"]].target_class == SEARCHABLE_CLASS]
        for arm in ARMS:
            call = callable_for(arm, probe["question"], active_items,
                                union_items, cutoff)
            for _ in range(WARMUP):
                call()
            for _ in range(REPS):
                start = time.perf_counter()
                call()
                samples[arm].append((time.perf_counter() - start) * 1000.0)
    report["latency_ms"] = {
        arm: {"p50": round(v1.percentile(samples[arm], 0.50), 3),
              "p95": round(v1.percentile(samples[arm], 0.95), 3),
              "samples": len(samples[arm])}
        for arm in ARMS}


def render_markdown(report: dict[str, Any]) -> str:
    lines = ["# Two-tier retrieval v2 — bounded candidacy", "",
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
              "## Sensitivity (combined index; descriptive, not gating)", "",
              "| margin | availability | precision@k |",
              "|---|---:|---:|"]
    for margin_value, (avail, precision) in report["sensitivity"]["margin"].items():
        lines.append(f"| {margin_value} | {avail:.3f} | {precision:.3f} |")
    lines += ["", "| budget | availability | precision@k |", "|---|---:|---:|"]
    for budget_value, (avail, precision) in report["sensitivity"]["budget"].items():
        lines.append(f"| top-{budget_value} | {avail:.3f} | {precision:.3f} |")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", default=str(DEFAULT_FIXTURE))
    parser.add_argument("--projection", default=str(DEFAULT_PROJECTION))
    parser.add_argument("--out", default=str(ROOT / "eval" / "results" / "two_tier_v2"))
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
