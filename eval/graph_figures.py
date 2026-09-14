"""Figures for the graph-recall measurement (M3/V2).

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


def _strict_by_arm(ax: Any, summary: dict[str, Any], dataset: str) -> None:
    arms = summary["arms"]
    values = [summary["results"][arm]["strict"] or 0 for arm in arms]
    positions = range(len(arms))
    ax.bar(positions, values, width=0.55, color=["#6b7280", "#8b5cf6", "#10b981", "#f59e0b", "#94a3b8"][: len(arms)])
    ax.set_xticks(list(positions))
    ax.set_xticklabels([arm.replace("graph_", "") for arm in arms], rotation=20, ha="right", fontsize=8)
    ax.set_ylim(0, 1.05)
    ax.set_ylabel("strict accuracy (judged)")
    ax.set_title(f"Answer accuracy by arm ({dataset})", fontsize=10)
    ax.grid(axis="y", alpha=0.3)


def _novelty(ax: Any, summary: dict[str, Any], dataset: str) -> None:
    label_arms = ["agent_only"] + summary["augment_arms"]
    values = [summary["retrieval"]["graph_off"]["agent_only_gold"]]
    values += [summary["retrieval"][arm]["graph_only_gold"] for arm in summary["augment_arms"]]
    positions = range(len(label_arms))
    ax.bar(positions, values, width=0.55, color=["#94a3b8", "#8b5cf6", "#10b981", "#f59e0b"][: len(label_arms)])
    ax.set_xticks(list(positions))
    ax.set_xticklabels([name.replace("graph_augment", "aug").replace("_", " ") for name in label_arms],
                       rotation=20, ha="right", fontsize=8)
    ax.set_ylabel("gold memories (count)")
    ax.set_title(f"Gold found only by one arm ({dataset})", fontsize=10)
    ax.grid(axis="y", alpha=0.3)


def make(dataset: str) -> None:
    summary = graph_report.aggregate(dataset)
    if not summary.get("n"):
        print(f"{dataset}: no snapshots")
        return
    fig, axes = plt.subplots(1, 2, figsize=(10.4, 3.8))
    _strict_by_arm(axes[0], summary, dataset)
    _novelty(axes[1], summary, dataset)
    fig.tight_layout()
    FIGS.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIGS / f"graph_recall_{dataset}.pdf", bbox_inches="tight")
    fig.savefig(FIGS / f"graph_recall_{dataset}.svg", bbox_inches="tight")
    plt.close(fig)

    with (FIGS / f"graph_recall_{dataset}.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["arm", "strict", "lenient", "aur", "graph_only_gold", "graph_precision", "evidence_complete"])
        for arm in summary["arms"]:
            data = summary["results"][arm]
            retrieval = summary["retrieval"][arm]
            writer.writerow([
                arm, data["strict"], data["lenient"], data["aur"],
                retrieval["graph_only_gold"], retrieval["graph_precision"],
                retrieval["evidence_complete"],
            ])
    print(f"{dataset}: wrote docs/figures/graph_recall_{dataset}.pdf/.svg/.csv")


def main() -> None:
    for dataset in ("synthetic", "longmemeval"):
        make(dataset)


if __name__ == "__main__":
    main()
