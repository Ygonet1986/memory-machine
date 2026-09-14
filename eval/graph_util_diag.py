"""U-phase utilization diagnostics (graph/admission frozen).

For each shared-agent replay snapshot, rebuilds the deterministic payloads per
arm and records, per gold memory: delivered? position/allocation/truncation?
cited/used/contradicted/ignored (deterministic mention + LLM probe). Then runs
two answerer/delivery-only interventions:

  i1_fact_floor   same precise admission, payload with a 600-char floor per item
  i4_gold_full    gold sessions only, untruncated (diagnostic ceiling)

No graph, retrieval or admission change: agent annotations are the frozen ones
from the snapshot, and all payloads are rebuilt deterministically.

Run:
  PYTHONPATH=src:.:eval python3 eval/graph_util_diag.py --api-key ... [--stage u1|u2|all]
"""

from __future__ import annotations

import argparse
import json
import os
import re
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

from memory_machine.coordinator import Machine  # noqa: E402
from memory_machine.graph import GraphStore  # noqa: E402
from memory_machine.graph_recall import GraphRecall, guard_evidence, question_gate  # noqa: E402
from memory_machine.llm import LLMClient, extract_json_object  # noqa: E402
from memory_machine.payload import build_evidence_payload, payload_as_context  # noqa: E402
from memory_machine.retrieval import tokenize  # noqa: E402
from memory_machine.tape import Tape  # noqa: E402
from memory_machine.whiteboard import Annotation, merge_annotations  # noqa: E402

from e2e_bench import answer_with, classify_error, judge  # noqa: E402
from graph_bench import sha256  # noqa: E402
from graph_replay_shared import copy_case, variant_config, variant_evidence  # noqa: E402
from view_router_bench import CountingClient  # noqa: E402

OUT_DIR = HERE / "graph_out"
SLICES = {
    "longmemeval": {
        "snapshot": "graph_bench_longmemeval.jsonl",
        "root": Path("/var/folders/3z/9n8mh2p12ld771wy19z5v7rw0000gn/T/mm-graph-shared-81shc_0e"),
    },
    "longmemeval_lexmiss": {
        "snapshot": "graph_bench_longmemeval_lexmiss.jsonl",
        "root": Path("/var/folders/3z/9n8mh2p12ld771wy19z5v7rw0000gn/T/mm-graph-shared-r3hyd5my"),
    },
}
ARMS = ["graph_off", "graph_augment", "graph_augment_precise"]
PROBE_ARMS = {"graph_augment", "graph_augment_precise"}
I1_FLOOR = 600

PROBE_SYSTEM = """You check whether a CANDIDATE ANSWER uses the fact stated in ONE memory.
Return ONLY a JSON object: {"usage":"used|partial|ignored|contradicted","why":"<short>"}
- used: the answer states the memory's fact (paraphrase counts).
- partial: the answer uses part of the fact but drops something required.
- ignored: the memory's fact plays no role in the answer.
- contradicted: the answer states the opposite of the memory's fact.
Judge only this memory, not the overall correctness."""


def frozen_agent_annotations(case: dict[str, Any]) -> list[Annotation]:
    """The agent annotations exactly as the shared replay froze them."""
    path = case["root"] / f"case_{case['case']:02d}_agent" / "whiteboard.json"
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            items = data.get("annotations") or []
            annotations = [
                Annotation(
                    memory_id=str(item["memory_id"]),
                    note=str(item.get("note") or ""),
                    relevance=float(item.get("relevance") or 0.0),
                    agent_id=str(item.get("agent_id") or ""),
                )
                for item in items
                if item.get("memory_id")
            ]
            if annotations:
                return annotations
        except (json.JSONDecodeError, OSError, KeyError, TypeError, ValueError):
            pass
    return [
        Annotation(memory_id=mid, note="agent", relevance=0.9, agent_id="agent")
        for mid in sorted(case["row"]["agent_ids"])
    ]


def gold_text(record: Any) -> str:
    return f"{record.summary} {record.why}".strip() if record is not None else ""


def answer_tokens(text: str) -> set[str]:
    return {t for t in tokenize(text) if len(t) > 2}


def mention_stats(answer: str, gold: str, memory_id: str) -> dict[str, Any]:
    cited = memory_id in set(re.findall(r"M\d{4}", answer))
    at = answer_tokens(answer)
    gt = answer_tokens(gold)
    overlap = len(at & gt) / len(gt) if gt else 0.0
    return {"cited_memory_id": cited, "answer_gold_overlap": round(overlap, 4)}


def probe_usage(
    client: CountingClient, question: str, reference: str, memory_text: str, answer: str
) -> dict[str, Any]:
    messages = [
        {"role": "system", "content": PROBE_SYSTEM},
        {
            "role": "user",
            "content": (
                f"Question: {question}\nReference answer: {reference}\n"
                f"Memory:\n{memory_text[:1500]}\nCandidate answer:\n{answer[:2000]}"
            ),
        },
    ]
    content = client.complete(messages, temperature=0.0)
    obj = extract_json_object(content)
    usage = str(obj.get("usage") or "").strip().lower()
    if usage not in {"used", "partial", "ignored", "contradicted"}:
        usage = "unknown"
    return {"usage": usage, "why": str(obj.get("why") or "")[:200]}


def _segments(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+|\n+", text)
    return [part.strip() for part in parts if part.strip()]


def fact_window(text: str, question: str, allocation: int) -> str:
    """Keep the question-matching window of a long memory instead of its head.

    Deterministic: segments of the session are scored by question-token
    coverage; the best segment is expanded left/right until the allocation is
    filled. Falls back to the head when nothing matches.
    """
    if allocation <= 0 or not text:
        return text[: max(0, allocation)]
    segments = _segments(text)
    if not segments or sum(len(s) + 1 for s in segments) <= allocation:
        return text[:allocation]
    qtokens = answer_tokens(question)
    scores = [len(qtokens & answer_tokens(segment)) for segment in segments]
    best = max(range(len(scores)), key=lambda i: (scores[i], -i))
    chosen = [best]
    used = len(segments[best])
    left, right = best - 1, best + 1
    while len(" ".join(segments[i] for i in chosen)) < allocation:
        take_left = left >= 0 and (right >= len(segments) or scores[left] >= scores[right])
        if take_left:
            chosen.insert(0, left)
            left -= 1
        elif right < len(segments):
            chosen.append(right)
            right += 1
        else:
            break
    window = " … ".join(segments[i] for i in chosen)
    if len(window) <= allocation:
        return window
    cut = window[:allocation]
    return cut.rsplit(" ", 1)[0] if " " in cut else cut


def full_gold_text(records: dict[str, Any], ids: list[str]) -> str:
    blocks = []
    for memory_id in ids:
        record = records.get(memory_id)
        if record is None:
            continue
        blocks.append(f"[{record.id}] {record.summary}\n{record.why}")
    return "\n\n".join(blocks)


def analyze_arm(
    case: dict[str, Any],
    arm: str,
    records_for: dict[str, Any],
    *,
    judge_client: CountingClient,
    probe_client: CountingClient,
    stage: str,
) -> dict[str, Any]:
    base = case["root"] / f"case_{case['case']:02d}"
    records = records_for
    required = list(case["row"]["required_ids"])
    agent_ids = set(case["row"]["agent_ids"])
    question = case["row"]["question"]
    answer = case["row"]["arms"][arm]["answer"]
    verdict = case["row"]["arms"][arm]["verdict"]
    reason = case["row"]["arms"][arm]["reason"]
    cfg = variant_config(arm)
    result: dict[str, Any] = {"answer": answer, "verdict": verdict, "reason": reason}

    if arm == "graph_off":
        raw_evidence: list[Any] = []
        admitted: list[Any] = []
        graph_annotations: list[Annotation] = []
    else:
        store = GraphStore(base / "graph")
        index = store.index()
        hub = cfg.graph_hub_degree
        if not hub and cfg.graph_recall_mode == "augment_guarded":
            hub = cfg.graph_augment_hub_degree
        recall = GraphRecall(index, depth=cfg.graph_depth, top_k=cfg.graph_top_k, hub_degree=hub)
        raw_evidence = recall.recall(question).evidence
        admitted = raw_evidence
        if cfg.graph_recall_mode == "augment_guarded":
            admitted = guard_evidence(
                admitted,
                min_score=cfg.graph_augment_min_score,
                max_items=cfg.graph_augment_max_items,
            )
            if cfg.graph_augment_question_gate:
                admitted = question_gate(
                    admitted, records, question, min_cov=cfg.graph_augment_question_min_cov
                )
        graph_annotations = [
            Annotation(
                memory_id=item.memory_id,
                note=item.label or "graph evidence",
                relevance=max(0.05, float(item.score)),
                agent_id="graph",
            )
            for item in admitted
            if item.memory_id in {r.id for r in records.values() if r.status == "active"}
        ]

    agent_annotations = frozen_agent_annotations(case)
    union = list(agent_annotations)
    by_id = {a.memory_id: a for a in union}
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

    work_dir = case["work_root"] / f"{arm}"
    copy_case(base, work_dir)
    machine = Machine(work_dir, config=cfg, client=case["agent_client"])
    machine.whiteboard.annotations = []
    machine.whiteboard.subject = question
    kept = merge_annotations(machine.whiteboard, union, budget=cfg.whiteboard_budget)
    payload = build_evidence_payload(
        records, kept, budget=cfg.evidence_payload_budget, min_item_chars=cfg.evidence_payload_min_item
    )
    context = payload_as_context(payload)
    result["payload_ids"] = [item["memory_id"] for item in payload]
    result["payload_chars"] = sum(item["used_chars"] for item in payload)
    result["payload_matches_snapshot"] = (
        result["payload_ids"] == list(case["row"]["arms"][arm]["payload_ids"])
        and result["payload_chars"] == case["row"]["arms"][arm]["payload_chars"]
    )
    result["context"] = context

    admitted_ids = {item.memory_id for item in admitted}
    raw_ids = {item.memory_id for item in raw_evidence}
    payload_by_id = {item["memory_id"]: item for item in payload}
    gold: list[dict[str, Any]] = []
    for memory_id in required:
        record = records.get(memory_id)
        text = gold_text(record)
        entry: dict[str, Any] = {"memory_id": memory_id, "gold_text": text}
        item = payload_by_id.get(memory_id)
        if item is not None:
            entry.update(
                {
                    "delivered": True,
                    "position": result["payload_ids"].index(memory_id) + 1,
                    "allocated_chars": item["allocated_chars"],
                    "used_chars": item["used_chars"],
                    "truncated": item["truncated"],
                }
            )
            entry.update(mention_stats(answer, text, memory_id))
            if stage in {"u1", "all"} and arm in PROBE_ARMS:
                entry["probe"] = probe_usage(
                    probe_client, question, case["row"]["gold"], text, answer
                )
        else:
            if memory_id in agent_ids:
                why = "agent_not_delivered"
            elif memory_id in admitted_ids:
                why = "dropped_in_payload"
            elif memory_id in raw_ids:
                why = "filtered_by_guard"
            else:
                why = "not_retrieved"
            entry.update({"delivered": False, "reason": why})
        gold.append(entry)
    result["gold"] = gold
    if stage in {"u1", "all"} and verdict != "correct":
        kind, why = classify_error(judge_client, question, case["row"]["gold"], context, answer)
        result["error_kind"] = {"kind": kind, "why": why[:200]}
    return result


def run_u2(
    case: dict[str, Any],
    judge_client: CountingClient,
    agent_client: CountingClient,
    interventions: set[str],
) -> dict[str, Any]:
    """Answerer/delivery-only interventions, judged with the same answerer."""
    records = case["records"]
    required = list(case["row"]["required_ids"])
    question = case["row"]["question"]
    question_date = case.get("question_date", "")
    provenance = f"\n\n(Question asked on {question_date}.)" if question_date else ""
    out: dict[str, Any] = {}
    if "i1" not in interventions and "i4" not in interventions and "i5" not in interventions:
        return out
    if "i5" in interventions:
        cfg = variant_config("graph_augment_precise")
        work_dir = case["work_root"] / "i5_fact_window"
        copy_case(case["root"] / f"case_{case['case']:02d}", work_dir)
        machine = Machine(work_dir, config=cfg, client=agent_client)
        evidence = variant_evidence(case["root"] / f"case_{case['case']:02d}", cfg, question)
        graph_annotations = [
            Annotation(
                memory_id=item.memory_id,
                note=item.label or "graph evidence",
                relevance=max(0.05, float(item.score)),
                agent_id="graph",
            )
            for item in evidence
            if item.memory_id in {r.id for r in records.values() if r.status == "active"}
        ]
        agent_annotations = frozen_agent_annotations(case)
        union = {a.memory_id: a for a in agent_annotations}
        for item in graph_annotations:
            current = union.get(item.memory_id)
            if current is None or item.relevance > current.relevance:
                union[item.memory_id] = item
        machine.whiteboard.annotations = []
        machine.whiteboard.subject = question
        kept = merge_annotations(machine.whiteboard, list(union.values()), budget=cfg.whiteboard_budget)
        payload = build_evidence_payload(
            records, kept, budget=cfg.evidence_payload_budget,
            min_item_chars=cfg.evidence_payload_min_item,
        )
        windowed = []
        for item in payload:
            record = records.get(item["memory_id"])
            entry = dict(item)
            if record is not None and item["truncated"]:
                header = item["evidence"].split("\n", 1)[0]
                allocation = max(0, item["used_chars"] - len(header) - 1)
                body = fact_window(record.why or record.summary, question, allocation)
                entry["evidence"] = f"{header}\n{body}"
                entry["windowed"] = True
            windowed.append(entry)
        context = payload_as_context(windowed)
        answer = answer_with(agent_client, machine, question + provenance, extra_context=context)
        verdict, reason = judge(judge_client, question, case["row"]["gold"], answer)
        out["i5_fact_window"] = {
            "answer": answer,
            "verdict": verdict,
            "reason": reason,
            "payload_ids": [item["memory_id"] for item in windowed],
            "payload_chars": sum(len(item["evidence"]) for item in windowed),
            "windowed_items": sum(1 for item in windowed if item.get("windowed")),
            "context": context,
        }
    if "i1" not in interventions and "i4" not in interventions:
        return out

    # i1: same precise admission, fact-floor delivery
    cfg = variant_config("graph_augment_precise")
    work_dir = case["work_root"] / "i1_fact_floor"
    copy_case(case["root"] / f"case_{case['case']:02d}", work_dir)
    machine = Machine(work_dir, config=cfg, client=agent_client)
    evidence = variant_evidence(case["root"] / f"case_{case['case']:02d}", cfg, question)
    graph_annotations = [
        Annotation(
            memory_id=item.memory_id,
            note=item.label or "graph evidence",
            relevance=max(0.05, float(item.score)),
            agent_id="graph",
        )
        for item in evidence
        if item.memory_id in {r.id for r in records.values() if r.status == "active"}
    ]
    agent_annotations = frozen_agent_annotations(case)
    union = {a.memory_id: a for a in agent_annotations}
    for item in graph_annotations:
        current = union.get(item.memory_id)
        if current is None or item.relevance > current.relevance:
            union[item.memory_id] = item
    machine.whiteboard.annotations = []
    machine.whiteboard.subject = question
    kept = merge_annotations(machine.whiteboard, list(union.values()), budget=cfg.whiteboard_budget)
    payload = build_evidence_payload(
        records, kept, budget=cfg.evidence_payload_budget, min_item_chars=I1_FLOOR
    )
    context = payload_as_context(payload)
    answer = answer_with(agent_client, machine, question + provenance, extra_context=context)
    verdict, reason = judge(judge_client, question, case["row"]["gold"], answer)
    out["i1_fact_floor"] = {
        "answer": answer,
        "verdict": verdict,
        "reason": reason,
        "payload_ids": [item["memory_id"] for item in payload],
        "payload_chars": sum(item["used_chars"] for item in payload),
        "context": context,
    }

    # i4: gold sessions only, untruncated (diagnostic ceiling)
    cfg4 = variant_config("graph_augment_precise")
    work4 = case["work_root"] / "i4_gold_full"
    copy_case(case["root"] / f"case_{case['case']:02d}", work4)
    machine4 = Machine(work4, config=cfg4, client=agent_client)
    machine4.whiteboard.annotations = []
    machine4.whiteboard.subject = question
    context4 = full_gold_text(records, required)
    answer4 = answer_with(agent_client, machine4, question + provenance, extra_context=context4)
    verdict4, reason4 = judge(judge_client, question, case["row"]["gold"], answer4)
    out["i4_gold_full"] = {
        "answer": answer4,
        "verdict": verdict4,
        "reason": reason4,
        "context_chars": len(context4),
        "context": context4,
    }
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slice", default="", choices=["", *SLICES])
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--stage", default="all", choices=["u1", "u2", "all"])
    parser.add_argument(
        "--interventions", default="i1,i4",
        help="comma-separated: i1,i4,i5",
    )
    parser.add_argument("--model", default="deepseek-v4-flash")
    parser.add_argument("--judge-model", default="deepseek-v4-flash")
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--api-key", default="")
    args = parser.parse_args()
    api_key = args.api_key or os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key:
        raise SystemExit("set DEEPSEEK_API_KEY (or --api-key)")

    agent_client = CountingClient(
        LLMClient("https://api.deepseek.com", api_key, args.model, timeout=args.timeout, retries=1, backoff=0.5)
    )
    judge_client = CountingClient(
        LLMClient("https://api.deepseek.com", api_key, args.judge_model, timeout=args.timeout, retries=1, backoff=0.5)
    )
    probe_client = CountingClient(
        LLMClient("https://api.deepseek.com", api_key, args.judge_model, timeout=args.timeout, retries=1, backoff=0.5)
    )

    from external_bench import DATA, load_longmemeval

    tasks = {t["question"]: t for t in load_longmemeval(DATA / "longmemeval_s_cleaned.json", 0, 7)}
    work_root = Path(tempfile.mkdtemp(prefix="mm-util-"))
    slices = [args.slice] if args.slice else list(SLICES)
    for name in slices:
        spec = SLICES[name]
        rows = [
            json.loads(line)
            for line in (OUT_DIR / spec["snapshot"]).read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        if args.limit:
            rows = rows[: args.limit]
        out_rows = []
        for row in rows:
            case_dir = spec["root"] / f"case_{row['case']:02d}"
            records = {r.id: r for r in Tape(case_dir / "tape.jsonl").read()}
            task = tasks.get(row["question"], {})
            case = {
                "case": row["case"],
                "row": row,
                "root": spec["root"],
                "records": records,
                "work_root": work_root / name,
                "agent_client": agent_client,
                "question_date": task.get("question_date", ""),
            }
            arm_rows = {}
            for arm in ARMS:
                arm_rows[arm] = analyze_arm(
                    case, arm, records, judge_client=judge_client,
                    probe_client=probe_client, stage=args.stage,
                )
            if args.stage in {"u2", "all"}:
                arm_rows.update(
                    run_u2(
                        case, judge_client, agent_client,
                        {x.strip() for x in args.interventions.split(",") if x.strip()},
                    )
                )
            out_rows.append(
                {
                    "case": row["case"],
                    "cat": row["cat"],
                    "question": row["question"],
                    "gold": row["gold"],
                    "required_ids": row["required_ids"],
                    "agent_ids": row["agent_ids"],
                    "arms": arm_rows,
                }
            )
            path = OUT_DIR / f"u_diag_{name}.jsonl"
            merged_rows: dict[int, dict[str, Any]] = {}
            if path.exists():
                for line in path.read_text(encoding="utf-8").splitlines():
                    if line.strip():
                        old_row = json.loads(line)
                        merged_rows[old_row["case"]] = old_row
            for item in out_rows:
                old = merged_rows.get(item["case"])
                if old is not None:
                    arms = dict(old.get("arms") or {})
                    arms.update(item.get("arms") or {})
                    old["arms"] = arms
                    merged_rows[item["case"]] = old
                else:
                    merged_rows[item["case"]] = item
            with path.open("w", encoding="utf-8") as handle:
                for item in merged_rows.values():
                    handle.write(json.dumps(item, ensure_ascii=False) + "\n")
            delivered = sum(
                1 for g in arm_rows["graph_augment_precise"]["gold"] if g.get("delivered")
            )
            print(
                f"{name} case {row['case']}: precise={arm_rows['graph_augment_precise']['verdict']} "
                f"gold_delivered={delivered}/{len(row['required_ids'])} "
                + (f"i1={arm_rows['i1_fact_floor']['verdict']} i4={arm_rows['i4_gold_full']['verdict']}"
                   if "i1_fact_floor" in arm_rows else ""),
                flush=True,
            )

    checksums = OUT_DIR / "CHECKSUMS_graph.txt"
    lines = []
    for file in sorted(OUT_DIR.rglob("*")):
        if file.is_file() and file.name != checksums.name:
            lines.append(f"{sha256(file)}  {file.relative_to(OUT_DIR.parent.parent)}")
    checksums.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"done; work root: {work_root}")


if __name__ == "__main__":
    main()
