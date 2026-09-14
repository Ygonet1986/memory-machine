"""P0: judged replay with SHARED agent annotations.

The v2 five-arm replay was confounded: every arm re-ran the LLM agents, so a
difference between arms could come from agent variance instead of graph
admission. Here the agents run ONCE per case (mode off) and their annotations
are frozen; each variant differs only by the graph evidence admitted
computed deterministically from the preserved graph. The gate
``agent_added == []`` proves the shared-agent isolation.

Run:
  PYTHONPATH=src:.:eval python3 eval/graph_replay_shared.py \
      --reuse-root <LME12-root> --api-key ...
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "src"))

from memory_machine.config import Config  # noqa: E402
from memory_machine.coordinator import Machine  # noqa: E402
from memory_machine.graph import GraphStore  # noqa: E402
from memory_machine.graph_recall import GraphRecall, guard_evidence  # noqa: E402
from memory_machine.llm import LLMClient  # noqa: E402
from memory_machine.payload import build_evidence_payload, payload_as_context  # noqa: E402
from memory_machine.tape import Tape  # noqa: E402
from memory_machine.whiteboard import Annotation, merge_annotations  # noqa: E402

from e2e_bench import VIEW_CONFIG, answer_with, judge  # noqa: E402
from graph_bench import (  # noqa: E402
    ARM_FLAGS,
    GRAPH_EXTRACT_TYPES,
    retrieval_metrics,
    sha256,
)
from view_router_bench import CountingClient  # noqa: E402

DEFAULT_ROOT = Path(
    "/var/folders/3z/9n8mh2p12ld771wy19z5v7rw0000gn/T/mm-graph-t5w86fv7"
)
OUT_DIR = HERE / "graph_out"
VARIANTS = [
    "graph_off",
    "graph_augment",
    "graph_augment_guarded",
    "graph_augment_precise",
    "graph_augment_gated",
]


def copy_case(source: Path, dest: Path) -> None:
    """Copy only the frozen inputs: tape, manifest and the graph projection.

    Copying the whole arm directory would carry a stale whiteboard.json and
    inflate the agent recall with annotations from a previous run.
    """
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source / "tape.jsonl", dest / "tape.jsonl")
    if (source / "manifest.json").exists():
        shutil.copy2(source / "manifest.json", dest / "manifest.json")
    if (dest / "graph").exists():
        shutil.rmtree(dest / "graph")
    shutil.copytree(source / "graph", dest / "graph")


def variant_config(variant: str) -> Config:
    mode = {
        "graph_off": "off",
        "graph_augment": "augment",
        "graph_augment_guarded": "augment_guarded",
        "graph_augment_precise": "augment_guarded",
        "graph_augment_gated": "augment_guarded",
    }[variant]
    cfg = Config(
        **VIEW_CONFIG,
        evidence_payload="budgeted",
        evidence_payload_budget=4000,
        graph_enabled=True,
        graph_recall_mode=mode,
        graph_extract_types=GRAPH_EXTRACT_TYPES,
    )
    for flag, value in ARM_FLAGS.get(variant, {}).items():
        setattr(cfg, flag, value)
    if variant == "graph_augment_gated":
        # R3 recipe + the optional question veto (P2 calibration)
        cfg.graph_augment_hub_degree = 20
        cfg.graph_augment_min_score = 0.80
        cfg.graph_augment_max_items = 3
        cfg.graph_augment_question_gate = True
    return cfg


def variant_evidence(case_dir: Path, cfg: Config, question: str) -> list[Any]:
    store = GraphStore(case_dir / "graph")
    recall = GraphRecall(
        store.index(),
        embedder=None,
        depth=cfg.graph_depth,
        top_k=cfg.graph_top_k,
        hub_degree=cfg.graph_hub_degree,
    )
    result = recall.recall(question)
    if cfg.graph_recall_mode == "augment_guarded":
        result.evidence = guard_evidence(
            result.evidence,
            min_score=cfg.graph_augment_min_score,
            max_items=cfg.graph_augment_max_items,
        )
        if cfg.graph_augment_question_gate:
            from memory_machine.graph_recall import question_gate

            records = {record.id: record for record in Tape(case_dir / "tape.jsonl").read()}
            result.evidence = question_gate(
                result.evidence,
                records,
                question,
                min_cov=cfg.graph_augment_question_min_cov,
            )
        result.paths_selected = sum(len(item.paths) for item in result.evidence)
    return result.evidence


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reuse-root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--model", default="deepseek-v4-flash")
    parser.add_argument("--judge-model", default="deepseek-v4-flash")
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--snapshot", default="graph_bench_longmemeval.jsonl")
    parser.add_argument("--out-suffix", default="longmemeval")
    parser.add_argument(
        "--source-arm",
        default="graph_augment",
        help="arm directory in --reuse-root that holds tape+graph (graph_only builds use graph_only)",
    )
    parser.add_argument("--api-key", default="")
    args = parser.parse_args()
    api_key = args.api_key or os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key:
        raise SystemExit("set DEEPSEEK_API_KEY (or --api-key)")

    from external_bench import DATA, load_longmemeval

    tasks = load_longmemeval(DATA / "longmemeval_s_cleaned.json", 0, 7)
    by_question = {task["question"]: task for task in tasks}
    snapshot = [
        json.loads(line)
        for line in (OUT_DIR / args.snapshot).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if args.limit:
        snapshot = snapshot[: args.limit]

    agent_client = CountingClient(
        LLMClient("https://api.deepseek.com", api_key, args.model, timeout=args.timeout, retries=1, backoff=0.5)
    )
    judge_client = CountingClient(
        LLMClient("https://api.deepseek.com", api_key, args.judge_model, timeout=args.timeout, retries=1, backoff=0.5)
    )
    root = Path(tempfile.mkdtemp(prefix="mm-graph-shared-"))
    rows: list[dict[str, Any]] = []

    for case in snapshot:
        index = case["case"]
        task = by_question.get(case["question"], {})
        question_date = task.get("question_date", "")
        provenance = f"\n\n(Question asked on {question_date}.)" if question_date else ""
        required = list(case["required_ids"])
        gold = case["gold"]

        base = root / f"case_{index:02d}"
        source = args.reuse_root / f"case_{index:02d}" / args.source_arm
        copy_case(source, base)

        # ---- one agent recall per case, frozen for every variant
        off_cfg = variant_config("graph_off")
        agent_dir = root / f"case_{index:02d}_agent"
        copy_case(source, agent_dir)
        agent_machine = Machine(agent_dir, config=off_cfg, client=agent_client)
        agent_machine._invalidate_recall_cache()
        agent_result = agent_machine.recall(case["question"], debug=True)
        agent_annotations = [
            Annotation(
                memory_id=item["memory_id"],
                note=item.get("note", ""),
                relevance=float(item.get("relevance") or 0.0),
                agent_id=item.get("agent_id", ""),
            )
            for item in agent_result.get("annotations") or []
        ]
        agent_ids = {item.memory_id for item in agent_annotations}
        tape = Tape(base / "tape.jsonl")
        records = {record.id: record for record in tape.read()}
        active = {record.id for record in tape.read() if record.status == "active"}

        arm_rows: dict[str, Any] = {}
        graph_only_by_arm: dict[str, list[str]] = {}
        agent_recall_calls = agent_client.calls
        for variant in VARIANTS:
            calls_before_variant = agent_client.calls
            cfg = variant_config(variant)
            evidence = (
                variant_evidence(base, cfg, case["question"])
                if variant != "graph_off"
                else []
            )
            graph_annotations: list[Annotation] = []
            for item in evidence:
                if item.memory_id not in active:
                    continue
                weight = cfg.graph_augment_weight if cfg.graph_recall_mode == "augment_guarded" else 1.0
                graph_annotations.append(
                    Annotation(
                        memory_id=item.memory_id,
                        note=item.label or "graph evidence",
                        relevance=max(0.05, float(item.score) * max(0.0, weight)),
                        agent_id="graph",
                    )
                )
            merged: list[Annotation] = list(agent_annotations)
            by_id = {a.memory_id: a for a in merged}
            for item in graph_annotations:
                current = by_id.get(item.memory_id)
                if current is None:
                    by_id[item.memory_id] = item
                elif item.relevance > current.relevance:
                    by_id[item.memory_id] = Annotation(
                        memory_id=current.memory_id,
                        note=current.note or item.note,
                        relevance=item.relevance,
                        agent_id=current.agent_id or item.agent_id,
                    )
            union = list(by_id.values())

            answer_dir = root / f"case_{index:02d}_{variant}"
            copy_case(source, answer_dir)
            machine = Machine(answer_dir, config=cfg, client=agent_client)
            machine.whiteboard.annotations = []
            machine.whiteboard.subject = case["question"]
            kept = merge_annotations(
                machine.whiteboard, union, budget=cfg.whiteboard_budget
            )
            payload = build_evidence_payload(
                records,
                kept,
                budget=cfg.evidence_payload_budget,
                min_item_chars=cfg.evidence_payload_min_item,
            )
            context = payload_as_context(payload)
            # Shared-agent gate: building the graph evidence, the union and
            # the payload is pure local work, so the client must not have been
            # called since this variant started (the answerer call comes next).
            assert agent_client.calls == calls_before_variant, (
                f"case {index} {variant}: union/payload called the LLM"
            )
            answer = answer_with(
                agent_client, machine, case["question"] + provenance, extra_context=context
            )
            verdict, reason = judge(judge_client, case["question"], gold, answer)

            annotated = {item.memory_id for item in kept}
            agent_added = sorted(annotated - agent_ids)
            graph_ids = [item.memory_id for item in evidence]
            graph_only_by_arm[variant] = sorted(set(graph_ids) - agent_ids)
            arm_rows[variant] = {
                "annotations": sorted(annotated),
                "agent_added": agent_added,
                "graph_added": sorted(set(graph_ids) - agent_ids),
                "graph_ids": graph_ids,
                "graph_evidence": [item.to_dict() for item in evidence],
                "graph_metrics": {
                    "graph_seed_entities": 0,
                    "graph_unique_memories": len(evidence),
                    "graph_only_memories": len(set(graph_ids) - agent_ids),
                },
                "payload_ids": [item["memory_id"] for item in payload],
                "payload_chars": sum(item["used_chars"] for item in payload),
                "answer": answer,
                "verdict": verdict,
                "reason": reason[:300],
                "evidence_complete": int(set(required) <= annotated),
            }

        # Shared-agent gate: the agent recall ran once, the off arm is a
        # subset of the frozen agent set, and the answerer calls are the only
        # LLM calls made by the variants.
        assert set(arm_rows["graph_off"]["annotations"]) <= agent_ids, (
            f"case {index}: off arm contains non-agent annotations"
        )

        retrieval_by_arm = {
            variant: retrieval_metrics(
                required,
                sorted(agent_ids),
                arm_rows[variant]["annotations"],
                graph_only_by_arm[variant],
            )
            for variant in VARIANTS
        }
        row = {
            "case": index,
            "cat": case["cat"],
            "question": case["question"],
            "gold": gold,
            "required_ids": required,
            "strata": case["strata"],
            "ingestion": case["ingestion"],
            "graph": case["graph"],
            "shared_agents": True,
            "agent_ids": sorted(agent_ids),
            "agent_recall_calls": agent_recall_calls,
            "retrieval": retrieval_metrics(
                required,
                sorted(agent_ids),
                arm_rows["graph_augment"]["annotations"],
                graph_only_by_arm["graph_augment"],
            ),
            "retrieval_by_arm": retrieval_by_arm,
            "arms": arm_rows,
            "cost": case["cost"],
        }
        rows.append(row)
        path = OUT_DIR / f"graph_bench_{args.out_suffix}.jsonl"
        with path.open("w", encoding="utf-8") as handle:
            for item in rows:
                handle.write(json.dumps(item, ensure_ascii=False) + "\n")
        print(
            f"case {index}: agents={len(agent_ids)} "
            + " ".join(
                f"{v.replace('graph_', '')}={arm_rows[v]['verdict'][:3]}"
                for v in VARIANTS
            ),
            flush=True,
        )

    manifest = {
        "run_id": datetime.now(timezone.utc).strftime("%Y-%m-%d-shared-%H%M%S"),
        "dataset": "longmemeval",
        "shared_agents": True,
        "variants": VARIANTS,
        "model": args.model,
        "judge_model": args.judge_model,
        "reuse_root": str(args.reuse_root),
        "git_commit": subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=HERE.parent, text=True
        ).strip(),
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    (OUT_DIR / f"run_manifest_graph_{args.out_suffix}.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    checksums = OUT_DIR / "CHECKSUMS_graph.txt"
    lines = []
    for file in sorted(OUT_DIR.rglob("*")):
        if file.is_file() and file.name != checksums.name:
            lines.append(f"{sha256(file)}  {file.relative_to(OUT_DIR.parent.parent)}")
    checksums.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("\nshared-agent replay done:")
    for variant in VARIANTS:
        verdicts = [row["arms"][variant]["verdict"] for row in rows]
        strict = sum(1 for v in verdicts if v == "correct") / len(verdicts)
        print(f"  {variant:<24} strict={strict:.3f}")
    print(f"root: {root}")


if __name__ == "__main__":
    main()
