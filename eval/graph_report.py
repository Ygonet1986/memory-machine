"""Aggregate the graph-recall measurement snapshots (M2/M3/V2).

Reads eval/graph_out/graph_bench_<dataset>.jsonl and emits:
  - eval/graph_out/summary_graph_<dataset>.json
  - eval/graph_out/tables_graph_<dataset>.csv
  - eval/graph_out/report_graph_<dataset>.md

Deterministic: only reads snapshots, never re-runs anything. Arms are
discovered from the snapshot, so the v1 three-arm run and the v2 five-arm
replay share the same analyzer.
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

VERDICT_RANK = {"incorrect": 0, "partial": 1, "correct": 2}


def load(dataset: str) -> list[dict[str, Any]]:
    path = OUT / f"graph_bench_{dataset}.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def arms_of(rows: list[dict[str, Any]]) -> list[str]:
    if not rows:
        return []
    return list(rows[0]["arms"].keys())


def augment_arms(arms: list[str]) -> list[str]:
    return [arm for arm in arms if arm not in {"graph_off", "graph_only"}]


def retrieval_for(row: dict[str, Any], arm: str) -> dict[str, Any]:
    by_arm = row.get("retrieval_by_arm") or {}
    if arm in by_arm:
        return by_arm[arm]
    return row["retrieval"]


def strict(rows: list[dict[str, Any]], arm: str) -> float | None:
    items = [row for row in rows if row["arms"][arm]["verdict"]]
    if not items:
        return None
    return round(sum(1 for row in items if row["arms"][arm]["verdict"] == "correct") / len(items), 4)


def lenient(rows: list[dict[str, Any]], arm: str) -> float | None:
    items = [row for row in rows if row["arms"][arm]["verdict"]]
    if not items:
        return None
    return round(
        sum(1 for row in items if row["arms"][arm]["verdict"] in {"correct", "partial"}) / len(items),
        4,
    )


def aur(rows: list[dict[str, Any]], arm: str) -> float | None:
    key = "graph_evidence_complete" if arm == "graph_only" else "union_evidence_complete"
    if arm == "graph_off":
        key = "agent_evidence_complete"
    items = [
        row
        for row in rows
        if row["arms"][arm]["verdict"] and retrieval_for(row, arm)[key] == 1
    ]
    if not items:
        return None
    return round(sum(1 for row in items if row["arms"][arm]["verdict"] == "correct") / len(items), 4)


def mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 4) if values else None


def paired(items: list[dict[str, Any]], arm: str) -> tuple[int, int, int]:
    better = worse = equal = 0
    for row in items:
        off = row["arms"]["graph_off"]["verdict"]
        other = row["arms"][arm]["verdict"]
        if not off or not other:
            continue
        delta = VERDICT_RANK[other] - VERDICT_RANK[off]
        better += int(delta > 0)
        worse += int(delta < 0)
        equal += int(delta == 0)
    return better, worse, equal


def strata_table(
    rows: list[dict[str, Any]],
    arm_names: list[str],
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
        entry: dict[str, Any] = {
            "stratum": name,
            "value": key,
            "n": len(items),
            "agent_recall": mean(
                [r["retrieval"]["agent_recall"] for r in items if r["retrieval"]["agent_recall"] is not None]
            ),
            "graph_recall": mean(
                [r["retrieval"]["graph_recall"] for r in items if r["retrieval"]["graph_recall"] is not None]
            ),
            "union_recall": mean(
                [r["retrieval"]["union_recall"] for r in items if r["retrieval"]["union_recall"] is not None]
            ),
            "graph_only_gold": sum(len(r["retrieval"]["graph_only_gold"]) for r in items),
            "agent_only_gold": sum(len(r["retrieval"]["agent_only_gold"]) for r in items),
        }
        for arm in arm_names:
            entry[f"strict_{arm}"] = strict(items, arm)
            if arm != "graph_off":
                better, worse, equal = paired(items, arm)
                entry[f"delta_{arm}"] = (better, worse, equal)
                entry[f"gog_{arm}"] = sum(
                    len(retrieval_for(r, arm)["graph_only_gold"]) for r in items
                )
        table.append(entry)
    return table


def path_stats(rows: list[dict[str, Any]], arm: str = "graph_only") -> dict[str, Any]:
    gold_evidence = 0
    depths: list[int] = []
    event_hops = 0
    confidences: list[float] = []
    for row in rows:
        required = set(row["required_ids"])
        for evidence in row["arms"][arm]["graph_evidence"]:
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
    arms = arms_of(rows)
    aug = augment_arms(arms)
    categories = strata_table(rows, arms, lambda r: r["cat"] or "(none)", name="category")
    multi = strata_table(rows, arms, lambda r: "multi" if r["strata"]["multi_session"] else "single", name="sessions")
    seeds = strata_table(rows, arms, lambda r: "seeds" if r["strata"]["graph_seeds"] else "no-seeds", name="seeds")
    buckets = strata_table(rows, arms, lambda r: r["strata"]["lexical_bucket"] or "(n/a)", name="lexical")
    reused = any(row["graph"].get("reused_fixture") for row in rows)
    fixture = rows[0]["graph"] if reused else {}
    extraction_calls = sum(row["graph"]["extract_calls"] for row in rows)
    extraction_ms = sum(row["graph"]["build_ms"] for row in rows)
    return {
        "dataset": dataset,
        "n": len(rows),
        "arms": arms,
        "augment_arms": aug,
        "results": {
            arm: {
                "strict": strict(rows, arm),
                "lenient": lenient(rows, arm),
                "aur": aur(rows, arm),
                "mean_annotations": mean([len(r["arms"][arm]["annotations"]) for r in rows]),
            }
            for arm in arms
        },
        "paired_vs_off": {arm: dict(zip(("better", "worse", "equal"), paired(rows, arm))) for arm in aug},
        "retrieval": {
            arm: {
                "agent_recall": mean(
                    [r["retrieval"]["agent_recall"] for r in rows if r["retrieval"]["agent_recall"] is not None]
                ),
                "graph_recall": mean(
                    [
                        retrieval_for(r, arm)["graph_recall"]
                        for r in rows
                        if retrieval_for(r, arm)["graph_recall"] is not None
                    ]
                ),
                "union_recall": mean(
                    [
                        retrieval_for(r, arm)["union_recall"]
                        for r in rows
                        if retrieval_for(r, arm)["union_recall"] is not None
                    ]
                ),
                "graph_precision": mean(
                    [
                        retrieval_for(r, arm)["graph_precision"]
                        for r in rows
                        if retrieval_for(r, arm)["graph_precision"] is not None
                    ]
                ),
                "graph_only_gold": sum(len(retrieval_for(r, arm)["graph_only_gold"]) for r in rows),
                "agent_only_gold": sum(len(r["retrieval"]["agent_only_gold"]) for r in rows),
                "graph_only_count": sum(r["retrieval"]["graph_only_count"] for r in rows),
                "evidence_complete": sum(retrieval_for(r, arm)["union_evidence_complete"] for r in rows),
            }
            for arm in arms
        },
        "paths": {arm: path_stats(rows, arm) for arm in arms if arm != "graph_off"},
        "cost": {
            "extraction_calls": extraction_calls if not reused else fixture.get("extract_calls"),
            "extraction_ms": extraction_ms if not reused else fixture.get("build_ms"),
            "reused_fixture": reused,
            "graph_recall_ms_mean": mean(
                [r["arms"]["graph_only"]["graph_metrics"].get("graph_recall_ms", 0.0) for r in rows]
            ),
            "embed_calls_total": rows[-1]["cost"]["embed_calls_total"] if rows else None,
        },
        "review": {
            "hypotheses": sum(row["graph"]["hypotheses"] for row in rows) if not reused else fixture.get("hypotheses"),
            "open": sum(row["graph"]["open_hypotheses"] for row in rows) if not reused else fixture.get("open_hypotheses"),
            "rejected_pairs": sum(row["graph"]["rejected_pairs"] for row in rows) if not reused else fixture.get("rejected_pairs"),
        },
        "tables": {"category": categories, "sessions": multi, "seeds": seeds, "lexical": buckets},
        "rows": rows,
    }


def fmt(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def markdown(summary: dict[str, Any]) -> str:
    arms = summary["arms"]
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
    for arm in arms:
        data = summary["results"][arm]
        lines.append(
            f"| {arm} | {fmt(data['strict'])} | {fmt(data['lenient'])} | {fmt(data['aur'])} "
            f"| {fmt(data['mean_annotations'])} |"
        )
    for arm, delta in summary["paired_vs_off"].items():
        lines.append(
            f"| paired {arm} vs off (better/worse/equal) | {delta['better']} / {delta['worse']} / {delta['equal']} |"
            " | | |"
        )
    lines += ["", "## Retrieval", "", "| arm | agent recall | graph recall | union recall | graph precision | graph_only_gold | graph_only_count | evidence complete |", "|---|---|---|---|---|---|---|---|"]
    for arm in arms:
        data = summary["retrieval"][arm]
        lines.append(
            f"| {arm} | {fmt(data['agent_recall'])} | {fmt(data['graph_recall'])} | {fmt(data['union_recall'])} "
            f"| {fmt(data['graph_precision'])} | {data['graph_only_gold']} | {data['graph_only_count']} | {data['evidence_complete']} |"
        )
    lines += ["", "## Paths", ""]
    for arm, data in summary["paths"].items():
        lines.append(
            f"- {arm}: gold evidence {data['gold_graph_evidence']}, depths {data['by_semantic_depth']}, "
            f"event-hop share {fmt(data['event_hop_share'])}, mean best {fmt(data['mean_best_score'])}"
        )
    lines += [
        "",
        "## Cost",
        "",
        f"- extraction calls: {summary['cost']['extraction_calls']} (fixture reused: {summary['cost']['reused_fixture']})",
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
        header = ["value", "n", "agent recall", "graph recall", "union recall"]
        for arm in arms:
            header.append(f"strict {arm.replace('graph_', '')}")
        for arm in summary["augment_arms"]:
            header.append(f"{arm.replace('graph_augment', 'aug')} +/=/−")
        header += ["graph_only_gold", "agent_only_gold"]
        lines += [f"## By {name}", "", "| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
        for item in table:
            row = [
                item["value"], str(item["n"]), fmt(item["agent_recall"]),
                fmt(item["graph_recall"]), fmt(item["union_recall"]),
            ]
            for arm in arms:
                row.append(fmt(item.get(f"strict_{arm}")))
            for arm in summary["augment_arms"]:
                delta = item.get(f"delta_{arm}")
                row.append(f"{delta[0]}/{delta[1]}/{delta[2]}" if delta else "-")
            row += [str(item["graph_only_gold"]), str(item["agent_only_gold"])]
            lines.append("| " + " | ".join(row) + " |")
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
                ["stratum", "value", "n", "agent_recall", "graph_recall", "union_recall"]
                + [f"strict_{arm}" for arm in summary["arms"]]
                + [f"delta_{arm}" for arm in summary["augment_arms"]]
                + ["graph_only_gold", "agent_only_gold"]
            )
            for table in summary["tables"].values():
                for item in table:
                    writer.writerow(
                        [item["stratum"], item["value"], item["n"], item["agent_recall"],
                         item["graph_recall"], item["union_recall"]]
                        + [item.get(f"strict_{arm}") for arm in summary["arms"]]
                        + [str(item.get(f"delta_{arm}")) for arm in summary["augment_arms"]]
                        + [item["graph_only_gold"], item["agent_only_gold"]]
                    )
        (OUT / f"report_graph_{dataset}.md").write_text(markdown(summary), encoding="utf-8")
        print(f"{dataset}: wrote summary/tables/report (n={summary['n']}, arms={summary['arms']})")


if __name__ == "__main__":
    main()
