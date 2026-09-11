"""Generate the paper figures from the frozen snapshots (eval-only dependency).

Matplotlib is used only here; the Memory Machine core remains stdlib-only.
Each figure is saved as PDF + SVG plus its source CSV under docs/figures/.

Run:  .venv/bin/python eval/figures.py
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
FIGS = HERE.parent / "docs" / "figures"


def load(name: str) -> list[dict[str, Any]]:
    path = OUT / name
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def strict(rows: list[dict[str, Any]]) -> float:
    return sum(1 for r in rows if r["judge"]["verdict"] == "correct") / len(rows) if rows else 0.0


def aur(rows: list[dict[str, Any]]) -> float:
    complete = [r for r in rows if r["evidence_complete"] == 1]
    return strict(complete) if complete else 0.0


def chars(rows: list[dict[str, Any]]) -> float:
    vals = [max(r.get("context_chars", 0), r.get("payload_chars", 0)) for r in rows]
    return sum(vals) / len(vals) if vals else 0.0


def gfr(rows: list[dict[str, Any]]) -> float:
    vals = [r["gfr"] for r in rows if r.get("gfr") is not None]
    return sum(vals) / len(vals) if vals else 0.0


def save(fig: Any, name: str, header: list[str], data: list[list[Any]]) -> None:
    FIGS.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIGS / f"{name}.pdf", bbox_inches="tight")
    fig.savefig(FIGS / f"{name}.svg", bbox_inches="tight")
    plt.close(fig)
    with (FIGS / f"{name}.csv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(header)
        writer.writerows(data)
    print(f"wrote docs/figures/{name}.pdf/.svg/.csv")


def fig_compression() -> None:
    runs = [
        ("full", "e2e_agents_view_ctx_longmemeval_ing0.jsonl"),
        ("6000", "e2e_agents_view_payload_longmemeval_ing0_pb6000.jsonl"),
        ("4000", "e2e_agents_view_payload_longmemeval_ing0_pb4000.jsonl"),
        ("2500", "e2e_agents_view_payload_longmemeval_ing0_pb2500.jsonl"),
    ]
    data = []
    for label, f in runs:
        rows = load(f)
        if rows:
            data.append([label, round(chars(rows)), round(strict(rows), 3), round(aur(rows), 3)])
    if not data:
        return
    fig, ax = plt.subplots(figsize=(5.2, 3.4))
    xs = [d[1] for d in data]
    ax.plot(xs, [d[2] for d in data], "o-", label="strict accuracy")
    ax.plot(xs, [d[3] for d in data], "s--", label="AUR (correct | evidence complete)")
    for d in data:
        ax.annotate(d[0], (d[1], d[2]), textcoords="offset points", xytext=(0, 7), ha="center", fontsize=8)
    ax.set_xlabel("context characters")
    ax.set_ylabel("accuracy (LongMemEval, n=50)")
    ax.set_ylim(0.4, 1.0)
    ax.grid(alpha=0.3)
    ax.legend(fontsize=8)
    save(fig, "fig_compression",
         ["arm", "chars", "strict", "aur"], data)


def fig_synthetic_arms() -> None:
    arms = [
        ("no_memory", "e2e_no_memory.jsonl"),
        ("bm25", "e2e_bm25.jsonl"),
        ("agents_group", "e2e_agents_group.jsonl"),
        ("agents_view", "e2e_agents_view.jsonl"),
        ("agents_view_ctx", "e2e_agents_view_ctx.jsonl"),
        ("agents_view_payload", "e2e_agents_view_payload.jsonl"),
        ("gold-evidence", "e2e_oracle.jsonl"),
    ]
    data = []
    for label, f in arms:
        rows = load(f)
        if rows:
            data.append([label, round(strict(rows), 3), round(aur(rows), 3)])
    if not data:
        return
    fig, ax = plt.subplots(figsize=(6.4, 3.4))
    idx = range(len(data))
    ax.bar([i - 0.2 for i in idx], [d[1] for d in data], width=0.4, label="strict")
    ax.bar([i + 0.2 for i in idx], [d[2] for d in data], width=0.4, label="AUR")
    ax.set_xticks(list(idx))
    ax.set_xticklabels([d[0] for d in data], rotation=25, ha="right", fontsize=8)
    ax.set_ylabel("accuracy (synthetic, n=32)")
    ax.set_ylim(0, 1.05)
    ax.grid(axis="y", alpha=0.3)
    ax.legend(fontsize=8)
    save(fig, "fig_synthetic_arms", ["arm", "strict", "aur"], data)


def fig_ingestion() -> None:
    runs = [
        ("2000", "e2e_agents_view_payload_longmemeval.jsonl"),
        ("4000", "e2e_agents_view_payload_longmemeval_ing4000.jsonl"),
        ("8000", "e2e_agents_view_payload_longmemeval_ing8000.jsonl"),
        ("full", "e2e_agents_view_payload_longmemeval_ing0.jsonl"),
    ]
    data = []
    for label, f in runs:
        rows = load(f)
        if rows:
            data.append([label, round(gfr(rows), 3), round(strict(rows), 3)])
    if not data:
        return
    fig, ax = plt.subplots(figsize=(5.2, 3.4))
    xs = range(len(data))
    ax.plot(xs, [d[1] for d in data], "o-", label="Gold Fact Retention")
    ax.plot(xs, [d[2] for d in data], "s--", label="strict accuracy")
    ax.set_xticks(list(xs))
    ax.set_xticklabels([d[0] for d in data])
    ax.set_xlabel("session characters stored at ingestion")
    ax.set_ylabel("rate (LongMemEval, n=12)")
    ax.set_ylim(0, 1.0)
    ax.grid(alpha=0.3)
    ax.legend(fontsize=8)
    save(fig, "fig_ingestion", ["ingest_chars", "gfr", "strict"], data)


def fig_temporal() -> None:
    runs = [
        ("payload base", "e2e_agents_view_payload_longmemeval_ing0_pb4000.jsonl"),
        ("+ real dates", "e2e_agents_view_payload_dates_longmemeval_ing0_pb4000.jsonl"),
        ("+ temporal prompt", "e2e_agents_view_payload_dates_temporal_longmemeval_ing0_pb4000.jsonl"),
    ]
    data = []
    for label, f in runs:
        rows = [r for r in load(f) if r["cat"] == "temporal-reasoning"]
        if rows:
            complete = [r for r in rows if r["evidence_complete"] == 1]
            data.append([label, len(rows), round(strict(rows), 3), round(strict(complete), 3)])
    if not data:
        return
    fig, ax = plt.subplots(figsize=(5.6, 3.4))
    idx = range(len(data))
    ax.bar([i - 0.2 for i in idx], [d[2] for d in data], width=0.4, label="temporal (all)")
    ax.bar([i + 0.2 for i in idx], [d[3] for d in data], width=0.4, label="temporal | evidence complete")
    ax.set_xticks(list(idx))
    ax.set_xticklabels([d[0] for d in data], fontsize=8)
    ax.set_ylabel("strict accuracy (n=14 / 9)")
    ax.set_ylim(0, 1.05)
    ax.grid(axis="y", alpha=0.3)
    ax.legend(fontsize=8)
    save(fig, "fig_temporal", ["arm", "n_temporal", "temporal_all", "temporal_evidence_complete"], data)


def main() -> None:
    fig_compression()
    fig_synthetic_arms()
    fig_ingestion()
    fig_temporal()


if __name__ == "__main__":
    main()
