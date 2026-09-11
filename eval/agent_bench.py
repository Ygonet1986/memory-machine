"""Agentic memory benchmark: do memory agents surface memories that BM25 misses?

Builds a synthetic tape of topics where each task is *lexically distant* from
its ground-truth memory (different words, same meaning). Compares:

  bm25          — deterministic BM25 retrieval over all memories (no LLM)
  agents_full   — every memory agent consulted (no router)
  agents_router — memory router selects top-K partitions, then agents

Metrics per arm: recall (ground-truth memory surfaced), LLM calls/query, and
latency. `--scale` repeats the topic set to grow the number of partitions.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from memory_machine.config import Config
from memory_machine.coordinator import Machine
from memory_machine.llm import LLMClient
from memory_machine.retrieval import rank
from memory_machine.tape import MemoryRecord

# Each topic: a target memory and a lexically-distant task pointing at it.
TOPICS = [
    {
        "name": "database",
        "target": "Use PostgreSQL for the primary datastore",
        "task": "which RDBMS should hold user accounts?",
    },
    {
        "name": "auth",
        "target": "Use Argon2id to hash passwords",
        "task": "how should we protect user credentials at rest?",
    },
    {
        "name": "cache",
        "target": "Use Redis for session caching",
        "task": "where should we keep short-lived session state?",
    },
    {
        "name": "deploy",
        "target": "Deploy behind Nginx with Gunicorn workers",
        "task": "what is our production web serving setup?",
    },
    {
        "name": "messaging",
        "target": "Use Kafka for event streaming",
        "task": "how do services publish asynchronous events?",
    },
    {
        "name": "search",
        "target": "Use Elasticsearch for full-text search",
        "task": "which engine powers our text queries?",
    },
]

FILLER = [
    "Rename the {t} module for clarity",
    "Add tests for the {t} parser",
    "Refactor the {t} config loader",
    "Document the {t} deployment notes",
    "Bump the {t} dependency version",
]


class CountingClient:
    """Wraps an LLM client and counts calls."""

    def __init__(self, inner):
        self.inner = inner
        self.calls = 0

    def complete(self, messages, *, temperature=0.0):
        self.calls += 1
        return self.inner.complete(messages, temperature=temperature)

    def complete_with_reasoning(self, messages, *, temperature=0.0):
        self.calls += 1
        return self.inner.complete_with_reasoning(messages, temperature=temperature)

    def stream(self, messages, *, temperature=0.0):
        self.calls += 1
        return self.inner.stream(messages, temperature=temperature)


def build_project(root: Path, *, filler: int, capacity: int, scale: int) -> tuple[Machine, list[dict]]:
    root.mkdir(parents=True, exist_ok=True)
    cfg = Config(capacity=capacity, router_top_k=2)
    cfg.save(root / "config.json")
    machine = Machine(root, config=cfg)

    tasks: list[dict] = []
    for rep in range(scale):
        for t in TOPICS:
            machine.add_memory(
                MemoryRecord(
                    type="decision",
                    summary=f"{t['target']} [{t['name']}{rep}]",
                )
            )
            target_id = machine.tape.read()[-1].id
            tasks.append({"task": t["task"], "expected": target_id, "topic": t["name"]})
            for i in range(filler):
                machine.add_memory(
                    MemoryRecord(
                        type="lesson",
                        summary=FILLER[i % len(FILLER)].format(t=f"{t['name']}{rep}_{i}"),
                    )
                )
    return machine, tasks


def run_bm25(machine: Machine, tasks: list[dict], *, k: int) -> dict:
    hits = 0
    for t in tasks:
        docs = [r.text() for r in machine.tape.read()]
        ids = [r.id for r in machine.tape.read()]
        top = [ids[i] for i, _s in rank(t["task"], docs, limit=k)]
        if t["expected"] in top:
            hits += 1
    return {"recall": hits / len(tasks), "calls": 0.0, "latency": 0.0}


def run_agents(machine: Machine, tasks: list[dict], *, model: str, api_key: str) -> dict:
    client = CountingClient(
        LLMClient("https://api.deepseek.com", api_key, model, retries=1, backoff=0.5)
    )
    machine.client = client
    hits = 0
    total_calls = 0
    total_latency = 0.0
    for t in tasks:
        # Fresh whiteboard annotations + no cache, so recall is per-task.
        machine.whiteboard.annotations = []
        machine._invalidate_recall_cache()
        before = client.calls
        start = time.monotonic()
        res = machine.recall(t["task"])
        total_latency += time.monotonic() - start
        total_calls += client.calls - before
        if any(a["memory_id"] == t["expected"] for a in res.get("annotations", [])):
            hits += 1
    n = len(tasks)
    return {
        "recall": hits / n,
        "calls": total_calls / n,
        "latency": total_latency / n,
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", default="/tmp/mm-agent-bench")
    p.add_argument("--filler", type=int, default=3)
    p.add_argument("--capacity", type=int, default=4)
    p.add_argument("--scale", type=int, default=1)
    p.add_argument("--model", default="deepseek-v4-flash")
    p.add_argument("--api-key", default="")
    p.add_argument("--router-mode", default="lexical", choices=["lexical", "llm", "embedding"])
    p.add_argument("--top-k", type=int, default=2)
    p.add_argument("--embedding-model", default="")
    p.add_argument("--embedding-base-url", default="")
    args = p.parse_args()

    import os

    api_key = args.api_key or os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key:
        raise SystemExit("set DEEPSEEK_API_KEY (or --api-key)")

    root = Path(args.root).expanduser().resolve()
    machine, tasks = build_project(
        root, filler=args.filler, capacity=args.capacity, scale=args.scale
    )

    # Full agents: router disabled.
    full_cfg = Config(capacity=args.capacity, router_enabled=False)
    full = Machine(root, config=full_cfg)
    # Router arm: enabled with the chosen mode, top_k=2.
    router = Machine(
        root,
        config=Config(
            capacity=args.capacity,
            router_enabled=True,
            router_mode=args.router_mode,
            router_top_k=args.top_k,
            embedding_model=args.embedding_model,
            embedding_base_url=args.embedding_base_url,
        ),
    )

    print(
        f"memories: {len(machine.tape)} | groups: {len(machine.manifest.groups)} "
        f"| tasks: {len(tasks)} | capacity: {args.capacity}\n"
    )

    arms = {
        "bm25": run_bm25(machine, tasks, k=5),
        "agents_full": run_agents(full, tasks, model=args.model, api_key=api_key),
        "agents_router": run_agents(router, tasks, model=args.model, api_key=api_key),
    }

    print(f"{'arm':<16} {'recall':>8} {'calls/query':>12} {'latency(s)':>11}")
    for name, m in arms.items():
        print(f"{name:<16} {m['recall']:>8.2f} {m['calls']:>12.1f} {m['latency']:>11.2f}")


if __name__ == "__main__":
    main()
