"""Graph recall measurement (M-phase): graph_off vs graph_augment vs graph_only.

Separate from the frozen paper harnesses: same corpora, same judge, same
ingestion regime, but **written only to eval/graph_out/** (gitignored). It
never touches eval/out, eval/archive, docs/RESULTS.md or docs/PAPER.md, and
the graph settings below exist only in this harness (system defaults stay
untouched).

Design invariants:
  1. graph_off and graph_augment share exactly the same ingestion: the base
     machine is built once per case (graph disabled), the projection is built
     once, and each arm gets a byte-identical tape + graph copy.
  2. graph_only is retrieval-only: no answer, no judge, no agent calls.
  3. `graph_extract_types` including "memory" lives only here.
  4. Every metric can be walked back: case -> path -> R#### -> memory_id -> tape.

Run:
  PYTHONPATH=src:.:eval python3 eval/graph_bench.py --dataset synthetic --limit 32 --api-key ...
  PYTHONPATH=src:.:eval python3 eval/graph_bench.py --dataset longmemeval --limit 12 --tag --api-key ...
"""

from __future__ import annotations

import argparse
import hashlib
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
from memory_machine.groups import load_manifest  # noqa: E402
from memory_machine.graph import ExtractorSpec, GraphStore, build_graph  # noqa: E402
from memory_machine.graph_extract import GraphExtractor  # noqa: E402
from memory_machine.graph_resolve import GraphResolver  # noqa: E402
from memory_machine.llm import LLMClient  # noqa: E402
from memory_machine.payload import payload_as_context  # noqa: E402
from memory_machine.retrieval import Embedder, rank  # noqa: E402

from e2e_bench import (  # noqa: E402
    VIEW_CONFIG,
    answer_with,
    build_external_machine,
    judge,
    load_gold,
)
from tag_sessions import tag_sessions  # noqa: E402
from view_router_bench import CountingClient, TASKS, build_machine  # noqa: E402

OUT_DIR = HERE / "graph_out"
GRAPH_EXTRACT_TYPES = "decision,lesson,preference,bugfix,build,memory"
MAX_MEMORY_CHARS = 6000


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


class Meter:
    """Counts LLM calls and prompt/response characters (tokens ~ chars/4)."""

    def __init__(self, client: Any) -> None:
        self.client = client
        self.calls = 0
        self.prompt_chars = 0
        self.response_chars = 0

    def complete(self, messages: list[dict[str, str]], *, temperature: float = 0.0) -> str:
        self.prompt_chars += sum(len(m.get("content", "")) for m in messages)
        out = self.client.complete(messages, temperature=temperature)
        self.calls += 1
        self.response_chars += len(out or "")
        return out


class EmbedMeter:
    def __init__(self, embedder: Any) -> None:
        self.embedder = embedder
        self.calls = 0
        self.texts = 0

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls += 1
        self.texts += len(texts)
        return self.embedder.embed(texts)


ARM_MODES = {
    "graph_off": "off",
    "graph_augment": "augment",
    "graph_augment_guarded": "augment_guarded",
    "graph_augment_precise": "augment_guarded",
    "graph_only": "only",
}

# V2-0 calibration (LME-12 replay):
#   guarded = literal rule  -> keeps 3/3 graph-only gold, -30% non-gold
#   precise = precision     -> keeps 2/3 gold (case 6, no answer effect), -83% non-gold
ARM_FLAGS = {
    "graph_augment_guarded": dict(
        graph_augment_hub_degree=0, graph_augment_min_score=0.80, graph_augment_max_items=5
    ),
    "graph_augment_precise": dict(
        graph_augment_hub_degree=20, graph_augment_min_score=0.80, graph_augment_max_items=3
    ),
}


def make_config(
    mode: str,
    *,
    embedding_model: str,
    embedding_base_url: str,
) -> Config:
    return Config(
        **VIEW_CONFIG,
        evidence_payload="budgeted",
        evidence_payload_budget=4000,
        graph_enabled=mode != "ingest",
        graph_recall_mode=mode if mode in {"off", "augment", "only"} else "off",
        graph_extract_types=GRAPH_EXTRACT_TYPES,
        embedding_model=embedding_model,
        embedding_base_url=embedding_base_url,
    )


def build_case_graph(
    machine: Machine,
    *,
    extraction_client: Meter,
    embedder: Any,
    batch_size: int,
    extract_types: str,
) -> dict[str, Any]:
    store = GraphStore(Path(machine.root) / machine.config.graph_path)
    extractor = GraphExtractor(extraction_client, max_chars=MAX_MEMORY_CHARS)
    resolver = GraphResolver(
        embedder=embedder,
        auto=machine.config.graph_confidence_auto,
        hypothesis=machine.config.graph_confidence_hypothesis,
    )
    before_calls = extraction_client.calls
    before_prompt = extraction_client.prompt_chars
    before_response = extraction_client.response_chars
    started = time.perf_counter()
    result = build_graph(
        machine.tape,
        store,
        ExtractorSpec(extractor.extract, extractor.version),
        extract_types=extract_types,
        rebuild=True,
        extractor_name="llm",
        resolver=resolver,
        max_attempts=machine.config.graph_max_attempts,
        batch_size=batch_size,
        batch_fn=extractor.extract_batch,
    )
    elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
    return {
        "ok": result.get("ok"),
        "counts": store.counts(),
        "hypotheses": len(store.hypotheses()),
        "open_hypotheses": len(store.open_hypotheses()),
        "extracted": result.get("extracted"),
        "pending": result.get("pending"),
        "failed": result.get("failed"),
        "build_ms": elapsed_ms,
        "extract_calls": extraction_client.calls - before_calls,
        "extract_prompt_chars": extraction_client.prompt_chars - before_prompt,
        "extract_response_chars": extraction_client.response_chars - before_response,
        "rejected_pairs": len(store.rejected_pairs()),
    }


def lexical_bucket(question: str, task: dict[str, Any]) -> str:
    """Where the gold sessions rank under BM25 against the question."""
    sessions = task.get("sessions") or []
    required = set(task.get("expected") or [])
    if not sessions or not required:
        return ""
    texts = [s["text"] for s in sessions]
    ranked = rank(question, texts, limit=len(texts))
    positions = [
        position
        for position, (index, _score) in enumerate(ranked, start=1)
        if sessions[index]["id"] in required
    ]
    if not positions:
        return "miss"
    if positions[0] == 1:
        return "top1"
    return "top5" if positions[0] <= 5 else "miss"


def run_arm(
    machine: Machine,
    arm: str,
    *,
    question: str,
    gold: str,
    agent_client: CountingClient,
    judge_client: CountingClient,
    judge_answers: bool,
    question_date: str,
) -> dict[str, Any]:
    machine.config.graph_enabled = True
    machine.config.graph_recall_mode = ARM_MODES[arm]
    machine._invalidate_recall_cache()
    before_calls = agent_client.calls
    started = time.perf_counter()
    res = machine.recall(question, debug=True)
    recall_ms = round((time.perf_counter() - started) * 1000, 1)
    agent_calls = agent_client.calls - before_calls
    context = payload_as_context(res.get("evidence_payload") or [])
    provenance = f"\n\n(Question asked on {question_date}.)" if question_date else ""
    answer = ""
    verdict = ""
    reason = ""
    judge_calls = 0
    if judge_answers:
        answer = answer_with(agent_client, machine, question + provenance, extra_context=context)
        before_judge = judge_client.calls
        verdict, reason = judge(judge_client, question, gold, answer)
        judge_calls = judge_client.calls - before_judge
    return {
        "annotations": [a["memory_id"] for a in res.get("annotations") or []],
        "graph_ids": [item["memory_id"] for item in res.get("graph_evidence") or []],
        "graph_evidence": res.get("graph_evidence") or [],
        "graph_metrics": res.get("graph_metrics") or {},
        "payload_ids": [item["memory_id"] for item in res.get("evidence_payload") or []],
        "payload_chars": int(res.get("evidence_payload_chars") or 0),
        "answer": answer,
        "verdict": verdict,
        "reason": reason[:300],
        "recall_ms": recall_ms,
        "llm_calls": agent_calls + judge_calls,
    }


def retrieval_metrics(
    required: list[str],
    off_ids: list[str],
    augment_ids: list[str],
    graph_ids: list[str],
) -> dict[str, Any]:
    required_set = set(required)
    agent = set(off_ids)
    graph = set(graph_ids)
    union = set(augment_ids)

    def recall(ids: set[str]) -> float | None:
        return round(len(ids & required_set) / len(required_set), 4) if required_set else None

    return {
        "required": len(required_set),
        "agent_recall": recall(agent),
        "graph_recall": recall(graph),
        "graph_precision": round(len(graph & required_set) / len(graph), 4) if graph else None,
        "union_recall": recall(union),
        "graph_only_gold": sorted((graph - agent) & required_set),
        "graph_only_count": len(graph - agent),
        "agent_only_gold": sorted((agent - graph) & required_set),
        "overlap_gold": sorted((graph & agent) & required_set),
        "agent_evidence_complete": int(required_set <= agent),
        "graph_evidence_complete": int(required_set <= graph),
        "union_evidence_complete": int(required_set <= union),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", choices=["synthetic", "longmemeval"], default="synthetic")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--indices", default="")
    parser.add_argument("--model", default="deepseek-v4-flash")
    parser.add_argument("--judge-model", default="deepseek-v4-flash")
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--embedding-model", default="nomic-embed-text")
    parser.add_argument("--embedding-base-url", default="http://localhost:11434/v1")
    parser.add_argument("--ingest-why", type=int, default=0, help="0 = full session text")
    parser.add_argument("--no-dates", action="store_true")
    parser.add_argument("--no-judge", action="store_true")
    parser.add_argument("--tag", action="store_true", help="tag external sessions at write time")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--api-key", default="")
    parser.add_argument(
        "--reuse-root",
        type=Path,
        default=None,
        help="copy tape+graph from a previous run's root instead of re-extracting",
    )
    parser.add_argument(
        "--arms",
        default=",".join(ARM_MODES),
        help="comma-separated arms to run",
    )
    args = parser.parse_args()
    selected_arms = [a.strip() for a in args.arms.split(",") if a.strip()]

    api_key = args.api_key or os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key:
        raise SystemExit("set DEEPSEEK_API_KEY (or --api-key)")
    judge_answers = not args.no_judge

    agent_client = CountingClient(
        LLMClient("https://api.deepseek.com", api_key, args.model, timeout=args.timeout, retries=1, backoff=0.5)
    )
    judge_client = CountingClient(
        LLMClient("https://api.deepseek.com", api_key, args.judge_model, timeout=args.timeout, retries=1, backoff=0.5)
    )
    extraction_meter = Meter(
        LLMClient("https://api.deepseek.com", api_key, args.model, timeout=args.timeout, retries=1, backoff=0.5)
    )
    embed_meter = EmbedMeter(
        Embedder(args.embedding_base_url, "", args.embedding_model, timeout=300)
    )

    root = Path(tempfile.mkdtemp(prefix="mm-graph-"))
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    tags: dict[str, dict[str, Any]] = {}
    tasks: dict[int, dict[str, Any]] = {}
    if args.dataset == "synthetic":
        gold = load_gold()
        indices = [int(x) for x in args.indices.split(",") if x.strip()] or list(range(len(TASKS)))
        if args.limit > 0:
            indices = indices[: args.limit]
        tasks = {
            i: {
                "question": TASKS[i]["q"],
                "cat": TASKS[i]["cat"],
                "required": TASKS[i]["required"],
            }
            for i in indices
        }
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
            for task in tasks.values():
                for session in task["sessions"]:
                    unique.setdefault(session["id"], session)
            print(f"tagging {len(unique)} sessions ...", flush=True)
            tags = tag_sessions("longmemeval", list(unique.values()), agent_client, batch=8)

    ingest_cfg = make_config(
        "ingest", embedding_model=args.embedding_model, embedding_base_url=args.embedding_base_url
    )
    arms = ["graph_off", "graph_augment", "graph_augment_guarded", "graph_augment_precise", "graph_only"]

    # Synthetic fixture: identical tape for every case -> build the graph once.
    fixture_machine: Machine | None = None
    fixture_graph: Path | None = None
    fixture_result: dict[str, Any] | None = None
    if args.dataset == "synthetic":
        fixture_dir = root / "_fixture"
        fixture_machine, fixture_map = build_machine(fixture_dir, ingest_cfg)
        fixture_tape_hash = sha256(Path(fixture_machine.root) / "tape.jsonl")
        fixture_result = build_case_graph(
            fixture_machine,
            extraction_client=extraction_meter,
            embedder=embed_meter,
            batch_size=args.batch_size,
            extract_types=GRAPH_EXTRACT_TYPES,
        )
        fixture_graph = Path(fixture_machine.root) / fixture_machine.config.graph_path
        print(
            f"fixture graph: {fixture_result['counts']} "
            f"calls={fixture_result['extract_calls']} ms={fixture_result['build_ms']}",
            flush=True,
        )

    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=HERE.parent, text=True
        ).strip()
    except Exception:
        commit = ""
    run_id = datetime.now(timezone.utc).strftime("%Y-%m-%d-graph-%H%M%S")
    manifest = {
        "run_id": run_id,
        "dataset": args.dataset,
        "model": args.model,
        "judge_model": args.judge_model,
        "batch_size": args.batch_size,
        "embedding_model": args.embedding_model,
        "extract_types": GRAPH_EXTRACT_TYPES,
        "max_memory_chars": MAX_MEMORY_CHARS,
        "ingest_why": args.ingest_why,
        "ingest_dates": not args.no_dates,
        "judge_answers": judge_answers,
        "git_commit": commit,
        "indices": indices,
        "fixture_graph": fixture_result if args.dataset == "synthetic" else None,
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    (OUT_DIR / f"run_manifest_graph_{args.dataset}.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    rows: list[dict[str, Any]] = []
    for index in indices:
        task = tasks[index]
        if not gold.get(index):
            continue
        print(f"case {index} ...", flush=True)
        case_dir = root / f"case_{index:02d}"
        base = case_dir / "_base"
        if args.dataset == "synthetic":
            base_machine, id_map = build_machine(base, ingest_cfg)
            required = [id_map[key] for key in task["required"]]
            bucket = ""
            sessions = 0
            question_date = ""
        else:
            base_machine, id_map = build_external_machine(
                base,
                task,
                ingest_cfg,
                tags,
                agent_client,
                summary_limit=300,
                why_limit=args.ingest_why,
                dates=not args.no_dates,
            )
            required = [id_map[s] for s in task["expected"] if s in id_map]
            bucket = lexical_bucket(task["question"], task)
            sessions = len(task["sessions"])
            question_date = task.get("question_date", "") if not args.no_dates else ""

        if args.reuse_root is not None:
            reuse = args.reuse_root / f"case_{index:02d}" / "graph_augment"
            if not (reuse / "tape.jsonl").exists():
                raise RuntimeError(f"reuse root missing case {index}: {reuse}")
            for name in ("tape.jsonl", "manifest.json"):
                if (reuse / name).exists():
                    shutil.copy2(reuse / name, Path(base_machine.root) / name)
            reused_graph = reuse / "graph"
            if (Path(base_machine.root) / "graph").exists():
                shutil.rmtree(Path(base_machine.root) / "graph")
            if reused_graph.exists():
                shutil.copytree(reused_graph, Path(base_machine.root) / "graph")
            base_machine.manifest = load_manifest(
                Path(base_machine.root) / "manifest.json", capacity=base_machine.config.capacity
            )
        tape_hash = sha256(Path(base_machine.root) / "tape.jsonl")
        if args.dataset == "synthetic" and fixture_graph is not None:
            if tape_hash != fixture_tape_hash:
                raise RuntimeError("synthetic fixture tape drifted")
            shutil.copytree(fixture_graph, Path(base_machine.root) / "graph")
            graph_result = {
                **(fixture_result or {}),
                "reused_fixture": True,
                "extract_calls": 0,
                "extract_prompt_chars": 0,
                "extract_response_chars": 0,
                "build_ms": 0.0,
            }
        else:
            graph_result = build_case_graph(
                base_machine,
                extraction_client=extraction_meter,
                embedder=embed_meter,
                batch_size=args.batch_size,
                extract_types=GRAPH_EXTRACT_TYPES,
            )
            graph_result["reused_fixture"] = False
        graph_dir = Path(base_machine.root) / base_machine.config.graph_path
        audit_dir = OUT_DIR / "graphs" / args.dataset / f"case_{index:02d}"
        if audit_dir.exists():
            shutil.rmtree(audit_dir)
        shutil.copytree(graph_dir, audit_dir)

        arm_rows: dict[str, Any] = {}
        for arm in selected_arms:
            arm_dir = case_dir / arm
            if arm_dir.exists():
                shutil.rmtree(arm_dir)
            arm_dir.mkdir(parents=True)
            shutil.copy2(Path(base_machine.root) / "tape.jsonl", arm_dir / "tape.jsonl")
            manifest_path = Path(base_machine.root) / "manifest.json"
            if manifest_path.exists():
                shutil.copy2(manifest_path, arm_dir / "manifest.json")
            shutil.copytree(graph_dir, arm_dir / "graph")
            if sha256(arm_dir / "tape.jsonl") != tape_hash:
                raise RuntimeError(f"tape drift in {arm_dir}")
            arm_config = make_config(
                "augment",
                embedding_model=args.embedding_model,
                embedding_base_url=args.embedding_base_url,
            )
            for flag, value in ARM_FLAGS.get(arm, {}).items():
                setattr(arm_config, flag, value)
            arm_machine = Machine(
                arm_dir,
                config=arm_config,
                client=agent_client,
            )
            arm_rows[arm] = run_arm(
                arm_machine,
                arm,
                question=task["question"],
                gold=gold[index],
                agent_client=agent_client,
                judge_client=judge_client,
                judge_answers=judge_answers and arm != "graph_only",
                question_date=question_date,
            )

        off = arm_rows["graph_off"]
        augment = arm_rows["graph_augment"]
        only = arm_rows["graph_only"]
        retrieval = retrieval_metrics(
            required, off["annotations"], augment["annotations"], only["graph_ids"]
        )
        retrieval_by_arm = {
            arm: retrieval_metrics(
                required,
                off["annotations"],
                arm_rows[arm]["annotations"],
                arm_rows[arm]["graph_ids"],
            )
            for arm in selected_arms
        }
        row = {
            "case": index,
            "cat": task.get("cat") or task.get("type", ""),
            "question": task["question"],
            "gold": gold[index],
            "required_ids": required,
            "strata": {
                "lexical_bucket": bucket,
                "required_sessions": len(required),
                "multi_session": int(len(required) > 1),
                "graph_seeds": only["graph_metrics"].get("graph_seed_entities", 0),
            },
            "ingestion": {
                "sessions": sessions,
                "tape_records": len(base_machine.tape),
                "tape_sha256": tape_hash,
            },
            "graph": graph_result,
            "retrieval": retrieval,
            "retrieval_by_arm": retrieval_by_arm,
            "arms": arm_rows,
            "cost": {
                "extract_calls_case": graph_result.get("extract_calls", 0),
                "extract_prompt_chars_case": graph_result.get("extract_prompt_chars", 0),
                "embed_calls_total": embed_meter.calls,
                "embed_texts_total": embed_meter.texts,
            },
        }
        rows.append(row)
        path = OUT_DIR / f"graph_bench_{args.dataset}.jsonl"
        with path.open("w", encoding="utf-8") as handle:
            for item in rows:
                handle.write(json.dumps(item, ensure_ascii=False) + "\n")
        print(
            f"  off={len(off['annotations'])} augment={len(augment['annotations'])} "
            f"graph={len(only['graph_ids'])} graph_only_gold={len(retrieval['graph_only_gold'])} "
            f"evidence(off/union)={retrieval['agent_evidence_complete']}/{retrieval['union_evidence_complete']}",
            flush=True,
        )

    final = OUT_DIR / f"graph_bench_{args.dataset}.jsonl"
    checksums = OUT_DIR / "CHECKSUMS_graph.txt"
    lines = []
    for file in sorted(OUT_DIR.rglob("*")):
        if file.is_file() and file.name != checksums.name:
            lines.append(f"{sha256(file)}  {file.relative_to(OUT_DIR.parent.parent)}")
    checksums.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("\naggregate:")
    for arm in selected_arms:
        rows_arm = [row["arms"][arm] for row in rows]
        judged = [row for row in rows_arm if row["verdict"]]
        strict = (
            sum(1 for row in judged if row["verdict"] == "correct") / len(judged)
            if judged
            else None
        )
        print(f"  {arm:<14} n={len(rows_arm)} verdicts={len(judged)} strict={strict}")
    graph_only_gold = sum(len(row["retrieval"]["graph_only_gold"]) for row in rows)
    print(f"  graph_only_gold total: {graph_only_gold}")
    print(f"snapshots: {final}")
    if args.dataset == "longmemeval":
        print(f"root: {root}")


if __name__ == "__main__":
    main()
