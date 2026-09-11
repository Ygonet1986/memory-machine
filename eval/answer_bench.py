"""End-to-end answer accuracy with an LLM judge.

For each question and each retrieval arm, the pipeline is:

    retrieve context -> answerer LLM -> judge LLM (correct vs reference)

Arms:
  bm25          — top-k BM25 memories as context
  vector        — top-k dense (embedding) memories as context
  agents        — the memories annotated by the memory agents

Metrics: answer accuracy and LLM calls/query (retrieval + answer + judge).
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from external_bench import (  # noqa: E402
    CountingClient,
    DATA,
    build_machine,
    load_locomo,
    load_longmemeval,
)
from memory_machine.config import Config  # noqa: E402
from memory_machine.llm import LLMClient, extract_json_object  # noqa: E402
from memory_machine.retrieval import Embedder, rank, rank_semantic  # noqa: E402

ANSWER_SYSTEM = """You answer a question about a long-running project or \
conversation using ONLY the context provided. Be concise. If the context does \
not contain the answer, reply exactly: I don't know."""

JUDGE_SYSTEM = """You grade an answer against a reference. Reply with ONLY a \
JSON object: {"correct": true} if the candidate is semantically equivalent to \
the reference (or both say the answer is unknown), otherwise {"correct": false}."""


def context_from_ids(machine, ids: list[str], *, budget: int = 6000) -> str:
    by_id = {r.id: r for r in machine.tape.read()}
    blocks: list[str] = []
    used = 0
    for mid in ids:
        r = by_id.get(mid)
        if r is None:
            continue
        block = f"[{r.id}] {r.summary}\n{r.why}"
        if blocks and used + len(block) > budget:
            break
        blocks.append(block)
        used += len(block)
    return "\n\n".join(blocks)


def answer(client: CountingClient, question: str, context: str) -> str:
    messages = [
        {"role": "system", "content": ANSWER_SYSTEM},
        {"role": "user", "content": f"Context:\n{context or '(empty)'}\n\nQuestion: {question}"},
    ]
    return client.complete(messages, temperature=0.0).strip()


def judge(client: CountingClient, question: str, reference: str, candidate: str) -> bool:
    messages = [
        {"role": "system", "content": JUDGE_SYSTEM},
        {
            "role": "user",
            "content": (
                f"Question: {question}\nReference answer: {reference}\n"
                f"Candidate answer: {candidate}"
            ),
        },
    ]
    content = client.complete(messages, temperature=0.0)
    return bool(extract_json_object(content).get("correct") is True)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dataset", choices=["longmemeval", "locomo"], default="longmemeval")
    p.add_argument("--path", default="")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--capacity", type=int, default=5)
    p.add_argument("--top-k", type=int, default=5)
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--model", default="deepseek-v4-flash")
    p.add_argument("--api-key", default="")
    p.add_argument("--embedding-model", default="nomic-embed-text")
    p.add_argument("--embedding-base-url", default="http://localhost:11434/v1")
    p.add_argument("--arms", default="bm25,vector,agents")
    args = p.parse_args()

    api_key = args.api_key or os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key:
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
    # keep the reference answer
    if args.dataset == "longmemeval":
        import json

        raw = json.loads(path.read_text(encoding="utf-8"))
        by_q = {item["question"]: item.get("answer", "") for item in raw}
        for t in tasks:
            t["reference"] = by_q.get(t["question"], "")
    else:
        import json

        raw = json.loads(path.read_text(encoding="utf-8"))
        by_q = {}
        for sample in raw:
            for qa in sample.get("qa") or []:
                by_q[qa.get("question", "")] = qa.get("answer", "")
        for t in tasks:
            t["reference"] = by_q.get(t["question"], "")

    selected = {a.strip() for a in args.arms.split(",") if a.strip()}
    root = Path("/tmp/mm-answer-bench")
    client = CountingClient(
        LLMClient("https://api.deepseek.com", api_key, args.model, retries=1, backoff=0.5)
    )
    embedder = Embedder(args.embedding_base_url, "", args.embedding_model)

    stats: dict[str, list[float]] = {a: [0, 0, 0.0] for a in selected}  # hits, calls, latency

    for i, t in enumerate(tasks):
        reference = t.get("reference", "")
        if not reference:
            continue
        machine, _id_map = build_machine(
            root, t["sessions"], Config(capacity=args.capacity, router_enabled=False)
        )
        records = machine.tape.read()
        docs = [r.text() for r in records]
        ids = [r.id for r in records]

        if "bm25" in selected:
            top = [ids[j] for j, _s in rank(t["question"], docs, limit=args.top_k)]
            start = time.monotonic()
            cand = answer(client, t["question"], context_from_ids(machine, top))
            ok = judge(client, t["question"], reference, cand)
            stats["bm25"][0] += int(ok)
            stats["bm25"][1] += 2
            stats["bm25"][2] += time.monotonic() - start

        if "vector" in selected:
            top = [
                ids[j]
                for j, _s in rank_semantic(t["question"], docs, embedder, limit=args.top_k)
            ]
            start = time.monotonic()
            cand = answer(client, t["question"], context_from_ids(machine, top))
            ok = judge(client, t["question"], reference, cand)
            stats["vector"][0] += int(ok)
            stats["vector"][1] += 2
            stats["vector"][2] += time.monotonic() - start

        if "agents" in selected:
            machine.client = client
            machine.whiteboard.annotations = []
            machine._invalidate_recall_cache()
            before = client.calls
            start = time.monotonic()
            res = machine.recall(t["question"])
            annotated = [a["memory_id"] for a in res.get("annotations", [])]
            cand = answer(client, t["question"], context_from_ids(machine, annotated))
            ok = judge(client, t["question"], reference, cand)
            stats["agents"][0] += int(ok)
            stats["agents"][1] += client.calls - before
            stats["agents"][2] += time.monotonic() - start

        print(f"  [{i + 1}/{len(tasks)}] done", flush=True)

    n = max(len(tasks), 1)
    print(f"\ndataset: {args.dataset} | questions: {len(tasks)} | top_k: {args.top_k}\n")
    print(f"{'arm':<12} {'answer accuracy':>16} {'calls/query':>12} {'latency(s)':>11}")
    for name, (hits, calls, latency) in stats.items():
        print(f"{name:<12} {hits / n:>16.2f} {calls / n:>12.1f} {latency / n:>11.2f}")


if __name__ == "__main__":
    main()
