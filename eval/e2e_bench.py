"""End-to-end answer accuracy with an LLM judge (v0.8).

For each frozen synthetic task and each arm the pipeline is:

    recall -> whiteboard -> main chatbot -> answer -> LLM judge (vs gold)

Arms:
  no_memory        closed-book: empty whiteboard (floor)
  bm25             top-k BM25 memories as full-text context (flat RAG)
  agents_group     group agents recall -> whiteboard (annotation notes only)
  agents_view      view agents + lexical dimension plan + attention prior
  agents_view_ctx  same retrieval, plus the full text of annotated memories
  oracle           gold evidence memories as full-text context (ceiling)

Every boundary is snapshotted to ``eval/out/e2e_<arm>.jsonl`` so a wrong answer
can be attributed to retrieval / context loss / the answerer / the judge. The
judge is 3-way (correct|partial|incorrect) with a frozen prompt; a stratified
sample gets a second pass (audit) to measure judge agreement. The Answer
Utilization Rate (AUR) is ``P(correct | evidence complete)``.

Run:  PYTHONPATH=src python3 eval/e2e_bench.py --arms no_memory,bm25,agents_view
"""

from __future__ import annotations

import argparse
import json
import random
import shutil
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from memory_machine.config import Config
from memory_machine.llm import LLMClient, extract_json_object
from memory_machine.main_chatbot import run_main_chatbot
from memory_machine.retrieval import rank, tokenize

from view_router_bench import CountingClient, TASKS, build_machine

HERE = Path(__file__).resolve().parent
GOLD_PATH = HERE / "gold_answers.json"
OUT_DIR = HERE / "out"
JUDGE_PROMPT_VERSION = "v1"

JUDGE_SYSTEM = """You grade an answer to a question against a reference answer. \
Grade only the content, never the style or length.

Return ONLY a JSON object, nothing else:
{"verdict":"correct","reason":"<short>"}

Rules:
- "correct": the candidate is semantically equivalent to the reference. \
Paraphrases count; numbers, names and dates must match.
- "partial": the candidate contains part of the reference but misses a required \
piece, or is vaguer than the reference.
- "incorrect": the candidate contradicts the reference, does not answer, or says \
it does not know when the reference contains the answer."""

VIEW_CONFIG = dict(
    capacity=5,
    router_enabled=True,
    router_mode="views",
    view_router_mode="lexical",
    view_dimension_mode="auto",
    agent_mode="view",
    attention_mode="prior",
    view_top_k=3,
)

ARMS: dict[str, dict[str, Any]] = {
    "no_memory": {},
    "bm25": {},
    "agents_group": dict(capacity=5, router_enabled=False, agent_mode="group"),
    "agents_view": dict(VIEW_CONFIG),
    "agents_view_ctx": dict(VIEW_CONFIG),
    "oracle": {},
}


def load_gold() -> dict[int, str]:
    return {int(k): v for k, v in json.loads(GOLD_PATH.read_text(encoding="utf-8")).items()}


def full_text(machine: Any, ids: list[str], *, budget: int = 6000) -> str:
    by_id = {r.id: r for r in machine.tape.read()}
    blocks: list[str] = []
    used = 0
    for mid in ids:
        record = by_id.get(mid)
        if record is None:
            continue
        block = f"[{record.id}] {record.summary}\n{record.why}"
        if blocks and used + len(block) > budget:
            break
        blocks.append(block)
        used += len(block)
    return "\n\n".join(blocks)


def answer_with(
    client: CountingClient,
    machine: Any,
    question: str,
    *,
    extra_context: str = "",
) -> str:
    machine.whiteboard.subject = question
    clean, _memories, _reasoning = run_main_chatbot(
        client, machine.whiteboard, question, extra_context=extra_context
    )
    return clean.strip()


def judge(
    client: CountingClient, question: str, reference: str, candidate: str
) -> tuple[str, str]:
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
    obj = extract_json_object(content)
    verdict = str(obj.get("verdict") or "").strip().lower()
    if verdict not in {"correct", "partial", "incorrect"}:
        verdict = "incorrect"
    return verdict, str(obj.get("reason") or "").strip()


def fact_coverage(machine: Any, required_ids: list[str], prompt: str) -> float:
    tokens: set[str] = set()
    by_id = {r.id: r for r in machine.tape.read()}
    for mid in required_ids:
        record = by_id.get(mid)
        if record is not None:
            tokens |= set(tokenize(record.summary))
    if not tokens:
        return 1.0
    return len(tokens & set(tokenize(prompt))) / len(tokens)


def run_case(
    arm: str,
    index: int,
    task: dict[str, Any],
    gold: str,
    root: Path,
    client: CountingClient,
    judge_client: CountingClient,
    id_map: dict[str, str],
    *,
    ctx_budget: int,
) -> dict[str, Any]:
    cfg = Config(**ARMS[arm])
    machine, _ = build_machine(root / f"{arm}_{index:02d}", cfg, client)
    required_ids = [id_map[k] for k in task["required"]]
    required = set(required_ids)

    before = client.calls
    start = time.monotonic()
    context = ""
    evidence_complete: int | None = None

    if arm == "no_memory":
        answer = answer_with(client, machine, task["q"])
    elif arm == "bm25":
        records = machine.tape.read()
        docs = [r.text() for r in records]
        ids = [r.id for r in records]
        top = [ids[j] for j, _s in rank(task["q"], docs, limit=5)]
        context = full_text(machine, top, budget=ctx_budget)
        evidence_complete = int(required <= set(top))
        answer = answer_with(client, machine, task["q"], extra_context=context)
    elif arm in {"agents_group", "agents_view", "agents_view_ctx"}:
        machine._invalidate_recall_cache()
        res = machine.recall(task["q"], debug=True)
        routing = res.get("routing") or {}
        consulted = set(routing.get("consulted_ids") or [])
        annotated = [a["memory_id"] for a in res.get("annotations") or []]
        evidence_complete = int(required <= consulted)
        if arm == "agents_view_ctx":
            context = full_text(machine, annotated, budget=ctx_budget)
        answer = answer_with(client, machine, task["q"], extra_context=context)
    else:  # oracle
        context = full_text(machine, required_ids, budget=ctx_budget)
        evidence_complete = 1
        answer = answer_with(client, machine, task["q"], extra_context=context)

    latency = time.monotonic() - start
    prompt = machine.whiteboard.render() + ("\n\n" + context if context else "")
    answer_prompt = (
        "## Whiteboard\n\n"
        + machine.whiteboard.render()
        + (f"\n\n## External context\n\n{context}" if context else "")
        + f"\n\n## Task\n\n{task['q']}"
    )
    before_judge = judge_client.calls
    verdict, reason = judge(judge_client, task["q"], gold, answer)
    judge_calls = judge_client.calls - before_judge

    return {
        "arm": arm,
        "task": index,
        "cat": task["cat"],
        "question": task["q"],
        "gold": gold,
        "required_ids": required_ids,
        "retrieved_ids": sorted(set((res.get("routing") or {}).get("consulted_ids") or []))
        if arm in {"agents_group", "agents_view", "agents_view_ctx"}
        else [],
        "evidence_complete": evidence_complete,
        "context_chars": len(context),
        "whiteboard_rendered": machine.whiteboard.render(),
        "dimension_boards_rendered": {
            d: b.render() for d, b in machine.whiteboard.boards.items()
        },
        "attention": dict(machine.whiteboard.attention),
        "answer_prompt_final": answer_prompt,
        "fact_coverage": round(fact_coverage(machine, required_ids, prompt), 3),
        "answer": answer,
        "judge": {"verdict": verdict, "reason": reason, "prompt_version": JUDGE_PROMPT_VERSION},
        "calls": client.calls - before,
        "judge_calls": judge_calls,
        "latency": round(latency, 2),
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(rows)
    complete = [r for r in rows if r["evidence_complete"] == 1]
    strict = sum(1 for r in rows if r["judge"]["verdict"] == "correct")
    lenient = sum(1 for r in rows if r["judge"]["verdict"] in {"correct", "partial"})
    aur = (
        sum(1 for r in complete if r["judge"]["verdict"] == "correct") / len(complete)
        if complete
        else None
    )
    return {
        "n": n,
        "evidence_complete": len(complete) / n if n else 0.0,
        "strict": strict / n if n else 0.0,
        "lenient": lenient / n if n else 0.0,
        "aur": aur,
        "calls": sum(r["calls"] for r in rows) / n if n else 0.0,
        "latency": sum(r["latency"] for r in rows) / n if n else 0.0,
    }


def audit_sample(rows: list[dict[str, Any]], fraction: float, seed: int) -> list[dict[str, Any]]:
    """Stratify by (verdict, evidence_complete) and take ~fraction."""
    rng = random.Random(seed)
    buckets: dict[tuple[str, int | None], list[dict[str, Any]]] = {}
    for row in rows:
        key = (row["judge"]["verdict"], row["evidence_complete"])
        buckets.setdefault(key, []).append(row)
    size = max(1, int(len(rows) * fraction))
    picked: list[dict[str, Any]] = []
    keys = list(buckets)
    rng.shuffle(keys)
    while len(picked) < size and any(buckets.values()):
        for key in keys:
            if buckets[key] and len(picked) < size:
                picked.append(buckets[key].pop(0))
    return picked


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--arms", default="no_memory,bm25,agents_group,agents_view,agents_view_ctx,oracle")
    p.add_argument("--indices", default="", help="comma-separated task indices")
    p.add_argument("--limit", type=int, default=0, help="0 = all")
    p.add_argument("--model", default="deepseek-v4-flash")
    p.add_argument("--judge-model", default="deepseek-v4-flash")
    p.add_argument("--audit-model", default="", help="default: same as judge model")
    p.add_argument("--audit-fraction", type=float, default=0.25)
    p.add_argument("--ctx-budget", type=int, default=6000)
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--api-key", default="")
    p.add_argument("--no-audit", action="store_true")
    p.add_argument("--keep", action="store_true")
    args = p.parse_args()

    import os

    api_key = args.api_key or os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key:
        raise SystemExit("set DEEPSEEK_API_KEY (or --api-key)")

    gold = load_gold()
    indices = [int(x) for x in args.indices.split(",") if x.strip()] or list(range(len(TASKS)))
    if args.limit > 0:
        indices = indices[: args.limit]
    arms = [a.strip() for a in args.arms.split(",") if a.strip()]

    base = CountingClient(
        LLMClient("https://api.deepseek.com", api_key, args.model, retries=1, backoff=0.5)
    )
    judge_client = CountingClient(
        LLMClient("https://api.deepseek.com", api_key, args.judge_model, retries=1, backoff=0.5)
    )
    root = Path(tempfile.mkdtemp(prefix="mm-e2e-"))
    _machine, id_map = build_machine(root / "_fixture", Config(capacity=5))

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=HERE, text=True
        ).strip()
    except Exception:
        commit = ""
    manifest = {
        "run_id": datetime.now(timezone.utc).strftime("%Y-%m-%d-e2e-%H%M%S"),
        "model": args.model,
        "judge_model": args.judge_model,
        "audit_judge_model": args.audit_model or args.judge_model,
        "judge_prompt_version": JUDGE_PROMPT_VERSION,
        "ctx_budget": args.ctx_budget,
        "git_commit": commit,
        "fixture_version": "frozen-32",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "arms": arms,
        "indices": indices,
    }
    manifest_name = (
        f"run_manifest_{arms[0]}.json" if len(arms) == 1 else "run_manifest.json"
    )
    (OUT_DIR / manifest_name).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    all_rows: list[dict[str, Any]] = []
    for arm in arms:
        rows: list[dict[str, Any]] = []
        print(f"running {arm} ...", flush=True)
        for i in indices:
            task = TASKS[i]
            if i not in gold:
                continue
            rows.append(
                run_case(
                    arm, i, task, gold[i], root, base, judge_client, id_map,
                    ctx_budget=args.ctx_budget,
                )
            )
        path = OUT_DIR / f"e2e_{arm}.jsonl"
        with path.open("w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        all_rows.extend(rows)
        s = summarize(rows)
        aur = f"{s['aur']:.2f}" if s["aur"] is not None else "  - "
        print(
            f"  n={s['n']} evidence={s['evidence_complete']:.2f} strict={s['strict']:.2f} "
            f"lenient={s['lenient']:.2f} AUR={aur} calls={s['calls']:.1f}",
            flush=True,
        )

    print("\nfinal table:")
    print(f"{'arm':<17} {'n':>3} {'evid':>6} {'strict':>7} {'lenient':>8} {'AUR':>6} {'calls':>7}")
    for arm in arms:
        rows = [r for r in all_rows if r["arm"] == arm]
        s = summarize(rows)
        aur = f"{s['aur']:.2f}" if s["aur"] is not None else "  - "
        print(
            f"{arm:<17} {s['n']:>3} {s['evidence_complete']:>6.2f} {s['strict']:>7.2f} "
            f"{s['lenient']:>8.2f} {aur:>6} {s['calls']:>7.1f}"
        )

    if not args.no_audit and all_rows:
        sample = audit_sample(all_rows, args.audit_fraction, args.seed)
        audit_model = args.audit_model or args.judge_model
        audit_client = CountingClient(
            LLMClient("https://api.deepseek.com", api_key, audit_model, retries=1, backoff=0.5)
        )
        audit_rows: list[dict[str, Any]] = []
        for row in sample:
            verdict, reason = judge(
                audit_client, row["question"], row["gold"], row["answer"]
            )
            audit_rows.append(
                {
                    "arm": row["arm"],
                    "task": row["task"],
                    "first_verdict": row["judge"]["verdict"],
                    "audit_verdict": verdict,
                    "audit_reason": reason,
                    "audit_model": audit_model,
                }
            )
        audit_name = (
            f"judge_audit_{arms[0]}.jsonl" if len(arms) == 1 else "judge_audit.jsonl"
        )
        path = OUT_DIR / audit_name
        with path.open("w", encoding="utf-8") as fh:
            for row in audit_rows:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        agree = sum(1 for r in audit_rows if r["first_verdict"] == r["audit_verdict"])
        print(
            f"\naudit ({audit_model}): {agree}/{len(audit_rows)} agreement "
            f"({agree / max(1, len(audit_rows)):.2f}) -> {path}"
        )

    if not args.keep:
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    main()
