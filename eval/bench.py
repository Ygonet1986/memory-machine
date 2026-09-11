"""Benchmark: naive full-tape context vs deterministic recall vs memory agents.

Measures, per task with a known ground-truth memory:
  - recall: whether the correct memory reaches the main chatbot's context;
  - main_context_tokens: the size of the context injected into the main chatbot
    (token proxy = chars / 4);
  - for the agents arm: total parallel input tokens and wall-clock latency.
"""

from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path
from typing import Any

from memory_machine.agents import agent_system_prompt, agent_user_prompt, run_agents
from memory_machine.config import Config
from memory_machine.coordinator import Machine
from memory_machine.groups import group_records
from memory_machine.llm import LLMClient, LLMError
from memory_machine.tape import Tape
from memory_machine.whiteboard import Whiteboard, merge_annotations

TOKEN_PROXY = 4
STOPWORDS = {
    "the", "and", "for", "are", "was", "what", "did", "we", "about", "using",
    "with", "that", "our", "this", "you", "how", "why", "module", "revisiting",
}


def tokens(text: str) -> int:
    return len(text) // TOKEN_PROXY


def _kw(text: str) -> list[str]:
    toks = re.findall(r"[a-z0-9]+", text.lower())
    return [t for t in toks if len(t) > 2 and t not in STOPWORDS]


def naive(tape: Tape, task: str, expected: str) -> dict[str, Any]:
    records = tape.read()
    full = "\n".join(r.text() for r in records)
    return {"recall": 1.0, "main_context_tokens": tokens(full)}


def deterministic(tape: Tape, task: str, expected: str, k: int = 10) -> dict[str, Any]:
    kws = _kw(task)
    scored: list[tuple[Any, int]] = []
    for r in tape.read():
        blob = (r.summary + " " + r.why).lower()
        score = sum(1 for t in kws if t in blob)
        if score:
            scored.append((r, score))
    scored.sort(key=lambda x: -x[1])
    top = [r for r, _ in scored[:k]]
    context = "\n".join(r.text() for r in top)
    recall = 1.0 if any(r.id == expected for r in top) else 0.0
    return {"recall": recall, "main_context_tokens": tokens(context)}


def agents(machine: Machine, client: Any, task: str, expected: str) -> dict[str, Any]:
    wb = Whiteboard(subject=task[:120])
    start = time.monotonic()
    anns = run_agents(machine.tape, machine.manifest, wb, client).annotations
    latency = time.monotonic() - start

    merge_annotations(wb, anns, budget=machine.config.whiteboard_budget)
    context = wb.render()
    recall = 1.0 if any(a.memory_id == expected for a in wb.annotations) else 0.0

    # Total parallel input tokens across all agents (informational).
    total_input = 0
    for agent in machine.manifest.agents:
        group = next((g for g in machine.manifest.groups if g.id == agent.group_id), None)
        if group is None:
            continue
        records = group_records(machine.tape, group)
        sp = agent_system_prompt(agent, group, records)
        up = agent_user_prompt(wb)
        total_input += tokens(sp + up)

    return {
        "recall": recall,
        "main_context_tokens": tokens(context),
        "agent_input_tokens": total_input,
        "num_agents": len(machine.manifest.agents),
        "latency_s": round(latency, 2),
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("root", help="fixture project root (from gen_fixture.py)")
    p.add_argument("--k", type=int, default=10, help="top-k for deterministic recall")
    p.add_argument("--limit", type=int, default=0, help="cap number of tasks (0 = all)")
    args = p.parse_args()

    root = Path(args.root).expanduser().resolve()
    machine = Machine(root)
    tasks = json.loads((root / "tasks.json").read_text(encoding="utf-8"))

    try:
        client = LLMClient.from_config(machine.config)
    except LLMError as e:
        print(f"error: {e}", "set DEEPSEEK_API_KEY to run the agents arm")
        client = None

    arms = ["naive", "deterministic", "agents"]
    results: dict[str, dict[str, list[float]]] = {a: {"recall": [], "tokens": []} for a in arms}
    agent_latencies: list[float] = []
    if args.limit:
        tasks = tasks[: args.limit]

    for t in tasks:
        task, expected = t["task"], t["expected"]
        results["naive"]["recall"].append(1.0)
        results["naive"]["tokens"].append(naive(machine.tape, task, expected)["main_context_tokens"])

        det = deterministic(machine.tape, task, expected, k=args.k)
        results["deterministic"]["recall"].append(det["recall"])
        results["deterministic"]["tokens"].append(det["main_context_tokens"])

        if client is not None:
            ag = agents(machine, client, task, expected)
            results["agents"]["recall"].append(ag["recall"])
            results["agents"]["tokens"].append(ag["main_context_tokens"])
            agent_latencies.append(ag["latency_s"])
        print(f"  [{expected}] task done")

    print(f"tasks: {len(tasks)}  |  tape: {len(machine.tape)} records  |  "
          f"agents: {len(machine.manifest.agents)}  |  token proxy: chars/{TOKEN_PROXY}\n")

    def avg(xs: list[float]) -> float:
        return round(sum(xs) / len(xs), 2) if xs else 0.0

    print(f"{'arm':<14} {'recall':>8} {'main-ctx tokens':>16}")
    for arm in arms:
        r = results[arm]
        print(f"{arm:<14} {avg(r['recall']):>8.2f} {avg(r['tokens']):>16.0f}")

    if agent_latencies:
        print(f"\nagents: avg latency {avg(agent_latencies)}s/turn "
              f"(parallel round over {len(machine.manifest.agents)} agents)")


if __name__ == "__main__":
    main()
