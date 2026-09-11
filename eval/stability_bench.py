"""Attention stability benchmark: is the routing selection reproducible?

Protocol per task and repetition (fresh machine each time):
  turn 1  the question (establishes attention for the prior arm)
  turn 2  the same question again, with the recall cache invalidated (measured)

Arms:
  view_llm         LLM dimension plan (the unstable baseline)
  view_bm25        deterministic lexical plan
  view_bm25_prior  lexical plan + attention prior from turn 1

Metrics per task: modal selection rate and mean pairwise Jaccard of the turn-2
selected views across repetitions, plus evidence recall and the attention
contribution (router only / attention only / both).

Run:  PYTHONPATH=src python3 eval/stability_bench.py
"""

from __future__ import annotations

import argparse
import itertools
import shutil
import tempfile
from pathlib import Path
from typing import Any

from memory_machine.config import Config
from memory_machine.llm import LLMClient

from view_router_bench import CountingClient, TASKS, build_machine

FOCUS = [13, 17, 19, 20, 23, 24, 27, 31]  # cross-view, adversarial, relational, temporal

ARMS: dict[str, dict[str, Any]] = {
    "view_llm": dict(view_router_mode="llm"),
    "view_bm25": dict(view_router_mode="lexical"),
    "view_bm25_prior": dict(view_router_mode="lexical", attention_mode="prior"),
}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b)


def run_repetition(
    cfg: Config,
    root: Path,
    task: dict[str, Any],
    id_map: dict[str, str],
    client: CountingClient,
) -> dict[str, Any]:
    machine, _ = build_machine(root, cfg, client)
    machine._invalidate_recall_cache()
    machine.recall(task["q"], debug=True)  # turn 1: establishes attention
    machine._invalidate_recall_cache()
    before = client.calls
    res = machine.recall(task["q"], debug=True)  # turn 2: measured
    calls = client.calls - before
    routing = res.get("routing") or {}
    selected = set(routing.get("selected_views") or [])
    consulted = set(routing.get("consulted_ids") or [])
    required = {id_map[k] for k in task["required"]}
    return {
        "selected": selected,
        "complete_evidence": int(required <= consulted),
        "calls": calls,
        "contribution": res.get("attention_contribution") or {},
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--model", default="deepseek-v4-flash")
    p.add_argument("--api-key", default="")
    p.add_argument("--repeats", type=int, default=5)
    p.add_argument("--arms", default="view_llm,view_bm25,view_bm25_prior")
    p.add_argument("--keep", action="store_true")
    args = p.parse_args()

    import os

    api_key = args.api_key or os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key:
        raise SystemExit("set DEEPSEEK_API_KEY (or --api-key)")

    base = CountingClient(
        LLMClient("https://api.deepseek.com", api_key, args.model, retries=1, backoff=0.5)
    )
    root = Path(tempfile.mkdtemp(prefix="mm-stability-"))
    fixture_cfg = Config(capacity=5)
    _machine, id_map = build_machine(root / "_fixture", fixture_cfg)
    selected_arms = [a.strip() for a in args.arms.split(",") if a.strip()]

    print(f"tasks: {FOCUS} | repeats: {args.repeats}\n")
    print(f"{'arm':<16} {'task':>4} {'modal':>6} {'jaccard':>8} {'ecomp':>6} {'calls':>6} "
          f"{'router':>6} {'attn':>5} {'both':>5}")
    for arm in selected_arms:
        cfg = Config(
            capacity=5,
            router_enabled=True,
            router_mode="views",
            view_dimension_mode="auto",
            agent_mode="view",
            view_top_k=3,
            **ARMS[arm],
        )
        for index in FOCUS:
            task = TASKS[index]
            selections: list[set[str]] = []
            ecomp: list[int] = []
            calls: list[float] = []
            contributions: list[dict[str, int]] = []
            for rep in range(args.repeats):
                row = run_repetition(
                    cfg, root / f"{arm}_{index}_{rep}", task, id_map, base
                )
                selections.append(row["selected"])
                ecomp.append(row["complete_evidence"])
                calls.append(row["calls"])
                contributions.append(row["contribution"])
            modal = max(selections.count(s) for s in selections) / len(selections)
            pair = list(itertools.combinations(selections, 2))
            mean_jac = sum(jaccard(a, b) for a, b in pair) / len(pair) if pair else 1.0
            contrib = {
                key: sum(c.get(key, 0) for c in contributions) for key in ("router", "attention", "both")
            }
            print(
                f"{arm:<16} {index:>4} {modal:>6.2f} {mean_jac:>8.2f} "
                f"{sum(ecomp)/len(ecomp):>6.2f} {sum(calls)/len(calls):>6.1f} "
                f"{contrib['router']:>6} {contrib['attention']:>5} {contrib['both']:>5}"
            )

    if not args.keep:
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    main()
