"""Figures for the graph-recall measurement (M3).

Reads the summaries produced by eval/graph_report.py and writes PDF/SVG plus
the source CSV under docs/figures/. Matplotlib is confined to eval/.

Run:  .venv/bin/python eval/graph_figures.py
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

import graph_report  # noqa: E402

FIGS = HERE.parent / "docs" / "figures"


def _bars(ax: Any, table: list[dict[str, Any]], title: str) -> None:
    values = [item["value"] for item in table]
    positions = range(len(values))
    width = 0.27
    ax.bar([i - width for i in positions], [item["agent_recall"] or 0 for item in table],
           width=width, label="agents (off)")
    ax.bar(list(positions), [item["graph_recall"] or 0 for item in table],
           width=width, label="graph (only)")
    ax.bar([i + width for i in positions], [item["union_recall"] or 0 for item in table],
           width=width, label="union (augment)")
    ax.set_xticks(list(positions))
    ax.set_xticklabels(values, rotation=20, ha="right", fontsize=8)
    ax.set_ylim(0, 1.05)
    ax.set_ylabel("gold evidence recall")
    ax.set_title(title, fontsize=10)
    ax.grid(axis="y", alpha=0.3)
    ax.legend(fontsize=8)


def _novelty(ax: Any, table: list[dict[str, Any]], title: str) -> None:
    values = [item["value"] for item in table]
    positions = range(len(values))
    width = 0.38
    ax.bar([i - width / 2 for i in positions],
           [item["graph_only_gold"] for item in table], width=width,
           label="graph-only gold")
    ax.bar([i + width / 2 for i in positions],
           [item["agent_only_gold"] for item in table], width=width,
           label="agent-only gold")
    ax.set_xticks(list(positions))
    ax.set_xticklabels(values, rotation=20, ha="right", fontsize=8)
    ax.set_ylabel("gold memories (count)")
    ax.set_title(title, fontsize=10)
    ax.grid(axis="y", alpha=0.3)
    ax.legend(fontsize=8)


def make(dataset: str) -> None:
    summary = graph_report.aggregate(dataset)
    if not summary.get("n"):
        print(f"{dataset}: no snapshots")
        return
    tables = summary["tables"]
    panels = [("category", tables["category"])]
    if dataset == "longmemeval":
        panels.append(("lexical overlap", tables["lexical"]))

    fig, axes = plt.subplots(2, len(panels), figsize=(5.2 * len(panels), 6.4), squeeze=False)
    for column, (name, table) in enumerate(panels):
        _bars(axes[0][column], table, f"Recall by {name} ({dataset})")
        _novelty(axes[1][column], table, f"Novel gold by {name} ({dataset})")
    fig.tight_layout()
    FIGS.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIGS / f"graph_recall_{dataset}.pdf", bbox_inches="tight")
    fig.savefig(FIGS / f"graph_recall_{dataset}.svg", bbox_inches="tight")
    plt.close(fig)

    with (FIGS / f"graph_recall_{dataset}.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow([
            "stratum", "value", "n", "agent_recall", "graph_recall", "union_recall",
            "strict_off", "strict_augment", "aug_better", "aug_worse", "aug_equal",
            "graph_only_gold", "agent_only_gold",
        ])
        for name, table in panels:
            for item in table:
                writer.writerow([
                    name, item["value"], item["n"], item["agent_recall"], item["graph_recall"],
                    item["union_recall"], item["strict_off"], item["strict_augment"],
                    item["aug_better"], item["aug_worse"], item["aug_equal"],
                    item["graph_only_gold"], item["agent_only_gold"],
                ])
    print(f"{dataset}: wrote docs/figures/graph_recall_{dataset}.pdf/.svg/.csv")


def main() -> None:
    for dataset in ("synthetic", "longmemeval"):
        make(dataset)


if __name__ == "__main__":
    main()
