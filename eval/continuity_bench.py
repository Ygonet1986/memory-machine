"""Multi-turn continuity benchmark: does persisted view state help later turns?

Runs short scenarios (3 turns) on the *same* machine and compares two arms:

  persistent — view agents keep their digests/checklists and the dimension
               boards keep their annotations across turns
  reset      — the same state is cleared before every turn (stateless)

Metrics per turn: complete evidence, agent recall, calls; plus state growth
(view-agent checklists, dimension board annotations). Evidence recall is the
primary measure; the state numbers show what continuity accumulates.

Run:  PYTHONPATH=src python3 eval/continuity_bench.py
"""

from __future__ import annotations

import argparse
import shutil
import tempfile
from pathlib import Path
from typing import Any

from memory_machine.config import Config
from memory_machine.coordinator import Machine
from memory_machine.llm import LLMClient
from memory_machine.views import build_index

from view_router_bench import CountingClient, build_machine

SCENARIOS: list[dict[str, Any]] = [
    {
        "name": "router evolution",
        "turns": [
            {"q": "why was the embedding router disabled?", "required": ["router_embed"]},
            {"q": "what did the benchmarks show after that?",
             "required": ["bench_locomo", "bench_judge"]},
            {"q": "what should we remember about the router now?",
             "required": ["router_llm", "router_digest"]},
        ],
    },
    {
        "name": "views design",
        "turns": [
            {"q": "how are views stored relative to the tape?", "required": ["views_foundation"]},
            {"q": "what are the rules for expansion?", "required": ["views_expand"]},
            {"q": "what did we do about views in September?",
             "required": ["views_index", "views_foundation"]},
        ],
    },
    {
        "name": "temporal composition",
        "turns": [
            {"q": "what changed about the router since July?",
             "required": ["router_digest", "adv_dual"]},
            {"q": "what did the answer-accuracy judge find?", "required": ["bench_judge"]},
            {"q": "what changed between the first router decision and the recent benchmark?",
             "required": ["router_llm", "bench_judge"]},
        ],
    },
]


def state_metrics(machine: Machine) -> dict[str, Any]:
    checklists = sum(len(a.checklist) for a in machine.manifest.view_agents.values())
    digests = sum(1 for a in machine.manifest.view_agents.values() if a.digest)
    board_annotations = sum(len(b.annotations) for b in machine.whiteboard.boards.values())
    board_chars = sum(len(b.render()) for b in machine.whiteboard.boards.values())
    return {
        "view_agents": len(machine.manifest.view_agents),
        "digests": digests,
        "checklist_chars": checklists,
        "board_annotations": board_annotations,
        "board_chars": board_chars,
    }


def reset_state(machine: Machine) -> None:
    machine.manifest.view_agents.clear()
    machine.whiteboard.boards.clear()
    machine.whiteboard.annotations = []
    machine._invalidate_recall_cache()


def run_scenario(
    arm: str,
    scenario: dict[str, Any],
    cfg: Config,
    root: Path,
    client: CountingClient,
    id_map: dict[str, str],
) -> list[dict[str, Any]]:
    machine, _ = build_machine(root, cfg, client)
    rows: list[dict[str, Any]] = []
    for turn, spec in enumerate(scenario["turns"], start=1):
        if arm == "reset":
            reset_state(machine)
        machine._invalidate_recall_cache()
        before = client.calls
        res = machine.recall(spec["q"], debug=True)
        calls = client.calls - before
        required = {id_map[k] for k in spec["required"]}
        consulted = set((res.get("routing") or {}).get("consulted_ids") or [])
        annotated = {a["memory_id"] for a in res.get("annotations") or []}
        rows.append(
            {
                "arm": arm,
                "scenario": scenario["name"],
                "turn": turn,
                "q": spec["q"],
                "complete_evidence": int(required <= consulted),
                "agent_recall": len(annotated & required) / len(required),
                "calls": calls,
                **state_metrics(machine),
            }
        )
    return rows


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--model", default="deepseek-v4-flash")
    p.add_argument("--api-key", default="")
    p.add_argument("--keep", action="store_true")
    args = p.parse_args()

    import os

    api_key = args.api_key or os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key:
        raise SystemExit("set DEEPSEEK_API_KEY (or --api-key)")

    base = CountingClient(
        LLMClient("https://api.deepseek.com", api_key, args.model, retries=1, backoff=0.5)
    )
    root = Path(tempfile.mkdtemp(prefix="mm-continuity-"))
    cfg = Config(
        capacity=5,
        router_enabled=True,
        router_mode="views",
        view_router_mode="lexical",
        view_dimension_mode="auto",
        agent_mode="view",
        whiteboard_mode="dimension",
        view_top_k=3,
    )
    _machine, id_map = build_machine(root / "_fixture", cfg)

    all_rows: list[dict[str, Any]] = []
    for arm in ("persistent", "reset"):
        for scenario in SCENARIOS:
            print(f"running {arm} / {scenario['name']} ...", flush=True)
            rows = run_scenario(
                arm, scenario, cfg, root / f"{arm}_{scenario['name'].replace(' ', '_')}",
                base, id_map,
            )
            all_rows.extend(rows)

    print(f"\n{'arm':<11} {'scenario':<20} {'turn':>4} {'ecomp':>6} {'arec':>6} "
          f"{'calls':>6} {'agents':>6} {'chk_chars':>9} {'board_ann':>9}")
    for r in all_rows:
        print(
            f"{r['arm']:<11} {r['scenario']:<20} {r['turn']:>4} {r['complete_evidence']:>6} "
            f"{r['agent_recall']:>6.2f} {r['calls']:>6.1f} {r['view_agents']:>6} "
            f"{r['checklist_chars']:>9} {r['board_annotations']:>9}"
        )

    print("\naggregate:")
    for arm in ("persistent", "reset"):
        rows = [r for r in all_rows if r["arm"] == arm]
        n = len(rows)
        print(
            f"  {arm:<11} ecomp={sum(r['complete_evidence'] for r in rows)/n:.2f} "
            f"arec={sum(r['agent_recall'] for r in rows)/n:.2f} "
            f"calls={sum(r['calls'] for r in rows)/n:.1f} "
            f"final_chk_chars={rows[-1]['checklist_chars']} "
            f"final_board_ann={rows[-1]['board_annotations']}"
        )

    if not args.keep:
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    main()
