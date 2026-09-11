"""End-to-end answer accuracy with an LLM judge (v0.8/v0.9).

For each task and each arm the pipeline is:

    recall -> whiteboard -> main chatbot -> answer -> LLM judge (vs gold)

Arms:
  no_memory            closed-book: empty whiteboard (floor)
  bm25                 top-k BM25 memories as full-text context (flat RAG)
  agents_group         group agents recall -> whiteboard (annotation notes only)
  agents_view          view agents + lexical dimension plan + attention prior
  agents_view_ctx      same retrieval, plus the full text of annotated memories
  agents_view_payload  same retrieval, plus the budgeted evidence payload (v0.9)
  oracle               gold evidence memories as full-text context (ceiling)

Every boundary is snapshotted to ``eval/out/e2e_<arm>.jsonl`` so a wrong answer
can be attributed to retrieval / context loss / the answerer / the judge. The
judge is 3-way (correct|partial|incorrect) with a frozen prompt; a stratified
sample gets a second pass (audit) to measure judge agreement. The Answer
Utilization Rate (AUR) is ``P(correct | evidence complete)``.

Datasets: the frozen synthetic fixture (32 tasks, authored gold answers) or
LongMemEval (reference answers, sessions tagged into views at write time).

Run:  PYTHONPATH=src python3 eval/e2e_bench.py --arms agents_view_payload
      PYTHONPATH=src python3 eval/e2e_bench.py --dataset longmemeval --limit 12 \
          --arms agents_view_ctx,agents_view_payload --tag
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
from typing import Any, Callable

from memory_machine.config import Config
from memory_machine.coordinator import Machine
from memory_machine.llm import LLMClient, extract_json_object
from memory_machine.main_chatbot import run_main_chatbot
from memory_machine.payload import payload_as_context
from memory_machine.retrieval import rank, tokenize
from memory_machine.secrets import SecretError
from memory_machine.tape import MemoryRecord

from tag_sessions import tag_sessions, views_for
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

GFR_SYSTEM = """You check whether a memory contains the information needed to answer a question. Judge only the memory text, not your own knowledge.

Return ONLY a JSON object, nothing else:
{"contains":true,"reason":"<short>"}

"contains" is true when the memory text holds the fact the reference answer states (a paraphrase counts; a partial fact counts only if it is enough to give the reference answer)."""


ERROR_SYSTEM = """You classify why an answer failed, given the question, the reference answer and the evidence that was available.

Return ONLY a JSON object, nothing else:
{"kind":"<one of: temporal_misread, ignored_memory, insufficient_evidence, reasoning_error, abstention, other>","reason":"<short>"}

Kinds:
- temporal_misread: the evidence had the fact but the answer mixed past/current state.
- ignored_memory: the evidence clearly contained the fact and the answer did not use it.
- insufficient_evidence: the evidence did not contain the fact needed.
- reasoning_error: the fact was present but the answer reasoned incorrectly.
- abstention: the answer declined although the evidence had the fact.
- other: anything else."""


def classify_error(
    client: CountingClient, question: str, gold: str, evidence: str, answer: str
) -> tuple[str, str]:
    messages = [
        {"role": "system", "content": ERROR_SYSTEM},
        {
            "role": "user",
            "content": (
                f"Question: {question}\nReference answer: {gold}\n"
                f"Evidence available:\n{evidence or '(none)'}\n"
                f"Candidate answer: {answer}"
            ),
        },
    ]
    content = client.complete(messages, temperature=0.0)
    obj = extract_json_object(content)
    kind = str(obj.get("kind") or "").strip().lower()
    if kind not in {
        "temporal_misread", "ignored_memory", "insufficient_evidence",
        "reasoning_error", "abstention", "other",
    }:
        kind = "other"
    return kind, str(obj.get("reason") or "").strip()


def gfr_check(
    client: CountingClient, question: str, gold: str, memory_text: str
) -> tuple[int, str]:
    """Gold Fact Retention: did the needed fact survive ingestion?"""
    if not memory_text.strip():
        return 0, "no evidence session in memory"
    messages = [
        {"role": "system", "content": GFR_SYSTEM},
        {
            "role": "user",
            "content": (
                f"Question: {question}\nReference answer: {gold}\n"
                f"Memory:\n{memory_text}"
            ),
        },
    ]
    content = client.complete(messages, temperature=0.0)
    obj = extract_json_object(content)
    return int(obj.get("contains") is True), str(obj.get("reason") or "").strip()


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
    "agents_view_payload": dict(VIEW_CONFIG, evidence_payload="budgeted"),
    "agents_view_payload_memory": dict(VIEW_CONFIG, evidence_payload="budgeted"),
    "agents_view_payload_dates": dict(VIEW_CONFIG, evidence_payload="budgeted"),
    "oracle": {},
    "oracle_memory": {},
    "oracle_dates": {},
}

MEMORY_AWARE_ARMS = {"agents_view_payload_memory", "oracle_memory"}
DATES_ARMS = {"agents_view_payload_dates", "oracle_dates"}
ORACLE_BUDGETS = {"oracle": 6000, "oracle_memory": 6000, "oracle_dates": 0}

RECALL_ARMS = {
    "agents_group", "agents_view", "agents_view_ctx",
    "agents_view_payload", "agents_view_payload_memory",
    "agents_view_payload_dates",
}


def load_gold() -> dict[int, str]:
    return {int(k): v for k, v in json.loads(GOLD_PATH.read_text(encoding="utf-8")).items()}


def full_text(machine: Any, ids: list[str], *, budget: int = 6000) -> str:
    """Full text of the records; ``budget <= 0`` means no cap (oracle)."""
    by_id = {r.id: r for r in machine.tape.read()}
    blocks: list[str] = []
    used = 0
    for mid in ids:
        record = by_id.get(mid)
        if record is None:
            continue
        block = f"[{record.id}] {record.summary}\n{record.why}"
        if budget > 0 and blocks and used + len(block) > budget:
            break
        blocks.append(block)
        used += len(block)
        if used > 2_000_000:  # technical guard only
            break
    return "\n\n".join(blocks)


DATE_RE = __import__("re").compile(r"(\d{4})/(\d{2})/(\d{2}).*?(\d{2}):(\d{2})")


def parse_date(raw: str) -> str:
    """'2023/05/20 (Sat) 02:21' -> '2023-05-20T02:21:00' ('' when unparseable)."""
    m = DATE_RE.search(raw or "")
    if not m:
        return ""
    y, mo, d, h, mi = m.groups()
    return f"{y}-{mo}-{d}T{h}:{mi}:00"


def answer_with(
    client: CountingClient,
    machine: Any,
    question: str,
    *,
    extra_context: str = "",
    memory_aware: bool = False,
) -> str:
    machine.whiteboard.subject = question
    clean, _memories, _reasoning = run_main_chatbot(
        client,
        machine.whiteboard,
        question,
        extra_context=extra_context,
        memory_aware=memory_aware,
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


def _run_arm(
    arm: str,
    index: int,
    question: str,
    cat: str,
    gold: str,
    required_ids: list[str],
    machine: Any,
    client: CountingClient,
    judge_client: CountingClient,
    *,
    ctx_budget: int,
    expected_sessions: list[str] | None = None,
    error_classify: bool = False,
    question_date: str = "",
) -> dict[str, Any]:
    required = set(required_ids)
    before = client.calls
    start = time.monotonic()
    context = ""
    evidence_complete: int | None = None
    res: dict[str, Any] | None = None

    memory_aware = arm in MEMORY_AWARE_ARMS
    provenance = (
        f"\n\n(Question asked on {question_date}.)" if question_date else ""
    )
    if arm == "no_memory":
        answer = answer_with(
            client, machine, question + provenance, memory_aware=memory_aware
        )
    elif arm == "bm25":
        records = machine.tape.read()
        docs = [r.text() for r in records]
        ids = [r.id for r in records]
        top = [ids[j] for j, _s in rank(question, docs, limit=5)]
        context = full_text(machine, top, budget=ctx_budget)
        evidence_complete = int(required <= set(top))
        answer = answer_with(
            client, machine, question + provenance, extra_context=context,
            memory_aware=memory_aware,
        )
    elif arm in RECALL_ARMS:
        machine._invalidate_recall_cache()
        res = machine.recall(question, debug=True)
        routing = res.get("routing") or {}
        consulted = set(routing.get("consulted_ids") or [])
        annotated = [a["memory_id"] for a in res.get("annotations") or []]
        evidence_complete = int(required <= consulted)
        if arm == "agents_view_ctx":
            context = full_text(machine, annotated, budget=ctx_budget)
        elif arm in {"agents_view_payload", "agents_view_payload_memory"}:
            context = payload_as_context(res.get("evidence_payload") or [])
        answer = answer_with(
            client, machine, question + provenance, extra_context=context,
            memory_aware=memory_aware,
        )
    else:  # oracle
        context = full_text(machine, required_ids, budget=ctx_budget)
        evidence_complete = 1
        answer = answer_with(
            client, machine, question + provenance, extra_context=context,
            memory_aware=memory_aware,
        )

    latency = time.monotonic() - start
    prompt = machine.whiteboard.render() + ("\n\n" + context if context else "")
    answer_prompt = (
        "## Whiteboard\n\n"
        + machine.whiteboard.render()
        + (f"\n\n## External context\n\n{context}" if context else "")
        + f"\n\n## Task\n\n{question}{provenance}"
    )
    before_judge = judge_client.calls
    verdict, reason = judge(judge_client, question, gold, answer)
    judge_calls = judge_client.calls - before_judge
    error_kind = ""
    if error_classify and verdict != "correct":
        error_kind, _er = classify_error(judge_client, question, gold, context, answer)

    return {
        "arm": arm,
        "task": index,
        "cat": cat,
        "question": question,
        "gold": gold,
        "expected_sessions": expected_sessions or [],
        "required_ids": required_ids,
        "retrieved_ids": sorted(set((res.get("routing") or {}).get("consulted_ids") or []))
        if res is not None
        else [],
        "evidence_complete": evidence_complete,
        "context_chars": len(context),
        "payload_chars": int(res.get("evidence_payload_chars", 0)) if res is not None else 0,
        "payload_items": [
            {
                "memory_id": item["memory_id"],
                "used_chars": item["used_chars"],
                "source": item["source"],
                "truncated": item["truncated"],
            }
            for item in (res.get("evidence_payload") or [])
        ]
        if res is not None
        else [],
        "whiteboard_rendered": machine.whiteboard.render(),
        "dimension_boards_rendered": {
            d: b.render() for d, b in machine.whiteboard.boards.items()
        },
        "attention": dict(machine.whiteboard.attention),
        "answer_prompt_final": answer_prompt,
        "fact_coverage": round(fact_coverage(machine, required_ids, prompt), 3),
        "answer": answer,
        "judge": {"verdict": verdict, "reason": reason, "prompt_version": JUDGE_PROMPT_VERSION},
        "error_kind": error_kind,
        "memory_aware": memory_aware,
        "calls": client.calls - before,
        "judge_calls": judge_calls,
        "latency": round(latency, 2),
    }


def run_synthetic_case(
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
    payload_budget: int = 0,
    ingest_summary: int = 300,
    ingest_why: int = 2000,
    gfr: bool = False,
) -> dict[str, Any]:
    cfg = Config(**ARMS[arm])
    if payload_budget and arm in {
        "agents_view_payload", "agents_view_payload_memory", "agents_view_payload_dates",
    }:
        cfg.evidence_payload_budget = payload_budget
    machine, _ = build_machine(root / f"{arm}_{index:02d}", cfg, client)
    required_ids = [id_map[k] for k in task["required"]]
    return _run_arm(
        arm, index, task["q"], task["cat"], gold, required_ids, machine,
        client, judge_client, ctx_budget=ctx_budget,
    )


def build_external_machine(
    path: Path,
    task: dict[str, Any],
    cfg: Config,
    tags: dict[str, dict[str, Any]],
    client: Any,
    *,
    summary_limit: int = 300,
    why_limit: int = 2000,
    dates: bool = False,
) -> tuple[Any, dict[str, str]]:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)
    machine = Machine(path, config=cfg, client=client)
    id_map: dict[str, str] = {}
    skipped = 0
    for session in task["sessions"]:
        text = session["text"]
        record = MemoryRecord(
            type="memory",
            summary=(text[:summary_limit] if summary_limit else text) or session["id"],
            why=text[:why_limit] if why_limit else text,
            created_at=parse_date(session.get("date", "")) if dates else "",
            source=session["id"],
            views=views_for(tags.get(session["id"])),
        )
        try:
            result = machine.add_memory(record, save=False)
        except SecretError:
            # the secret scanner gates every tape write; benchmark sessions that
            # look like credentials are skipped rather than bypassing the gate.
            skipped += 1
            continue
        id_map[session["id"]] = result["record"]["id"]
    machine.save()
    machine._e2e_skipped = skipped  # type: ignore[attr-defined]
    return machine, id_map


def run_external_case(
    arm: str,
    index: int,
    task: dict[str, Any],
    gold: str,
    root: Path,
    client: CountingClient,
    judge_client: CountingClient,
    tags: dict[str, dict[str, Any]],
    *,
    ctx_budget: int,
    payload_budget: int = 0,
    ingest_summary: int = 300,
    ingest_why: int = 2000,
    gfr: bool = False,
    error_classify: bool = False,
    ingest_dates: bool = False,
) -> dict[str, Any]:
    use_dates = ingest_dates or arm in DATES_ARMS
    cfg = Config(**ARMS[arm])
    if payload_budget and arm in {
        "agents_view_payload", "agents_view_payload_memory", "agents_view_payload_dates",
    }:
        cfg.evidence_payload_budget = payload_budget
    machine, id_map = build_external_machine(
        root / f"{arm}_{index:02d}", task, cfg, tags, client,
        summary_limit=ingest_summary, why_limit=ingest_why, dates=use_dates,
    )
    expected = [s for s in task["expected"] if s in id_map]
    required_ids = [id_map[s] for s in expected]
    row = _run_arm(
        arm, index, task["question"], task.get("type", "external"), gold, required_ids,
        machine, client, judge_client, ctx_budget=ctx_budget, expected_sessions=expected,
        error_classify=error_classify,
        question_date=task.get("question_date", "") if use_dates else "",
    )
    row["ingest_summary"] = ingest_summary
    row["ingest_why"] = ingest_why
    row["ingest_skipped"] = int(getattr(machine, "_e2e_skipped", 0))
    row["ingest_dates"] = use_dates
    if use_dates:
        time_views = sorted({v for r in machine.tape.read() for v in r.views if v.startswith("time/")})
        row["time_views"] = time_views
        sample = next((r.created_at[:16] for r in machine.tape.read() if r.created_at), "")
        row["created_at_sample"] = sample
    if gfr:
        by_id = {r.id: r for r in machine.tape.read()}
        evidence_text = "\n\n".join(
            f"[{mid}] {by_id[mid].summary}\n{by_id[mid].why}"
            for mid in required_ids
            if mid in by_id
        )
        contains, reason = gfr_check(judge_client, task["question"], gold, evidence_text)
        row["gfr"] = contains
        row["gfr_reason"] = reason
    return row


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
    p.add_argument("--dataset", choices=["synthetic", "longmemeval"], default="synthetic")
    p.add_argument("--arms", default="no_memory,bm25,agents_group,agents_view,agents_view_ctx,agents_view_payload,oracle")
    p.add_argument("--indices", default="", help="comma-separated task indices")
    p.add_argument("--limit", type=int, default=0, help="0 = all")
    p.add_argument("--model", default="deepseek-v4-flash")
    p.add_argument("--judge-model", default="deepseek-v4-flash")
    p.add_argument("--timeout", type=int, default=120, help="LLM request timeout (seconds)")
    p.add_argument("--audit-model", default="", help="default: same as judge model")
    p.add_argument("--audit-fraction", type=float, default=0.25)
    p.add_argument("--ctx-budget", type=int, default=6000)
    p.add_argument("--payload-budget", type=int, default=0, help="override the v0.9 payload budget")
    p.add_argument("--ingest-summary", type=int, default=300, help="summary chars at ingestion")
    p.add_argument("--ingest-why", type=int, default=2000, help="why chars at ingestion (0 = full text)")
    p.add_argument("--gfr", action="store_true", help="measure Gold Fact Retention per case")
    p.add_argument("--error-classify", action="store_true", help="classify answerer failures")
    p.add_argument("--ingest-dates", action="store_true",
                   help="restore real session timestamps and the question date (H5')")
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--tag", action="store_true", help="tag external sessions at write time")
    p.add_argument("--api-key", default="")
    p.add_argument("--no-audit", action="store_true")
    p.add_argument("--keep", action="store_true")
    args = p.parse_args()

    import os

    api_key = args.api_key or os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key:
        raise SystemExit("set DEEPSEEK_API_KEY (or --api-key)")

    base = CountingClient(
        LLMClient("https://api.deepseek.com", api_key, args.model,
                  timeout=args.timeout, retries=1, backoff=0.5)
    )
    judge_client = CountingClient(
        LLMClient("https://api.deepseek.com", api_key, args.judge_model,
                  timeout=args.timeout, retries=1, backoff=0.5)
    )
    root = Path(tempfile.mkdtemp(prefix="mm-e2e-"))
    arms = [a.strip() for a in args.arms.split(",") if a.strip()]

    tags: dict[str, dict[str, Any]] = {}
    if args.dataset == "synthetic":
        gold = load_gold()
        indices = [int(x) for x in args.indices.split(",") if x.strip()] or list(range(len(TASKS)))
        if args.limit > 0:
            indices = indices[: args.limit]
        _machine, id_map = build_machine(root / "_fixture", Config(capacity=5))
        runner: Callable[..., dict[str, Any]] = run_synthetic_case
        extra: dict[str, Any] = {"id_map": id_map}
        tasks: dict[int, dict[str, Any]] = {i: TASKS[i] for i in indices}
    else:
        from external_bench import DATA, load_longmemeval

        tasks_list = load_longmemeval(DATA / "longmemeval_s_cleaned.json", args.limit, args.seed)
        raw = json.loads((DATA / "longmemeval_s_cleaned.json").read_text(encoding="utf-8"))
        by_q = {item["question"]: item.get("answer", "") for item in raw}
        gold = {i: by_q.get(t["question"], "") for i, t in enumerate(tasks_list)}
        indices = [i for i in range(len(tasks_list)) if gold.get(i)]
        tasks = {i: tasks_list[i] for i in indices}
        if args.tag:
            unique: dict[str, dict[str, Any]] = {}
            for t in tasks.values():
                for s in t["sessions"]:
                    unique.setdefault(s["id"], s)
            print(f"tagging {len(unique)} sessions ...", flush=True)
            tags = tag_sessions("longmemeval", list(unique.values()), base, batch=8)
        runner = run_external_case
        extra = {"tags": tags}

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=HERE, text=True
        ).strip()
    except Exception:
        commit = ""
    run_id = datetime.now(timezone.utc).strftime("%Y-%m-%d-e2e-%H%M%S")
    manifest = {
        "run_id": run_id,
        "dataset": args.dataset,
        "model": args.model,
        "judge_model": args.judge_model,
        "audit_judge_model": args.audit_model or args.judge_model,
        "judge_prompt_version": JUDGE_PROMPT_VERSION,
        "ctx_budget": args.ctx_budget,
        "ingest_summary": args.ingest_summary,
        "ingest_why": args.ingest_why,
        "gfr": args.gfr,
        "error_classify": args.error_classify,
        "ingest_dates": args.ingest_dates,
        "git_commit": commit,
        "fixture_version": "frozen-32" if args.dataset == "synthetic" else "longmemeval",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "arms": arms,
        "indices": indices,
    }
    suffix = f"_{args.dataset}" if args.dataset != "synthetic" else ""
    if args.dataset == "longmemeval" and args.ingest_why != 2000:
        suffix += f"_ing{args.ingest_why}"
    if args.dataset == "longmemeval" and args.payload_budget:
        suffix += f"_pb{args.payload_budget}"
    manifest_name = (
        f"run_manifest_{arms[0]}{suffix}.json" if len(arms) == 1 else f"run_manifest{suffix}.json"
    )
    (OUT_DIR / manifest_name).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    all_rows: list[dict[str, Any]] = []
    for arm in arms:
        rows: list[dict[str, Any]] = []
        errors = 0
        print(f"running {arm} ...", flush=True)
        for i in indices:
            task = tasks[i]
            if not gold.get(i):
                continue
            try:
                rows.append(
                    runner(
                        arm, i, task, gold[i], root, base, judge_client,
                        ctx_budget=args.ctx_budget, payload_budget=args.payload_budget,
                        ingest_summary=args.ingest_summary, ingest_why=args.ingest_why,
                        gfr=args.gfr, error_classify=args.error_classify,
                        ingest_dates=args.ingest_dates,
                        **extra,
                    )
                )
            except Exception as exc:  # one bad case must not abort the arm
                errors += 1
                print(f"  case {i} failed: {type(exc).__name__}: {exc}", flush=True)
        if errors:
            print(f"  {errors} case(s) skipped", flush=True)
        path = OUT_DIR / f"e2e_{arm}{suffix}.jsonl"
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
    print(f"{'arm':<19} {'n':>3} {'evid':>6} {'strict':>7} {'lenient':>8} {'AUR':>6} {'calls':>7}")
    for arm in arms:
        rows = [r for r in all_rows if r["arm"] == arm]
        s = summarize(rows)
        aur = f"{s['aur']:.2f}" if s["aur"] is not None else "  - "
        print(
            f"{arm:<19} {s['n']:>3} {s['evidence_complete']:>6.2f} {s['strict']:>7.2f} "
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
            verdict, reason = judge(audit_client, row["question"], row["gold"], row["answer"])
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
            f"judge_audit_{arms[0]}{suffix}.jsonl" if len(arms) == 1 else f"judge_audit{suffix}.jsonl"
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
