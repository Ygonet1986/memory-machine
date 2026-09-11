"""Attention conversation benchmark: anaphora vs perseveration.

Runs two conversations on the same machine and compares attention off vs prior:

  S1 anaphora     router question -> "e por que mudamos isso?" -> change ->
                  "e o benchmark?"
  S2 topic shift  views question -> views follow-up -> sourdough (shift) ->
                  "e a hidratacao?" (anaphora inside the new topic)

Metrics per turn: complete evidence, agent recall, calls, churn (Jaccard with
the previous turn's selection), attention contribution; for shift turns, the
residual attention on the old topic (over-persistence) and whether the new
topic was covered (recovery).

Run:  PYTHONPATH=src python3 eval/conversation_bench.py
"""

from __future__ import annotations

import argparse
import shutil
import tempfile
from pathlib import Path
from typing import Any

from memory_machine.config import Config
from memory_machine.llm import LLMClient

from view_router_bench import CountingClient, build_machine

CONVERSATIONS: list[dict[str, Any]] = [
    {
        "name": "anaphora",
        "turns": [
            {"q": "why was the embedding router disabled?", "required": ["router_embed"]},
            {"q": "e por que mudamos isso?", "required": ["router_embed"], "anaphora": True},
            {"q": "what changed about the router since July?",
             "required": ["router_digest", "adv_dual"]},
            {"q": "e o benchmark?", "required": ["bench_judge"], "anaphora": True},
        ],
    },
    {
        "name": "topic_shift",
        "turns": [
            {"q": "what are the rules for views and expansion?",
             "required": ["views_foundation", "views_index", "views_expand"]},
            {"q": "how do views help keep the tape canonical?",
             "required": ["views_index", "views_expand"]},
            {"q": "what do we know about sourdough and hydration?",
             "required": ["bread_ferment", "bread_hydration"], "shift": True},
            {"q": "e a hidratacao?", "required": ["bread_hydration"], "anaphora": True},
        ],
    },
]


def jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b)


def run_conversation(
    arm: str,
    conversation: dict[str, Any],
    cfg: Config,
    root: Path,
    client: CountingClient,
    id_map: dict[str, str],
) -> list[dict[str, Any]]:
    machine, _ = build_machine(root, cfg, client)
    rows: list[dict[str, Any]] = []
    previous: set[str] = set()
    for turn, spec in enumerate(conversation["turns"], start=1):
        machine._invalidate_recall_cache()
        before = client.calls
        old_attention = dict(machine.whiteboard.attention)
        res = machine.recall(spec["q"], debug=True)
        calls = client.calls - before
        routing = res.get("routing") or {}
        selected = set(routing.get("selected_views") or [])
        consulted = set(routing.get("consulted_ids") or [])
        annotated = {a["memory_id"] for a in res.get("annotations") or []}
        required = {id_map[k] for k in spec["required"]}
        attention = res.get("attention") or {}
        old_top = max(old_attention, key=old_attention.get) if old_attention else ""
        rows.append(
            {
                "arm": arm,
                "conversation": conversation["name"],
                "turn": turn,
                "q": spec["q"],
                "anaphora": bool(spec.get("anaphora")),
                "shift": bool(spec.get("shift")),
                "complete_evidence": int(required <= consulted),
                "agent_recall": len(annotated & required) / len(required),
                "calls": calls,
                "churn": jaccard(previous, selected),
                "contribution": res.get("attention_contribution") or {},
                "old_topic_residual": attention.get(old_top, 0.0) if old_top else 0.0,
                "attention_top": max(attention.values()) if attention else 0.0,
            }
        )
        previous = selected
    return rows


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--model", default="deepseek-v4-flash")
    p.add_argument("--api-key", default="")
    p.add_argument("--arms", default="off,prior")
    p.add_argument("--keep", action="store_true")
    args = p.parse_args()

    import os

    api_key = args.api_key or os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key:
        raise SystemExit("set DEEPSEEK_API_KEY (or --api-key)")

    base = CountingClient(
        LLMClient("https://api.deepseek.com", api_key, args.model, retries=1, backoff=0.5)
    )
    root = Path(tempfile.mkdtemp(prefix="mm-conversation-"))
    fixture_cfg = Config(capacity=5)
    _machine, id_map = build_machine(root / "_fixture", fixture_cfg)
    arms = {
        "off": ("lexical", "off"),
        "prior": ("lexical", "prior"),
        "state": ("lexical", "state"),
        "llm": ("llm", "off"),
        "llm_state": ("llm", "state"),
    }

    all_rows: list[dict[str, Any]] = []
    for arm in [a.strip() for a in args.arms.split(",") if a.strip()]:
        router_mode, attention_mode = arms[arm]
        cfg = Config(
            capacity=5,
            router_enabled=True,
            router_mode="views",
            view_router_mode=router_mode,
            view_dimension_mode="auto",
            agent_mode="view",
            view_top_k=3,
            attention_mode=attention_mode,
        )
        for conversation in CONVERSATIONS:
            print(f"running {arm} / {conversation['name']} ...", flush=True)
            all_rows.extend(
                run_conversation(
                    arm,
                    conversation,
                    cfg,
                    root / f"{arm}_{conversation['name']}",
                    base,
                    id_map,
                )
            )

    print(f"\n{'arm':<6} {'conversation':<12} {'turn':>4} {'kind':<9} {'ecomp':>6} "
          f"{'arec':>6} {'calls':>6} {'churn':>6} {'attn_top':>8} {'old_res':>8}")
    for r in all_rows:
        kind = "shift" if r["shift"] else ("anaphora" if r["anaphora"] else "normal")
        print(
            f"{r['arm']:<6} {r['conversation']:<12} {r['turn']:>4} {kind:<9} "
            f"{r['complete_evidence']:>6} {r['agent_recall']:>6.2f} {r['calls']:>6.1f} "
            f"{r['churn']:>6.2f} {r['attention_top']:>8.2f} {r['old_topic_residual']:>8.2f}"
        )

    print("\nsummary:")
    for arm in [a.strip() for a in args.arms.split(",") if a.strip()]:
        rows = [r for r in all_rows if r["arm"] == arm]
        anaph = [r for r in rows if r["anaphora"]]
        shifts = [r for r in rows if r["shift"]]
        print(
            f"  {arm:<6} anaphora_ecomp={sum(r['complete_evidence'] for r in anaph)/max(1,len(anaph)):.2f} "
            f"anaphora_calls={sum(r['calls'] for r in anaph)/max(1,len(anaph)):.1f} "
            f"shift_ecomp={sum(r['complete_evidence'] for r in shifts)/max(1,len(shifts)):.2f} "
            f"shift_old_residual={sum(r['old_topic_residual'] for r in shifts)/max(1,len(shifts)):.2f}"
        )

    if not args.keep:
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    main()
