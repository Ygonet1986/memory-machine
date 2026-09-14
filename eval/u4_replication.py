"""U4.2 replication — how much do verdicts oscillate with identical contexts.

Pre-registered design (no post-hoc changes):
  arms        precise + i5_single over the 30 U3 cases (blocks a+b)
  flips       N=5 on both arms of every case that flipped between the two arms
  N           default 3 for the 30-case sweep; 5 for the flip cases
  fidelity    the rebuilt delivered context must equal the frozen snapshot
              context byte-for-byte (sha256 checked) or the run aborts
  metrics     per arm per case: verdict distribution, modal verdict,
              within-arm flip rate (identical-context oscillation);
              ledger recomputed with modal verdicts.

Run: PYTHONPATH=src:.:eval python3 eval/u4_replication.py --api-key ...
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "src"))

from memory_machine.coordinator import Machine  # noqa: E402
from memory_machine.llm import LLMClient  # noqa: E402
from memory_machine.payload import build_evidence_payload, payload_as_context  # noqa: E402
from memory_machine.tape import Tape  # noqa: E402
from memory_machine.whiteboard import Annotation, merge_annotations  # noqa: E402

from e2e_bench import answer_with, judge  # noqa: E402
from external_bench import DATA, load_longmemeval  # noqa: E402
from graph_replay_shared import copy_case, variant_config, variant_evidence  # noqa: E402
from graph_util_diag import frozen_agent_annotations, windowed_body  # noqa: E402
from view_router_bench import CountingClient  # noqa: E402

from memory_machine.graph import GraphStore  # noqa: E402
from memory_machine.graph_recall import GraphRecall, guard_evidence, question_gate  # noqa: E402


def arm_evidence(base: Path, cfg: Any, question: str, mode: str) -> list[Any]:
    """Exact recall path of each producer: analyze_arm for precise, run_u2 for i5."""
    if mode != "precise":
        return variant_evidence(base, cfg, question)
    store = GraphStore(base / "graph")
    hub = cfg.graph_hub_degree
    if not hub and cfg.graph_recall_mode == "augment_guarded":
        hub = cfg.graph_augment_hub_degree
    recall = GraphRecall(store.index(), depth=cfg.graph_depth, top_k=cfg.graph_top_k, hub_degree=hub)
    evidence = recall.recall(question).evidence
    evidence = guard_evidence(
        evidence,
        min_score=cfg.graph_augment_min_score,
        max_items=cfg.graph_augment_max_items,
    )
    if cfg.graph_augment_question_gate:
        records = {record.id: record for record in Tape(base / "tape.jsonl").read()}
        evidence = question_gate(
            evidence, records, question, min_cov=cfg.graph_augment_question_min_cov
        )
    return evidence

OUT_DIR = HERE / "graph_out"
TMP = Path("/var/folders/3z/9n8mh2p12ld771wy19z5v7rw0000gn/T")
SLICES = {
    "longmemeval_u3a": {
        "snapshot": "u_diag_longmemeval_u3a.jsonl",
        "root": TMP / "mm-graph-shared-wnps8c6d",
    },
    "longmemeval_u3b": {
        "snapshot": "u_diag_longmemeval_u3b.jsonl",
        "root": TMP / "mm-graph-shared-7ggare_r",
    },
}
U3_ARMS = ["graph_augment_precise", "i5_single"]
U3_N = 3
FLIP_CASES = {
    "longmemeval_u3a": [20, 22, 26],
    "longmemeval_u3b": [38, 41],
}
FLIP_N = 5


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def mode_of(arm: str) -> str:
    return {
        "graph_augment_precise": "precise",
        "i5_fact_window": "i5",
        "i5_single": "i5_single",
    }[arm]


def base_payload(records: dict[str, Any], kept: list[Any], cfg: Any, question: str, mode: str):
    if mode == "i5":
        return build_evidence_payload(
            records, kept, budget=cfg.evidence_payload_budget,
            min_item_chars=cfg.evidence_payload_min_item,
            question=question, window=True,
        )
    payload = build_evidence_payload(
        records, kept, budget=cfg.evidence_payload_budget,
        min_item_chars=cfg.evidence_payload_min_item,
    )
    if mode != "i5_single":
        return payload
    out = []
    for item in payload:
        entry = dict(item)
        record = records.get(item["memory_id"])
        if record is not None and item["truncated"]:
            header = item["evidence"].split("\n", 1)[0]
            summary = record.summary or ""
            room = item["used_chars"] - len(header) - 1
            if summary:
                room -= len(summary) + 1
            body = windowed_body(record, question, max(0, room), mode)
            if body:
                entry["evidence"] = (
                    f"{header}\n{summary}\n{body}" if summary else f"{header}\n{body}"
                )
        out.append(entry)
    return out


def rebuild_delivery(
    root: Path,
    row: dict[str, Any],
    arm: str,
    question_date: str,
    work_root: Path,
) -> tuple[str, Machine]:
    mode = mode_of(arm)
    cfg = variant_config("graph_augment_precise")
    base = root / f"case_{row['case']:02d}"
    records = {r.id: r for r in Tape(base / "tape.jsonl").read()}
    question = row["question"]
    evidence = arm_evidence(base, cfg, question, mode)
    active = {r.id for r in records.values() if r.status == "active"}
    graph_annotations = [
        Annotation(
            memory_id=item.memory_id,
            note=item.label or "graph evidence",
            relevance=max(0.05, float(item.score)),
            agent_id="graph",
        )
        for item in evidence
        if item.memory_id in active
    ]
    agent_annotations = frozen_agent_annotations({"root": root, "case": row["case"], "row": row})
    by_id = {a.memory_id: a for a in agent_annotations}
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

    work_dir = work_root / f"case_{row['case']:02d}_{arm}"
    copy_case(base, work_dir)
    machine = Machine(work_dir, config=cfg, client=None)
    machine.whiteboard.annotations = []
    machine.whiteboard.subject = question
    kept = merge_annotations(machine.whiteboard, list(by_id.values()), budget=cfg.whiteboard_budget)
    payload = base_payload(records, kept, cfg, question, mode)
    context = payload_as_context(payload)
    expected = row["arms"][arm]["context"]
    if context != expected:
        raise RuntimeError(f"case {row['case']} {arm}: rebuilt context differs from the snapshot")
    provenance = f"\n\n(Question asked on {question_date}.)" if question_date else ""
    return context, machine, question + provenance


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="deepseek-v4-flash")
    parser.add_argument("--judge-model", default="deepseek-v4-flash")
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--api-key", default="")
    args = parser.parse_args()
    api_key = args.api_key or os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key:
        raise SystemExit("set DEEPSEEK_API_KEY (or --api-key)")

    agent_client = CountingClient(
        LLMClient(
            "https://api.deepseek.com", api_key, args.model,
            timeout=args.timeout, retries=1, backoff=0.5,
        )
    )
    judge_client = CountingClient(
        LLMClient(
            "https://api.deepseek.com", api_key, args.judge_model,
            timeout=args.timeout, retries=1, backoff=0.5,
        )
    )
    tasks = {t["question"]: t for t in load_longmemeval(DATA / "longmemeval_s_cleaned.json", 0, 7)}
    work_root = Path(tempfile.mkdtemp(prefix="mm-u42-"))
    rows_out: list[dict[str, Any]] = []

    for slice_name, spec in SLICES.items():
        arms = spec.get("arms", U3_ARMS)
        rows = [
            json.loads(line)
            for line in (OUT_DIR / spec["snapshot"]).read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        flips = set(FLIP_CASES.get(slice_name, []))
        for row in rows:
            n = FLIP_N if row["case"] in flips else U3_N
            question_date = tasks.get(row["question"], {}).get("question_date", "")
            for arm in arms:
                context, machine, question_prompt = rebuild_delivery(
                    spec["root"], row, arm, question_date, work_root
                )
                context_hash = sha(context)
                verdicts: list[str] = []
                for _replicate in range(n):
                    whiteboard_hash = sha(machine.whiteboard.render())
                    answer = answer_with(
                        agent_client, machine, question_prompt, extra_context=context
                    )
                    verdict, _reason = judge(judge_client, row["question"], row["gold"], answer)
                    verdicts.append(verdict)
                modal = Counter(verdicts).most_common(1)[0][0]
                rows_out.append(
                    {
                        "slice": slice_name,
                        "case": row["case"],
                        "cat": row.get("cat", ""),
                        "arm": arm,
                        "n": n,
                        "verdicts": verdicts,
                        "modal": modal,
                        "n_modal": Counter(verdicts).most_common(1)[0][1],
                        "flip_rate_within_arm": round(
                            1.0 - Counter(verdicts).most_common(1)[0][1] / n, 3
                        ),
                        "context_sha256": context_hash,
                        "whiteboard_sha256": whiteboard_hash,
                    }
                )
                print(
                    f"{slice_name} case {row['case']:>3} {arm:<24} n={n} "
                    f"verdicts={verdicts} modal={modal}",
                    flush=True,
                )
        path = OUT_DIR / "u4_replication.jsonl"
        with path.open("w", encoding="utf-8") as handle:
            for item in rows_out:
                handle.write(json.dumps(item, ensure_ascii=False) + "\n")

    print(f"\nwork root: {work_root}")


if __name__ == "__main__":
    main()
