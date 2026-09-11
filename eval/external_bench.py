"""External benchmarks: LongMemEval and LoCoMo.

Converts each benchmark's sessions into tape memories and measures whether the
evidence session is surfaced by each arm:

  bm25          — deterministic BM25 over all memories (no LLM)
  agents_full   — every memory agent consulted
  agents_router — semantic router selects top-K partitions, then agents

Metric: evidence recall (the answer session's memory surfaced). Also reports
LLM calls/query. Subsample with --limit to keep cost bounded.
"""

from __future__ import annotations

import argparse
import json
import random
import shutil
import time
from pathlib import Path
from typing import Any

from memory_machine.config import Config
from memory_machine.coordinator import Machine
from memory_machine.llm import LLMClient
from memory_machine.retrieval import Embedder, rank, rank_semantic
from memory_machine.tape import MemoryRecord

DATA = Path(__file__).resolve().parent / "data"


class CountingClient:
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


def _turns_text(turns: list[dict[str, Any]]) -> str:
    parts = []
    for t in turns:
        role = t.get("role") or t.get("speaker") or "?"
        content = t.get("content") or t.get("text") or ""
        parts.append(f"{role}: {content}")
    return "\n".join(parts)


def load_longmemeval(path: Path, limit: int, seed: int) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    rng = random.Random(seed)
    sample = data if limit <= 0 else rng.sample(data, min(limit, len(data)))
    out = []
    for item in sample:
        sessions = [
            {"id": sid, "text": _turns_text(sess)}
            for sid, sess in zip(item["haystack_session_ids"], item["haystack_sessions"])
        ]
        out.append(
            {
                "question": item["question"],
                "expected": set(item.get("answer_session_ids") or []),
                "sessions": sessions,
                "type": item.get("question_type", ""),
            }
        )
    return out


def load_locomo(path: Path, limit: int, seed: int) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    rng = random.Random(seed)
    out = []
    for sample in data:
        conv = sample["conversation"]
        sessions = []
        for key, value in conv.items():
            if key.startswith("session_") and isinstance(value, list):
                sessions.append({"id": key, "text": _turns_text(value)})
        # evidence "D1:3" -> session "session_1"
        qas = sample.get("qa") or []
        for qa in qas:
            expected = set()
            for ev in qa.get("evidence") or []:
                if ":" in ev:
                    expected.add("session_" + ev.split(":", 1)[0].lstrip("Dd"))
            out.append(
                {
                    "question": qa.get("question", ""),
                    "expected": expected,
                    "sessions": sessions,
                    "type": str(qa.get("category", "")),
                }
            )
    if limit > 0:
        out = rng.sample(out, min(limit, len(out)))
    return out


def build_machine(root: Path, sessions: list[dict[str, Any]], cfg: Config) -> tuple[Machine, dict[str, str]]:
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    m = Machine(root, config=cfg)
    id_map: dict[str, str] = {}
    for s in sessions:
        rec = MemoryRecord(
            type="memory",
            summary=s["text"][:300] or s["id"],
            why=s["text"][:2000],
            source=s["id"],
        )
        res = m.add_memory(rec, save=False)
        id_map[s["id"]] = res["record"]["id"]
    m.save()
    return m, id_map


def arm_bm25(m: Machine, question: str, expected_ids: set[str], k: int) -> tuple[bool, int]:
    records = m.tape.read()
    docs = [r.text() for r in records]
    ids = [r.id for r in records]
    top = {ids[i] for i, _s in rank(question, docs, limit=k)}
    return bool(top & expected_ids), 0


def arm_vector(
    m: Machine, question: str, expected_ids: set[str], embedder: Embedder, k: int
) -> tuple[bool, int]:
    records = m.tape.read()
    docs = [r.text() for r in records]
    ids = [r.id for r in records]
    top = {ids[i] for i, _s in rank_semantic(question, docs, embedder, limit=k)}
    return bool(top & expected_ids), 0


def arm_agents(
    m: Machine, question: str, expected_ids: set[str], client: CountingClient
) -> tuple[bool, int]:
    m.client = client
    m.whiteboard.annotations = []
    m._invalidate_recall_cache()
    before = client.calls
    res = m.recall(question)
    calls = client.calls - before
    hit = any(a["memory_id"] in expected_ids for a in res.get("annotations", []))
    return hit, calls


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dataset", choices=["longmemeval", "locomo"], default="longmemeval")
    p.add_argument("--path", default="")
    p.add_argument("--limit", type=int, default=12, help="0 = all questions")
    p.add_argument("--capacity", type=int, default=5)
    p.add_argument("--top-k", type=int, default=3)
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--model", default="deepseek-v4-flash")
    p.add_argument("--api-key", default="")
    p.add_argument(
        "--arms",
        default="bm25,vector,agents_full,agents_router",
        help="comma-separated: bm25, vector, agents_full, agents_router",
    )
    p.add_argument(
        "--embedding-models",
        default="nomic-embed-text",
        help="comma-separated Ollama embedding models (one vector arm each)",
    )
    p.add_argument("--embedding-base-url", default="http://localhost:11434/v1")
    p.add_argument("--no-checklist", action="store_true", help="ablation: agents skip the checklist")
    p.add_argument("--keep", action="store_true", help="keep the temp memory dir")
    args = p.parse_args()

    import os

    selected = {a.strip() for a in args.arms.split(",") if a.strip()}
    needs_llm = bool(selected & {"agents_full", "agents_router"})
    api_key = args.api_key or os.environ.get("DEEPSEEK_API_KEY", "")
    if needs_llm and not api_key:
        raise SystemExit("set DEEPSEEK_API_KEY (or --api-key)")

    if args.path:
        path = Path(args.path).expanduser()
    elif args.dataset == "longmemeval":
        path = DATA / "longmemeval_s_cleaned.json"
    else:
        path = DATA / "locomo10.json"

    if args.dataset == "longmemeval":
        tasks = load_longmemeval(path, args.limit, args.seed)
    else:
        tasks = load_locomo(path, args.limit, args.seed)

    root = Path("/tmp/mm-external-bench")
    base = CountingClient(
        LLMClient("https://api.deepseek.com", api_key, args.model, retries=1, backoff=0.5)
    )
    embedders = [
        (m.strip(), Embedder(args.embedding_base_url, "", m.strip()))
        for m in args.embedding_models.split(",")
        if m.strip() and "vector" in selected
    ]

    arms: dict[str, list[float]] = {}
    lat: dict[str, float] = {}
    if "bm25" in selected:
        arms["bm25"] = [0, 0]
    for name, _emb in embedders:
        arms[f"vector:{name}"] = [0, 0]
    for a in ("agents_full", "agents_router"):
        if a in selected:
            arms[a] = [0, 0]
            lat[a] = 0.0

    for i, t in enumerate(tasks):
        expected = {sid for sid in t["expected"]}
        if not expected:
            continue

        m, id_map = build_machine(
            root, t["sessions"], Config(capacity=args.capacity, router_enabled=False)
        )
        expected_ids = {id_map[s] for s in expected if s in id_map}
        if not expected_ids:
            continue

        if "bm25" in selected:
            hit, calls = arm_bm25(m, t["question"], expected_ids, k=5)
            arms["bm25"][0] += int(hit)
            arms["bm25"][1] += calls
        for name, emb in embedders:
            hit, calls = arm_vector(m, t["question"], expected_ids, emb, k=5)
            arms[f"vector:{name}"][0] += int(hit)
            arms[f"vector:{name}"][1] += calls

        if "agents_full" in selected:
            start = time.monotonic()
            hit, calls = arm_agents(m, t["question"], expected_ids, base)
            lat["agents_full"] += time.monotonic() - start
            arms["agents_full"][0] += int(hit)
            arms["agents_full"][1] += calls

        if "agents_router" in selected:
            m2, id_map2 = build_machine(
                root,
                t["sessions"],
                Config(
                    capacity=args.capacity,
                    router_enabled=True,
                    router_mode="llm",
                    router_top_k=args.top_k,
                    ablation_no_checklist=args.no_checklist,
                ),
            )
            expected_ids2 = {id_map2[s] for s in expected if s in id_map2}
            if expected_ids2:
                start = time.monotonic()
                hit, calls = arm_agents(m2, t["question"], expected_ids2, base)
                lat["agents_router"] += time.monotonic() - start
                arms["agents_router"][0] += int(hit)
                arms["agents_router"][1] += calls

        if i % 25 == 0 or i == len(tasks) - 1:
            print(f"  [{i + 1}/{len(tasks)}] done", flush=True)

    n = max(len(tasks), 1)
    print(
        f"\ndataset: {args.dataset} | questions: {len(tasks)} | "
        f"capacity: {args.capacity} | arms: {','.join(arms)}\n"
    )
    print(f"{'arm':<28} {'evidence recall':>15} {'calls/query':>12} {'latency(s)':>11}")
    for name, (hits, calls) in arms.items():
        latency = lat.get(name, 0.0) / n
        print(f"{name:<28} {hits / n:>15.2f} {calls / n:>12.1f} {latency:>11.2f}")

    if not args.keep and root.exists():
        shutil.rmtree(root)


if __name__ == "__main__":
    main()
