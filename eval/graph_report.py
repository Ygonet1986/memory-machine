"""Aggregate the graph-recall measurement snapshots (M2/M3).

Reads eval/graph_out/graph_bench_<dataset>.jsonl and emits:
  - eval/graph_out/summary_graph_<dataset>.json
  - eval/graph_out/tables_graph_<dataset>.csv
  - eval/graph_out/report_graph_<dataset>.md  (skeleton for docs/GRAPH_EVAL.md)

Deterministic: only reads the snapshots, never re-runs anything.
"""

from __future__ import annotations

import csv
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable

HERE = Path(__file__).resolve().parent
OUT = HERE / "graph_out"


def load(dataset: str) -> list[dict[str, Any]]:
    path = OUT / f"graph_bench_{dataset}.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def judged(rows: list[dict[str, Any]], arm: str) -> list[dict[str, Any]]:
    return [row for row in rows if row["arms"][arm]["verdict"]]


def strict(rows: list[dict[str, Any]], arm: str) -> float | None:
    items = judged(rows, arm)
    if not items:
        return None
    return round(sum(1 for row in items if row["arms"][arm]["verdict"] == "correct") / len(items), 4)


def lenient(rows: list[dict[str, Any]], arm: str) -> float | None:
    items = judged(rows, arm)
    if not items:
        return None
    return round(
        sum(1 for row in items if row["arms"][arm]["verdict"] in {"correct", "partial"}) / len(items),
        4,
    )


def aur(rows: list[dict[str, Any]], arm: str, evidence_key: str) -> float | None:
    items = [
        row
        for row in rows
        if row["arms"][arm]["verdict"] and row["retrieval"][evidence_key] == 1
    ]
    if not items:
        return None
    return round(sum(1 for row in items if row["arms"][arm]["verdict"] == "correct") / len(items), 4)


def mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 4) if values else None


def strata_table(
    rows: list[dict[str, Any]],
    key_fn: Callable[[dict[str, Any]], str],
    *,
    name: str,
) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[key_fn(row)].append(row)
    table = []
    for key in sorted(groups):
        items = groups[key]
        table.append(
            {
                "stratum": name,
                "value": key,
                "n": len(items),
                "agent_recall": mean([r["retrieval"]["agent_recall"] for r in items if r["retrieval"]["agent_recall"] is not None]),
                "graph_recall": mean([r["retrieval"]["graph_recall"] for r in items if r["retrieval"]["graph_recall"] is not None]),
                "union_recall": mean([r["retrieval"]["union_recall"] for r in items if r["retrieval"]["union_recall"] is not None]),
                "strict_off": strict(items, "graph_off"),
                "strict_augment": strict(items, "graph_augment"),
                "graph_only_gold": sum(len(r["retrieval"]["graph_only_gold"]) for r in items),
                "graph_only_count": sum(r["retrieval"]["graph_only_count"] for r in items),
                "agent_only_gold": sum(len(r["retrieval"]["agent_only_gold"]) for r in items),
            }
        )
    return table


def path_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    gold_evidence = 0
    depths: list[int] = []
    event_hops = 0
    confidences: list[float] = []
    for row in rows:
        required = set(row["required_ids"])
        for evidence in row["arms"]["graph_only"]["graph_evidence"]:
            if evidence["memory_id"] not in required:
                continue
            gold_evidence += 1
            if not evidence["paths"]:
                continue
            best = max(evidence["paths"], key=lambda path: path["score"])
            depths.append(best["semantic_depth"])
            confidences.append(best["score"])
            if len(best["relations"]) > best["semantic_depth"]:
                event_hops += 1
    return {
        "gold_graph_evidence": gold_evidence,
        "by_semantic_depth": {str(depth): depths.count(depth) for depth in sorted(set(depths))},
        "event_hop_share": round(event_hops / len(depths), 4) if depths else None,
        "mean_best_score": mean(confidences),
    }


def aggregate(dataset: str) -> dict[str, Any]:
    rows = load(dataset)
    if not rows:
        return {"dataset": dataset, "n": 0}
    categories = strata_table(rows, lambda r: r["cat"] or "(none)", name="category")
    multi = strata_table(rows, lambda r: "multi" if r["strata"]["multi_session"] else "single", name="sessions")
    seeds = strata_table(rows, lambda r: "seeds" if r["strata"]["graph_seeds"] else "no-seeds", name="seeds")
    buckets = strata_table(rows, lambda r: r["strata"]["lexical_bucket"] or "(n/a)", name="lexical")
    extraction_calls = sum(row["graph"]["extract_calls"] for row in rows)
    extraction_ms = sum(row["graph"]["build_ms"] for row in rows)
    reused = any(row["graph"].get("reused_fixture") for row in rows)
    fixture = rows[0]["graph"] if reused else {}
    totals = {
        "graph_only_gold": sum(len(row["retrieval"]["graph_only_gold"]) for row in rows),
        "agent_only_gold": sum(len(row["retrieval"]["agent_only_gold"]) for row in rows),
        "overlap_gold": sum(len(row["retrieval"]["overlap_gold"]) for row in rows),
        "graph_only_count": sum(row["retrieval"]["graph_only_count"] for row in rows),
        "graph_evidence_total": sum(len(row["arms"]["graph_only"]["graph_ids"]) for row in rows),
        "graph_evidence_complete": sum(row["retrieval"]["graph_evidence_complete"] for row in rows),
        "agent_evidence_complete": sum(row["retrieval"]["agent_evidence_complete"] for row in rows),
        "union_evidence_complete": sum(row["retrieval"]["union_evidence_complete"] for row in rows),
    }
    return {
        "dataset": dataset,
        "n": len(rows),
        "arms": {
            arm: {
                "strict": strict(rows, arm),
                "lenient": lenient(rows, arm),
                "aur": aur(
                    rows,
                    arm,
                    "agent_evidence_complete" if arm == "graph_off" else "union_evidence_complete",
                ),
                "mean_annotations": mean([len(r["arms"][arm]["annotations"]) for r in rows]),
            }
            for arm in ("graph_off", "graph_augment", "graph_only")
        },
        "retrieval": {
            "agent_recall": mean([r["retrieval"]["agent_recall"] for r in rows if r["retrieval"]["agent_recall"] is not None]),
            "graph_recall": mean([r["retrieval"]["graph_recall"] for r in rows if r["retrieval"]["graph_recall"] is not None]),
            "union_recall": mean([r["retrieval"]["union_recall"] for r in rows if r["retrieval"]["union_recall"] is not None]),
            "graph_precision": mean([r["retrieval"]["graph_precision"] for r in rows if r["retrieval"]["graph_precision"] is not None]),
        },
        "totals": totals,
        "paths": path_stats(rows),
        "cost": {
            "extraction_calls": extraction_calls if not reused else fixture.get("extract_calls"),
            "extraction_ms": extraction_ms if not reused else fixture.get("build_ms"),
            "reused_fixture": reused,
            "fixture": fixture or None,
            "graph_recall_ms_mean": mean([r["arms"]["graph_only"]["graph_metrics"].get("graph_recall_ms", 0.0) for r in rows]),
            "embed_calls_total": rows[-1]["cost"]["embed_calls_total"] if rows else None,
        },
        "review": {
            "hypotheses": sum(row["graph"]["hypotheses"] for row in rows) if not reused else fixture.get("hypotheses"),
            "open": sum(row["graph"]["open_hypotheses"] for row in rows) if not reused else fixture.get("open_hypotheses"),
            "rejected_pairs": sum(row["graph"]["rejected_pairs"] for row in rows) if not reused else fixture.get("rejected_pairs"),
        },
        "tables": {
            "category": categories,
            "sessions": multi,
            "seeds": seeds,
            "lexical": buckets,
        },
        "rows": rows,
    }


def fmt(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def markdown(summary: dict[str, Any]) -> str:
    rows = summary["rows"]
    lines = [
        f"# Graph recall — {summary['dataset']} (n={summary['n']})",
        "",
        "Generated by `eval/graph_report.py` from the immutable snapshots in",
        "`eval/graph_out/`. No experiment is re-executed here.",
        "",
        "## Arms",
        "",
        "| arm | strict | lenient | AUR | mean annotations |",
        "|---|---|---|---|---|",
    ]
    for arm, data in summary["arms"].items():
        lines.append(
            f"| {arm} | {fmt(data['strict'])} | {fmt(data['lenient'])} | {fmt(data['aur'])} "
            f"| {fmt(data['mean_annotations'])} |"
        )
    retrieval = summary["retrieval"]
    totals = summary["totals"]
    lines += [
        "",
        "## Retrieval",
        "",
        "| metric | value |",
        "|---|---|",
        f"| agent recall (mean) | {fmt(retrieval['agent_recall'])} |",
        f"| graph recall (mean) | {fmt(retrieval['graph_recall'])} |",
        f"| union recall (mean) | {fmt(retrieval['union_recall'])} |",
        f"| graph precision (mean) | {fmt(retrieval['graph_precision'])} |",
        f"| graph_only_gold (total) | {totals['graph_only_gold']} |",
        f"| agent_only_gold (total) | {totals['agent_only_gold']} |",
        f"| overlap_gold (total) | {totals['overlap_gold']} |",
        f"| graph_only_count (total) | {totals['graph_only_count']} |",
        f"| evidence complete off / graph / union | {totals['agent_evidence_complete']} / "
        f"{totals['graph_evidence_complete']} / {totals['union_evidence_complete']} |",
        "",
        "## Paths",
        "",
        f"- gold graph evidence: {summary['paths']['gold_graph_evidence']}",
        f"- by semantic depth: {summary['paths']['by_semantic_depth']}",
        f"- event-hop share: {fmt(summary['paths']['event_hop_share'])}",
        f"- mean best score: {fmt(summary['paths']['mean_best_score'])}",
        "",
        "## Cost",
        "",
        f"- extraction calls: {summary['cost']['extraction_calls']} "
        f"(fixture reused: {summary['cost']['reused_fixture']})",
        f"- extraction ms: {summary['cost']['extraction_ms']}",
        f"- graph recall ms (mean): {fmt(summary['cost']['graph_recall_ms_mean'])}",
        f"- embedding calls: {summary['cost']['embed_calls_total']}",
        "",
        "## Review",
        "",
        f"- hypotheses: {summary['review']['hypotheses']} "
        f"(open {summary['review']['open']}, rejected pairs {summary['review']['rejected_pairs']})",
        "",
    ]
    for name, table in summary["tables"].items():
        lines += [
            f"## By {name}",
            "",
            "| value | n | agent recall | graph recall | union recall | strict off | strict aug | graph_only_gold | agent_only_gold |",
            "|---|---|---|---|---|---|---|---|---|",
        ]
        for item in table:
            lines.append(
                f"| {item['value']} | {item['n']} | {fmt(item['agent_recall'])} | "
                f"{fmt(item['graph_recall'])} | {fmt(item['union_recall'])} | "
                f"{fmt(item['strict_off'])} | {fmt(item['strict_augment'])} | "
                f"{item['graph_only_gold']} | {item['agent_only_gold']} |"
            )
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    datasets = sys.argv[1:] or ["synthetic", "longmemeval"]
    for dataset in datasets:
        summary = aggregate(dataset)
        if not summary.get("n"):
            print(f"{dataset}: no snapshots")
            continue
        (OUT / f"summary_graph_{dataset}.json").write_text(
            json.dumps({k: v for k, v in summary.items() if k != "rows"}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        with (OUT / f"tables_graph_{dataset}.csv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(
                ["stratum", "value", "n", "agent_recall", "graph_recall", "union_recall",
                 "strict_off", "strict_augment", "graph_only_gold", "agent_only_gold"]
            )
            for table in summary["tables"].values():
                for item in table:
                    writer.writerow([
                        item["stratum"], item["value"], item["n"], item["agent_recall"],
                        item["graph_recall"], item["union_recall"], item["strict_off"],
                        item["strict_augment"], item["graph_only_gold"], item["agent_only_gold"],
                    ])
        (OUT / f"report_graph_{dataset}.md").write_text(markdown(summary), encoding="utf-8")
        print(f"{dataset}: wrote summary/tables/report (n={summary['n']})")


if __name__ == "__main__":
    main()
