"""Controlled topology benchmark: does write-time organization route better?

A synthetic tape with known views and ground truth. Seven arms:

  full          — every memory agent consulted (system recall ceiling)
  similarity    — the current LLM similarity router over partitions
  view_bm25     — view router: BM25 over view name + member summaries
  view_llm      — view router: LLM picks views from the query + whiteboard
  view_oracle   — ground-truth views (diagnostic ceiling of the topology)
  cascade_bm25  — view_bm25 -> co-occurrence expansion -> similarity -> full
  cascade_llm   — view_llm  -> co-occurrence expansion -> similarity -> full

Metrics per arm: view recall/precision, evidence recall (mean + complete),
agent recall (mean + complete), routing reduction, expansion factor, fallback
rate/reasons, LLM calls/query, tokens/query (chars/4) and latency. This
separates "the router picked the wrong region" from "the agents missed the
memory" instead of mixing both into one recall number.

Run:  PYTHONPATH=src python3 eval/view_router_bench.py
"""

from __future__ import annotations

import argparse
import random
import shutil
import time
from collections import Counter
from pathlib import Path
from typing import Any

from memory_machine.config import Config
from memory_machine.coordinator import Machine
from memory_machine.llm import LLMClient
from memory_machine.tape import MemoryRecord

# --------------------------------------------------------------------- fixture
# Each spec has a stable key so tasks can reference ground-truth memories.
MEMORIES: list[dict[str, Any]] = [
    # memory-machine / router
    {"key": "router_llm", "type": "decision", "created": "2026-05-12",
     "summary": "Keep the LLM router opt-in: router_enabled stays false by default",
     "why": "It saved calls but skipped partitions that held relevant memories.",
     "views": ["topic/router", "subject/memory-machine"]},
    {"key": "router_embed", "type": "lesson", "created": "2026-06-03",
     "summary": "The embedding router lost evidence recall on LongMemEval, so it was disabled",
     "why": "Dense similarity to partition digests missed lexically distant memories.",
     "views": ["topic/router", "subject/memory-machine"]},
    {"key": "router_lexical", "type": "lesson", "created": "2026-06-20",
     "summary": "Lexical routing has a recall ceiling around 0.61",
     "why": "BM25 over partition digests cannot bridge terminology gaps.",
     "views": ["topic/router", "subject/memory-machine"]},
    {"key": "router_digest", "type": "decision", "created": "2026-07-01",
     "summary": "Group digests keep routing stable when records change",
     "why": "Agents rewrite their digest each turn; the router reads that digest.",
     "views": ["topic/router", "subject/memory-machine"]},
    # benchmarks
    {"key": "bench_locomo", "type": "lesson", "created": "2026-07-10",
     "summary": "LoCoMo is conversational: agents beat dense retrieval there",
     "why": "Recall needs judgment over dialogue context, not just similarity.",
     "views": ["topic/benchmarks", "subject/memory-machine"]},
    {"key": "bench_longmemeval", "type": "lesson", "created": "2026-07-15",
     "summary": "On LongMemEval dense retrieval ties the agentic path",
     "why": "Questions are direct, so embeddings over sessions are enough.",
     "views": ["topic/benchmarks", "subject/memory-machine"]},
    {"key": "bench_judge", "type": "build", "created": "2026-08-02",
     "summary": "The answer-accuracy judge scored agents 0.27 and bm25 0.23 on LongMemEval",
     "why": "Evidence recall is much higher than answer accuracy; the gap is the next problem.",
     "views": ["topic/benchmarks", "subject/memory-machine"]},
    {"key": "bench_timeout", "type": "lesson", "created": "2026-08-04",
     "summary": "The full 500-question LongMemEval run timed out at 40 minutes",
     "why": "Local embedding models are slow on CPU; runs must be subsampled.",
     "views": ["topic/benchmarks", "subject/memory-machine"]},
    # views
    {"key": "views_foundation", "type": "decision", "created": "2026-09-05",
     "summary": "Views are projections over one canonical tape, never physical copies",
     "why": "Duplication would let provenance and status drift between copies.",
     "views": ["topic/views", "subject/memory-machine"]},
    {"key": "views_index", "type": "decision", "created": "2026-09-05",
     "summary": "The view index is rebuildable from the records' view tags",
     "why": "The tape stays the single source of truth.",
     "views": ["topic/views", "subject/memory-machine"]},
    {"key": "views_expand", "type": "decision", "created": "2026-09-06",
     "summary": "Structural views (time, type, source) are excluded from co-occurrence expansion",
     "why": "They co-occur with everything and would act as hubs.",
     "views": ["topic/views", "subject/memory-machine"]},
    # agents
    {"key": "agents_fused", "type": "decision", "created": "2026-08-20",
     "summary": "Each memory agent fuses digest, checklist and annotations in one call",
     "why": "Keeps the cost at one LLM call per partition per turn.",
     "views": ["topic/agents", "subject/memory-machine"]},
    {"key": "agents_budget", "type": "decision", "created": "2026-08-21",
     "summary": "Agent annotations are merged into the whiteboard under a char budget",
     "why": "Working memory must stay bounded.",
     "views": ["topic/agents", "subject/memory-machine"]},
    {"key": "agents_parallel", "type": "build", "created": "2026-08-22",
     "summary": "Memory agents run in parallel, one call per group",
     "why": "Fan-out is O(groups), so latency stays close to one call.",
     "views": ["topic/agents", "subject/memory-machine"]},
    # whiteboard
    {"key": "wb_bounded", "type": "decision", "created": "2026-08-28",
     "summary": "The whiteboard is bounded working memory, consolidated when too big",
     "why": "It represents the present, not the whole history.",
     "views": ["topic/whiteboard", "subject/memory-machine"]},
    {"key": "wb_cache", "type": "decision", "created": "2026-08-29",
     "summary": "Recall is cached by subject and invalidated when memories are added",
     "why": "Identical questions should not pay for agents twice.",
     "views": ["topic/whiteboard", "subject/memory-machine"]},
    {"key": "wb_metacognition", "type": "decision", "created": "2026-08-30",
     "summary": "The whiteboard carries understanding, checklist and pending items",
     "why": "Those fields are the metacognition the agents refine.",
     "views": ["topic/whiteboard", "subject/memory-machine"]},
    # adversarial: wrong or missing tags
    {"key": "adv_missing", "type": "decision", "created": "2026-06-25",
     "summary": "We reverted the router to opt-in after the first external benchmark",
     "why": "The decision predates the topic tags and was never retagged.",
     "views": ["subject/memory-machine"]},
    {"key": "adv_wrong", "type": "decision", "created": "2026-07-03",
     "summary": "Router top-k should stay at five partitions",
     "why": "More partitions cost calls without adding evidence.",
     "views": ["topic/pasta", "subject/cooking"]},
    {"key": "adv_terminology", "type": "lesson", "created": "2026-07-20",
     "summary": "Similarity-based partition selection misses memories whose wording differs",
     "why": "The terminology in the tape drifts away from the query wording.",
     "views": ["topic/retrieval", "subject/memory-machine"]},
    {"key": "adv_dual", "type": "decision", "created": "2026-09-07",
     "summary": "Views and benchmarks share one digest budget",
     "why": "View routing must not starve the benchmark evidence.",
     "views": ["topic/router", "topic/benchmarks", "subject/memory-machine"]},
    # other subjects
    {"key": "bread_ferment", "type": "preference", "created": "2026-04-02",
     "summary": "Sourdough needs a twelve-hour cold ferment",
     "why": "Flavor develops slowly in the fridge.",
     "views": ["topic/bread", "subject/cooking"]},
    {"key": "bread_hydration", "type": "preference", "created": "2026-04-03",
     "summary": "Bread hydration is seventy-five percent",
     "why": "Higher is harder to shape.",
     "views": ["topic/bread", "subject/cooking"]},
    {"key": "pasta_ratio", "type": "preference", "created": "2026-04-10",
     "summary": "Fresh pasta is one egg per hundred grams of flour",
     "why": "Classic ratio for a supple dough.",
     "views": ["topic/pasta", "subject/cooking"]},
    {"key": "pasta_salt", "type": "preference", "created": "2026-04-11",
     "summary": "Salt pasta water like the sea",
     "why": "The only chance to season the pasta itself.",
     "views": ["topic/pasta", "subject/cooking"]},
    {"key": "japan_kyoto", "type": "preference", "created": "2026-03-01",
     "summary": "Kyoto in November is crowded, book early",
     "why": "Autumn colors peak then.",
     "views": ["topic/japan", "subject/travel"]},
    {"key": "japan_railpass", "type": "preference", "created": "2026-03-02",
     "summary": "The JR Pass must be bought before arrival",
     "why": "The price rises sharply once in Japan.",
     "views": ["topic/japan", "subject/travel"]},
    {"key": "iceland_ring", "type": "preference", "created": "2026-03-20",
     "summary": "Iceland's Ring Road needs ten days",
     "why": "Rushing it misses the north.",
     "views": ["topic/iceland", "subject/travel"]},
    {"key": "iceland_4x4", "type": "preference", "created": "2026-03-21",
     "summary": "Rent a 4x4 for the Icelandic highlands",
     "why": "Ordinary cars are not allowed on F-roads.",
     "views": ["topic/iceland", "subject/travel"]},
    {"key": "riemann_siegel", "type": "lesson", "created": "2026-02-10",
     "summary": "Use mpmath siegelz for the Riemann-Siegel Z function",
     "why": "It is fast and accurate for moderate zeros.",
     "views": ["topic/riemann", "subject/math"]},
    {"key": "riemann_gmpy2", "type": "lesson", "created": "2026-02-11",
     "summary": "Verify the first zeros with gmpy2 at high precision",
     "why": "mpmath is not enough near the critical line.",
     "views": ["topic/riemann", "subject/math"]},
    {"key": "sieve_segmented", "type": "lesson", "created": "2026-02-20",
     "summary": "A segmented sieve beats sympy for large prime ranges",
     "why": "Memory stays bounded while iterating.",
     "views": ["topic/sieve", "subject/math"]},
]

# 24 tasks: ~30% single, ~25% same-view, ~25% cross-view, ~20% adversarial.
TASKS: list[dict[str, Any]] = [
    {"q": "why was the semantic router turned off?", "required": ["router_embed"], "cat": "single"},
    {"q": "what recall ceiling does lexical routing hit?", "required": ["router_lexical"], "cat": "single"},
    {"q": "how is the conversational benchmark different?", "required": ["bench_locomo"], "cat": "single"},
    {"q": "what did the answer-accuracy judge find?", "required": ["bench_judge"], "cat": "single"},
    {"q": "how are views stored relative to the tape?", "required": ["views_foundation"], "cat": "single"},
    {"q": "how do agents keep checklists fresh without extra calls?", "required": ["agents_fused"], "cat": "single"},
    {"q": "when is the whiteboard consolidated?", "required": ["wb_bounded"], "cat": "single"},
    {"q": "what are our routing defaults and their limits?",
     "required": ["router_llm", "router_lexical"], "cat": "same_view"},
    {"q": "summarize our benchmark findings so far",
     "required": ["bench_locomo", "bench_longmemeval", "bench_judge"], "cat": "same_view"},
    {"q": "what are the rules for views and expansion?",
     "required": ["views_foundation", "views_index", "views_expand"], "cat": "same_view"},
    {"q": "how do memory agents work?",
     "required": ["agents_fused", "agents_budget", "agents_parallel"], "cat": "same_view"},
    {"q": "what does the whiteboard hold and when does it shrink?",
     "required": ["wb_bounded", "wb_metacognition"], "cat": "same_view"},
    {"q": "what do we know about sourdough and hydration?",
     "required": ["bread_ferment", "bread_hydration"], "cat": "same_view"},
    {"q": "why did we change the routing strategy after the benchmarks?",
     "required": ["router_embed", "bench_locomo"], "cat": "cross_view"},
    {"q": "how do views interact with routing experiments?",
     "required": ["views_foundation", "router_lexical"], "cat": "cross_view"},
    {"q": "what limits the agentic memory path in practice?",
     "required": ["agents_budget", "bench_timeout"], "cat": "cross_view"},
    {"q": "how is the whiteboard kept stable across turns?",
     "required": ["wb_cache", "agents_fused"], "cat": "cross_view"},
    {"q": "what should we know before benchmarking retrieval again?",
     "required": ["bench_judge", "router_lexical"], "cat": "cross_view"},
    {"q": "how do views help keep the tape canonical?",
     "required": ["views_index", "views_expand"], "cat": "cross_view"},
    {"q": "why did we revert the router to opt-in after the first external benchmark?",
     "required": ["adv_missing"], "cat": "adversarial"},
    {"q": "why is router top-k fixed at five?", "required": ["adv_wrong"], "cat": "adversarial"},
    {"q": "what did we learn about the router's similarity mode?",
     "required": ["adv_terminology"], "cat": "adversarial"},
    {"q": "what did the last experiment show?", "required": ["bench_judge"],
     "cat": "adversarial", "context": "We are reviewing the memory machine's benchmark results."},
    {"q": "what changed between the first router decision and the recent benchmark?",
     "required": ["router_llm", "bench_judge"], "cat": "adversarial",
     "dims": ["semantic", "temporal"]},
    # dimension-specific tasks (temporal / structural / relational)
    {"q": "what changed about the router since July?",
     "required": ["router_digest", "adv_dual"], "cat": "temporal",
     "dims": ["semantic", "temporal"]},
    {"q": "what did we decide about views in September?",
     "required": ["views_foundation", "views_index"], "cat": "temporal",
     "dims": ["semantic", "temporal"]},
    {"q": "list the decisions made in May and June",
     "required": ["router_llm", "adv_missing"], "cat": "temporal",
     "dims": ["temporal", "structural"]},
    {"q": "which lessons did we learn in February?",
     "required": ["riemann_siegel", "riemann_gmpy2", "sieve_segmented"], "cat": "temporal",
     "dims": ["temporal", "structural"]},
    {"q": "which decisions did we make about routing?",
     "required": ["router_llm", "router_digest"], "cat": "structural",
     "dims": ["semantic", "structural"]},
    {"q": "which lessons did we record about benchmarks?",
     "required": ["bench_locomo", "bench_longmemeval", "bench_timeout"], "cat": "structural",
     "dims": ["semantic", "structural"]},
    {"q": "what did we work on in September?",
     "required": ["views_foundation", "views_index", "views_expand", "adv_dual"],
     "cat": "temporal", "dims": ["temporal"]},
    {"q": "what did we decide recently about routing?",
     "required": ["router_digest", "adv_dual"], "cat": "ambiguous",
     "dims": ["semantic", "temporal", "structural"]},
]

FILLER_TEMPLATES = [
    "Tidy the {t} notes",
    "Rename the {t} helper for clarity",
    "Add a test for the {t} edge case",
    "Bump the {t} dependency",
    "Document the {t} follow-up",
]

CATEGORIES = ["single", "same_view", "cross_view", "adversarial", "temporal", "structural", "ambiguous"]


class CountingClient:
    """Wraps an LLM client, counting calls and characters (tokens = chars / 4)."""

    def __init__(self, inner: Any):
        self.inner = inner
        self.calls = 0
        self.prompt_chars = 0
        self.completion_chars = 0

    def _count_prompt(self, messages: list[dict[str, str]]) -> None:
        self.calls += 1
        self.prompt_chars += sum(len(m.get("content") or "") for m in messages)

    def complete(self, messages, *, temperature=0.0):
        self._count_prompt(messages)
        out = self.inner.complete(messages, temperature=temperature)
        self.completion_chars += len(out or "")
        return out

    def complete_with_reasoning(self, messages, *, temperature=0.0):
        self._count_prompt(messages)
        content, reasoning = self.inner.complete_with_reasoning(messages, temperature=temperature)
        self.completion_chars += len(content or "") + len(reasoning or "")
        return content, reasoning

    def stream(self, messages, *, temperature=0.0):
        self._count_prompt(messages)
        return self.inner.stream(messages, temperature=temperature)

    def snapshot(self) -> tuple[int, int, int]:
        return self.calls, self.prompt_chars, self.completion_chars

    def since(self, snap: tuple[int, int, int]) -> tuple[int, int, int]:
        now = self.snapshot()
        return tuple(a - b for a, b in zip(now, snap))  # type: ignore[return-value]


def _topic_of(spec: dict[str, Any]) -> str:
    return next((v for v in spec["views"] if v.startswith("topic/")), "topic/misc")


def _subject_of(topic: str, specs: list[dict[str, Any]]) -> str:
    for s in specs:
        if topic in s["views"]:
            subject = next((v for v in s["views"] if v.startswith("subject/")), "")
            if subject:
                return subject
    return "subject/misc"


def filler_specs() -> list[dict[str, Any]]:
    topics = sorted({_topic_of(s) for s in MEMORIES})
    out: list[dict[str, Any]] = []
    for topic in topics:
        subject = _subject_of(topic, MEMORIES)
        name = topic.split("/", 1)[1]
        for i, template in enumerate(FILLER_TEMPLATES[:3]):
            out.append(
                {
                    "type": "lesson",
                    "summary": template.format(t=name),
                    "views": [topic, subject],
                    "_filler": True,
                    "created": f"2026-01-{(i % 28) + 1:02d}",
                }
            )
    return out


def _interleaved(specs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Round-robin by topic so chronological groups mix topics."""
    by_topic: dict[str, list[dict[str, Any]]] = {}
    for s in specs:
        by_topic.setdefault(_topic_of(s), []).append(s)
    out: list[dict[str, Any]] = []
    while any(by_topic.values()):
        for topic in list(by_topic):
            if by_topic[topic]:
                out.append(by_topic[topic].pop(0))
    return out


def build_machine(root: Path, cfg: Config, client: Any = None) -> tuple[Machine, dict[str, str]]:
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    m = Machine(root, config=cfg, client=client)
    id_map: dict[str, str] = {}
    for spec in _interleaved(MEMORIES + filler_specs()):
        rec = MemoryRecord(
            type=spec["type"],
            summary=spec["summary"],
            why=spec.get("why", ""),
            created_at=spec.get("created", ""),
            views=list(spec["views"]),
        )
        res = m.add_memory(rec, save=False)
        if spec.get("key"):
            id_map[spec["key"]] = res["record"]["id"]
    m.save()
    return m, id_map


def _target_views(spec: dict[str, Any]) -> set[str]:
    """The most specific conceptual region(s) of a memory: topic/ if tagged,
    otherwise subject/ (the adversarial missing-tag case)."""
    topics = {v for v in spec["views"] if v.startswith("topic/")}
    if topics:
        return topics
    return {v for v in spec["views"] if v.startswith("subject/")}


def run_arm(
    name: str,
    cfg: Config,
    root: Path,
    inner_client: Any,
    indexed_tasks: list[tuple[int, dict[str, Any]]],
    specs: dict[str, dict[str, Any]],
    *,
    oracle: bool = False,
    workers: int = 4,
    agent_workers: int = 8,
) -> list[dict[str, Any]]:
    """Run every task on its own copy of the fixture (questions are independent)."""
    template = root / "_template"
    template_m, id_map = build_machine(template, cfg)
    total = sum(1 for r in template_m.tape.read() if r.status == "active")

    def one(index_task: tuple[int, dict[str, Any]]) -> dict[str, Any]:
        index, task = index_task
        task_root = root / f"task_{index:02d}"
        if task_root.exists():
            shutil.rmtree(task_root)
        shutil.copytree(template, task_root)
        client = CountingClient(inner_client)
        m = Machine(task_root, config=cfg, client=client)

        required = {id_map[k] for k in task["required"]}
        per_memory_views = [_target_views(specs[k]) for k in task["required"]]
        target_views = set().union(*per_memory_views)

        m.whiteboard.annotations = []
        m._invalidate_recall_cache()
        m.whiteboard.context = [task["context"]] if task.get("context") else []

        snap = client.snapshot()
        start = time.monotonic()
        if oracle:
            res = m.recall(task["q"], views=sorted(target_views), debug=True, max_workers=agent_workers)
        else:
            res = m.recall(task["q"], debug=True, max_workers=agent_workers)
        latency = time.monotonic() - start
        calls, prompt_chars, completion_chars = client.since(snap)

        routing = res.get("routing") or {}
        selected = set(routing.get("selected_views") or [])
        consulted = set(routing.get("consulted_ids") or [])
        annotated = {a["memory_id"] for a in res.get("annotations") or []}
        view_hits = [1 if selected & views else 0 for views in per_memory_views]
        reasons = list(routing.get("fallback_reasons") or [])

        required_dims = set(task.get("dims") or ["semantic"])
        selected_dims = set(routing.get("dimensions") or [])
        missed = [
            key
            for key, views in zip(task["required"], per_memory_views)
            if not (selected & views)
        ]
        recovered = [key for key in missed if id_map[key] in consulted]
        level1 = set(routing.get("level1_ids") or [])

        row = {
            "arm": name,
            "cat": task["cat"],
            "q": task["q"],
            "view_recall": sum(view_hits) / len(view_hits),
            "view_precision": (len(selected & target_views) / len(selected)) if selected else 0.0,
            "dimension_recall": len(selected_dims & required_dims) / len(required_dims),
            "dimension_precision": (
                len(selected_dims & required_dims) / len(selected_dims) if selected_dims else 0.0
            ),
            "recovery_redundancy": (len(recovered) / len(missed)) if missed else 1.0,
            "evidence_recall": len(consulted & required) / len(required),
            "complete_evidence": int(required <= consulted),
            "agent_recall": len(annotated & required) / len(required),
            "complete_agent": int(required <= annotated),
            "reduction": 1.0 - (len(consulted) / total if total else 0.0),
            "expansion": len(consulted) / max(1, routing.get("records_level1") or len(consulted)),
            "level": routing.get("level", 0),
            "fallback": int(routing.get("level", 0) > 1),
            "reasons": reasons,
            "coverage_signal": routing.get("level1_coverage_signal") or routing.get("coverage_signal") or "",
            "level1_complete": int(required <= level1) if level1 else 0,
            "intersection_mode": routing.get("intersection_mode") or "",
            "calls": calls,
            "tokens": (prompt_chars + completion_chars) / 4,
            "latency": latency,
        }
        if not all(view_hits):
            row["attribution"] = "view_miss"
        elif not row["complete_evidence"]:
            row["attribution"] = "evidence_miss"
        elif not row["complete_agent"]:
            row["attribution"] = "agent_miss"
        else:
            row["attribution"] = ""
        return row

    # id_map is identical for every copy (same append order).
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        rows = list(pool.map(one, indexed_tasks))
    return rows


def _mean(rows: list[dict[str, Any]], key: str) -> float:
    return sum(r[key] for r in rows) / len(rows) if rows else 0.0


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    reasons: Counter[str] = Counter()
    modes: Counter[str] = Counter()
    for r in rows:
        for reason in r["reasons"]:
            reasons[reason] += 1
        if r.get("intersection_mode"):
            modes[r["intersection_mode"]] += 1
    signals = [r for r in rows if r.get("coverage_signal")]
    complete_signals = [r for r in signals if r["coverage_signal"] == "complete"]
    level1_incomplete = [r for r in signals if not r["level1_complete"]]
    level1_complete = [r for r in signals if r["level1_complete"]]
    calibration = {
        "n": len(signals),
        "coverage_confidence": _mean(complete_signals, "level1_complete"),
        "false_safe_rate": (
            sum(1 for r in level1_incomplete if r["coverage_signal"] == "complete")
            / len(level1_incomplete)
            if level1_incomplete
            else 0.0
        ),
        "fallback_waste": (
            sum(1 for r in level1_complete if r["coverage_signal"] != "complete")
            / len(level1_complete)
            if level1_complete
            else 0.0
        ),
    }
    return {
        "n": len(rows),
        "view_recall": _mean(rows, "view_recall"),
        "view_precision": _mean(rows, "view_precision"),
        "dimension_recall": _mean(rows, "dimension_recall"),
        "dimension_precision": _mean(rows, "dimension_precision"),
        "recovery_redundancy": _mean(rows, "recovery_redundancy"),
        "evidence_recall": _mean(rows, "evidence_recall"),
        "complete_evidence": _mean(rows, "complete_evidence"),
        "agent_recall": _mean(rows, "agent_recall"),
        "complete_agent": _mean(rows, "complete_agent"),
        "reduction": _mean(rows, "reduction"),
        "expansion": _mean(rows, "expansion"),
        "fallback": _mean(rows, "fallback"),
        "calls": _mean(rows, "calls"),
        "tokens": _mean(rows, "tokens"),
        "latency": _mean(rows, "latency"),
        "reasons": dict(reasons),
        "modes": dict(modes),
        "calibration": calibration,
        "attribution": dict(Counter(r["attribution"] for r in rows if r["attribution"])),
    }


ARM_CONFIGS: dict[str, Config] = {
    "full": Config(router_enabled=False),
    "similarity": Config(router_enabled=True, router_mode="llm", router_top_k=3),
    "view_bm25": Config(
        router_enabled=True, router_mode="views", view_router_mode="lexical", view_top_k=3
    ),
    "view_llm": Config(
        router_enabled=True, router_mode="views", view_router_mode="llm", view_top_k=3
    ),
    "view_oracle": Config(router_enabled=False),
    "cascade_bm25": Config(
        router_enabled=True, router_mode="cascade", view_router_mode="lexical",
        view_top_k=3, cascade_min_score=0.0,
    ),
    "cascade_llm": Config(
        router_enabled=True, router_mode="cascade", view_router_mode="llm",
        view_top_k=3, cascade_min_score=0.5,
    ),
    "view_bm25_dim": Config(
        router_enabled=True, router_mode="views", view_router_mode="lexical",
        view_dimension_mode="auto", view_top_k=3, coverage_mode="both",
    ),
    "view_bm25_dim_struct": Config(
        router_enabled=True, router_mode="views", view_router_mode="lexical",
        view_dimension_mode="auto", view_top_k=3, coverage_mode="structural",
    ),
    "view_llm_dim": Config(
        router_enabled=True, router_mode="views", view_router_mode="llm",
        view_dimension_mode="auto", view_top_k=3, coverage_mode="both",
    ),
    "cascade_bm25_dim": Config(
        router_enabled=True, router_mode="cascade", view_router_mode="lexical",
        view_dimension_mode="auto", view_top_k=3, coverage_mode="both",
    ),
    "cascade_llm_dim": Config(
        router_enabled=True, router_mode="cascade", view_router_mode="llm",
        view_dimension_mode="auto", view_top_k=3, coverage_mode="both",
    ),
    "view_bm25_dim_judge": Config(
        router_enabled=True, router_mode="views", view_router_mode="lexical",
        view_dimension_mode="auto", view_top_k=3, coverage_mode="judge",
    ),
    "cascade_bm25_dim_judge": Config(
        router_enabled=True, router_mode="cascade", view_router_mode="lexical",
        view_dimension_mode="auto", view_top_k=3, coverage_mode="judge",
    ),
    "view_bm25_dim_vcov": Config(
        router_enabled=True, router_mode="views", view_router_mode="lexical",
        view_dimension_mode="auto", view_top_k=3, coverage_mode="views",
    ),
    "cascade_bm25_dim_vcov": Config(
        router_enabled=True, router_mode="cascade", view_router_mode="lexical",
        view_dimension_mode="auto", view_top_k=3, coverage_mode="views",
    ),
    "view_bm25_dim_judge2": Config(
        router_enabled=True, router_mode="views", view_router_mode="lexical",
        view_dimension_mode="auto", view_top_k=3, coverage_mode="judge_views",
    ),
    "cascade_bm25_dim_judge2": Config(
        router_enabled=True, router_mode="cascade", view_router_mode="lexical",
        view_dimension_mode="auto", view_top_k=3, coverage_mode="judge_views",
    ),
    "view_llm_prune": Config(
        router_enabled=True, router_mode="views", view_router_mode="llm",
        view_top_k=5, view_prune="subject",
    ),
    "cascade_llm_prune_judge2": Config(
        router_enabled=True, router_mode="cascade", view_router_mode="llm",
        view_top_k=5, view_prune="subject", coverage_mode="judge_views",
    ),
}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", default="/tmp/mm-view-bench")
    p.add_argument("--arms", default="full,similarity,view_bm25,view_llm,view_oracle,cascade_bm25,cascade_llm,view_bm25_dim,view_llm_dim,cascade_bm25_dim,cascade_llm_dim")
    p.add_argument("--limit", type=int, default=0, help="0 = all tasks")
    p.add_argument("--indices", default="", help="comma-separated task indices to run (preserves dir names)")
    p.add_argument("--capacity", type=int, default=5)
    p.add_argument("--model", default="deepseek-v4-flash")
    p.add_argument("--api-key", default="")
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--workers", type=int, default=4, help="tasks run in parallel per arm")
    p.add_argument("--agent-workers", type=int, default=8, help="agents run in parallel per task")
    p.add_argument("--timeout", type=int, default=120, help="LLM request timeout (seconds)")
    p.add_argument("--out", default="", help="write raw per-task rows to this JSON file")
    p.add_argument("--keep", action="store_true")
    args = p.parse_args()

    import json
    import os

    api_key = args.api_key or os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key:
        raise SystemExit("set DEEPSEEK_API_KEY (or --api-key)")

    selected = {a.strip() for a in args.arms.split(",") if a.strip()}
    indexed = list(enumerate(TASKS))
    if args.indices:
        want = {int(x) for x in args.indices.split(",") if x.strip()}
        indexed = [(i, t) for i, t in indexed if i in want]
    elif args.limit > 0:
        sampled = random.Random(args.seed).sample(TASKS, min(args.limit, len(TASKS)))
        keep = {id(t) for t in sampled}
        indexed = [(i, t) for i, t in indexed if id(t) in keep]
    tasks = [t for _i, t in indexed]
    specs = {s["key"]: s for s in MEMORIES if s.get("key")}

    root = Path(args.root).expanduser().resolve()
    base = LLMClient(
        "https://api.deepseek.com", api_key, args.model,
        timeout=args.timeout, retries=1, backoff=0.5,
    )

    all_rows: dict[str, list[dict[str, Any]]] = {}

    def dump_partial() -> None:
        if not args.out:
            return
        Path(args.out).write_text(
            json.dumps(
                {"tasks": tasks, "arms": all_rows},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    for name, cfg in ARM_CONFIGS.items():
        if name not in selected:
            continue
        cfg = Config(**{**cfg.to_dict(), "capacity": args.capacity})
        arm_root = root / name
        print(f"running {name} ...", flush=True)
        all_rows[name] = run_arm(
            name, cfg, arm_root, base, indexed, specs,
            oracle=(name == "view_oracle"),
            workers=args.workers, agent_workers=args.agent_workers,
        )
        dump_partial()

    print(f"\nfixture: {len(MEMORIES) + len(filler_specs())} memories | "
          f"tasks: {len(tasks)} | capacity: {args.capacity}\n")
    header = (
        f"{'arm':<16} {'n':>3} {'vrec':>6} {'vprec':>6} {'drec':>6} {'dprec':>6} "
        f"{'recov':>6} {'erec':>6} {'ecomp':>6} {'arec':>6} {'acomp':>6} "
        f"{'reduce':>7} {'exp':>5} {'fall':>5} {'calls':>6} {'tok/q':>7} {'lat':>6}"
    )
    print(header)
    print("-" * len(header))
    for name, rows in all_rows.items():
        s = summarize(rows)
        print(
            f"{name:<16} {s['n']:>3} {s['view_recall']:>6.2f} {s['view_precision']:>6.2f} "
            f"{s['dimension_recall']:>6.2f} {s['dimension_precision']:>6.2f} "
            f"{s['recovery_redundancy']:>6.2f} {s['evidence_recall']:>6.2f} "
            f"{s['complete_evidence']:>6.2f} {s['agent_recall']:>6.2f} "
            f"{s['complete_agent']:>6.2f} {s['reduction']:>7.2f} {s['expansion']:>5.2f} "
            f"{s['fallback']:>5.2f} {s['calls']:>6.1f} {s['tokens']:>7.0f} {s['latency']:>6.1f}"
        )

    print("\ncoverage calibration (level 1):")
    for name, rows in all_rows.items():
        s = summarize(rows)["calibration"]
        if s["n"]:
            print(
                f"  {name:<16} n={s['n']:<3} P(complete|signal=complete)={s['coverage_confidence']:.2f} "
                f"false_safe={s['false_safe_rate']:.2f} fallback_waste={s['fallback_waste']:.2f}"
            )

    print("\nintersection modes:")
    for name, rows in all_rows.items():
        s = summarize(rows)["modes"]
        if s:
            print(f"  {name:<16} {s}")

    print("\nby category (view recall / complete evidence / agent recall):")
    for name, rows in all_rows.items():
        for cat in CATEGORIES:
            sub = [r for r in rows if r["cat"] == cat]
            if not sub:
                continue
            s = summarize(sub)
            print(
                f"  {name:<14} {cat:<12} n={s['n']:<3} "
                f"vrec={s['view_recall']:.2f} ecomp={s['complete_evidence']:.2f} "
                f"arec={s['agent_recall']:.2f} calls={s['calls']:.1f}"
            )

    print("\nfallback reasons (cascade arms):")
    for name in ("cascade_bm25", "cascade_llm"):
        if name in all_rows:
            s = summarize(all_rows[name])
            print(f"  {name}: {s['reasons']}")

    print("\nfailure attribution (view_miss / evidence_miss / agent_miss):")
    for name, rows in all_rows.items():
        s = summarize(rows)
        print(f"  {name}: {s['attribution']}")

    if args.out:
        Path(args.out).write_text(
            json.dumps(
                {"tasks": tasks, "arms": {k: v for k, v in all_rows.items()}},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"\nraw rows written to {args.out}")

    if not args.keep and root.exists():
        shutil.rmtree(root)


if __name__ == "__main__":
    main()
