#!/usr/bin/env python3
"""P2 shadow — populate a ledger from train cases and evaluate it on U4.2.

Pre-registration: docs/PLASTICITY_V1.md §12 (frozen, commit 9594e92).

Pipeline per run label (A and B, both from scratch):

1. POPULATE: train cases 0–11 (disjoint from the U4.2 eval set 12–41). For each
   train case we replay the deterministic recall (same search space as P1) and,
   per delivered item in `graph_off` ground order, per retained candidate path
   (≤ max_paths_per_evidence=3 by base score), record the frozen composite
   signal (§12.3) on every edge of the path:
       fact_presence +0.60 | wasted_context −0.40 | multi_evidence_complete
       +0.30 | budget_respected +0.10 | cross_document_leak −0.60 (blocks).
2. FREEZE: the populated ledger is copied read-only to `<run>/ledger_frozen/`
   with a deterministic ts mask (timestamps are audit-only; the frozen copy is
   what evaluation loads), sha1 recorded in the manifest.
3. EVALUATE (shadow): the frozen ledger adjusts ranking by energy
   `E = D − w_u·U`; the base arm is the score ranking. Per-case outcome comes
   from the **budgeted payload** (addendum §12.5): walk each arm's ordered
   items until `graph_top_k=8` items or `evidence_payload_budget=4000` chars,
   `delivered_ids` = those memory-ids; correct ⇔ `required_ids ⊆ delivered_ids`.
4. CLASSIFY: repaired / regressed / stayed-correct / stayed-incorrect ⇒
   `net = repaired − regressed` (§12.5).
5. NEGATIVE CONTROL: same eval with an empty ledger must reproduce run1's
   byte-identical observer output (0/30 changed).
6. REPLICATE: runA and runB must produce byte-identical frozen ledger (sha1)
   and identiv notebook of the 30-case classification (§12.8).

Nothing here runs an LLM or writes outside `--out` (mutation guard, exit 2).

Expected usage:

    PYTHONPATH=src python3 eval/plasticity_shadow.py \
        --out eval/results/plasticity_u42_shadow

    PYTHONPATH=src python3 eval/plasticity_shadow.py --fake   # self-check
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

from memory_machine.graph import GraphIndex, GraphStore
from memory_machine.graph_recall import GraphRecall
from memory_machine.graph_utility import (
    DEFAULT_SCOPE,
    WEIGHT_UTILITY,
    EdgeKey,
    UtilityLedger,
)

import plasticity_observe as obs

DEPTH = obs.DEPTH
TOP_K = obs.TOP_K
MAX_PATHS = obs.MAX_PATHS
HOP_COST_OBSERVE = obs.HOP_COST_OBSERVE

TRAIN_CASES = range(0, 12)               # population pool (disjoint from eval)
EVAL_CASES = [c for _, r in obs.SLICES for c in r]  # U4.2 12–41 (30 cases)
MAX_PATHS_PER_EVIDENCE = 3               # frozen search limit (§12.3)
BUDGET_ITEMS = 8                         # graph_top_k (config default)
BUDGET_CHARS = 4000                      # evidence_payload_budget (config default)

SIGNAL_FACT_PRESENCE = 0.60
SIGNAL_WASTED = -0.40
SIGNAL_MULTI = 0.30
SIGNAL_BUDGET = 0.10
SIGNAL_LEAK = -0.60

P1_RUN1_ITER_SHA1 = "3d9df4dc6df19bc06bdd3eea2801e04f386afd13"


def sha1_bytes(blob: bytes) -> str:
    return hashlib.sha1(blob).hexdigest()


def sha1_file(path: Path) -> str:
    return sha1_bytes(path.read_bytes())


def _path_composite_edges(path, index: GraphIndex) -> tuple[list[EdgeKey], bool]:
    rels = [index.relations[rid] for rid in path.relations if rid in index.relations]
    if not rels:
        return [], False
    leak = len({(r.source_document or "").strip() for r in rels if (r.source_document or "").strip()}) > 1
    return [EdgeKey.from_relation(r) for r in rels], leak


def signal_for_item(delivered: bool, present: int, total: int, budget_respected: bool) -> float:
    s = 0.0
    if delivered:
        s += SIGNAL_FACT_PRESENCE if present >= 1 else SIGNAL_WASTED
    if total >= 2 and present == total:
        s += SIGNAL_MULTI
    if delivered and budget_respected:
        s += SIGNAL_BUDGET
    return max(-1.0, min(1.0, s))


def populate(
    ledger: UtilityLedger,
    snapshot_root: Path,
    bench_dir: Path,
    fp_path: Path,
) -> dict[str, Any]:
    train = {int(r["case"]): r for r in (json.loads(l) for l in
             (bench_dir / "graph_bench_longmemeval.jsonl").read_text().splitlines() if l.strip())}
    fp_rows = {int(r["case"]): r for r in (json.loads(l) for l in
               fp_path.read_text().splitlines() if l.strip())}
    stats = {"cases": 0, "items": 0, "paths": 0, "edges": 0, "leaks": 0, "skipped_items": []}
    for case in TRAIN_CASES:
        row = train.get(case)
        ground = fp_rows.get(case)
        if row is None or ground is None or "graph_off" not in ground["arms"]:
            continue
        items_ground = ground["arms"]["graph_off"]["items"]
        index = GraphIndex.load(GraphStore(snapshot_root / f"case_{case:02d}"))
        recall = GraphRecall(index, depth=DEPTH, top_k=TOP_K, max_paths=MAX_PATHS)
        result = recall.recall(row["question"])
        evidence = {item.memory_id: item for item in result.evidence}
        budget_respected = len(result.evidence) <= TOP_K
        stats["cases"] += 1
        for memory_id in items_ground:  # archive order
            item = evidence.get(memory_id)
            if item is None:
                stats["skipped_items"].append(f"{case}:{memory_id}")
                continue
            stats["items"] += 1
            i_f = items_ground[memory_id].get("item_facts") or {}
            present = int(i_f.get("present") or 0)
            total = int(i_f.get("total") or 0)
            delivered = bool(items_ground[memory_id].get("delivered") or False)
            signal = signal_for_item(delivered, present, total, budget_respected)
            paths = sorted(item.paths, key=lambda p: (-p.score, p.semantic_depth,
                            tuple(p.nodes), tuple(p.relations)))
            for p in paths[:MAX_PATHS_PER_EVIDENCE]:
                edges, leak = _path_composite_edges(p, index)
                if not edges:
                    continue
                stats["paths"] += 1
                if leak:
                    stats["leaks"] += 1
                for edge in edges:
                    ledger.record(
                        edge,
                        SIGNAL_LEAK if leak else signal,
                        query=row["question"],
                        path_ref=f"case_{case:02d}@{memory_id}",
                        evidenced=not leak,
                    )
                    stats["edges"] += 1
    return stats


def freeze_ledger(ledger: UtilityLedger, frozen_dir: Path, epoch: int = 0) -> dict[str, Any]:
    """Copy the ledger read-only with deterministic ts mask (audit-only)."""
    src_events = ledger.events_path
    src_utility = ledger.utility_path
    if not src_events.exists():
        raise SystemExit("MUTATION: populated ledger has no events.jsonl")
    out_dir = frozen_dir / "plasticity"
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, path in (("events.jsonl", src_events), ("utility.jsonl", src_utility)):
        out_lines = []
        for i, line in enumerate(path.read_text().splitlines(), start=1):
            if not line.strip():
                continue
            obj = json.loads(line)
            ts = f"2026-09-15T00:{i // 60:02d}:{i % 60:02d}+00:00"
            if name == "events.jsonl":
                obj["ts"] = ts
            else:
                obj["last_updated"] = ts
            out_lines.append(json.dumps(obj, ensure_ascii=False))
        (out_dir / name).write_text("\n".join(out_lines) + "\n", encoding="utf-8")
    poly_key = "policy_version"
    events_hash = sha1_file(out_dir / "events.jsonl")
    utility_hash = sha1_file(out_dir / "utility.jsonl")
    rows = sum(1 for _ in (out_dir / "utility.jsonl").read_text().splitlines()
               if _.strip())
    events = sum(1 for _ in (out_dir / "events.jsonl").read_text().splitlines()
                 if _.strip())
    return {"events": events, "rows": rows, "events_sha1": events_hash,
            "utility_sha1": utility_hash, poly_key: ledger.policy_version}


def budgeted_ids(items: list[dict[str, Any]], budget_items: int = BUDGET_ITEMS,
                 budget_chars: int = BUDGET_CHARS) -> list[str]:
    ids: list[str] = []
    chars = 0
    for it in items:
        cost = len(it["label"])
        if ids and (len(ids) >= budget_items or chars + cost > budget_chars):
            break
        ids.append(it["memory_id"])
        chars += cost
    return ids


def outcome_for_case(res: dict[str, Any]) -> dict[str, Any]:
    required = set(res["required_ids"])
    base_ids = budgeted_ids(res["base"]["evidence"])
    plastic_ids = budgeted_ids(res["plastic"]["evidence"])
    base_correct = required.issubset(set(base_ids))
    plastic_correct = required.issubset(set(plastic_ids))
    if base_correct and plastic_correct:
        cls = "stayed_correct"
    elif base_correct and not plastic_correct:
        cls = "regressed"
    elif not base_correct and plastic_correct:
        cls = "repaired"
    else:
        cls = "stayed_incorrect"
    net = {"repaired": 1, "regressed": -1}.get(cls, 0)
    return {
        "case": res["case"],
        "slice": res["slice"],
        "required_ids": sorted(required),
        "base_delivered": base_ids,
        "plastic_delivered": plastic_ids,
        "base_correct": base_correct,
        "plastic_correct": plastic_correct,
        "class": cls,
        "net": net,
        "base_chars": sum(len(it["label"]) for it in res["base"]["evidence"][:BUDGET_ITEMS]),
        "plastic_chars": sum(len(it["label"]) for it in res["plastic"]["evidence"][:BUDGET_ITEMS]),
        "max_energy_delta": res["diff"]["max_energy_delta"],
    }


def run_eval_iteration(cases: list[int], snapshot_root: Path, bench_dir: Path,
                       ledger: UtilityLedger) -> bytes:
    bench = dict(obs.load_bench(bench_dir))
    bench.update(_fake_bench_rows())
    rows = [obs.one_case(c, bench[c], snapshot_root, ledger) for c in cases]
    return b"".join(json.dumps(r, ensure_ascii=False, sort_keys=True).encode("utf-8") + b"\n"
                    for r in rows)


_FAKE_BENCH: dict[int, dict[str, Any]] = {}


def _fake_bench_rows() -> dict[int, dict[str, Any]]:
    return dict(_FAKE_BENCH)


def classify(cases: list[int], snapshot_root: Path, bench_dir: Path,
             ledger: UtilityLedger) -> list[dict[str, Any]]:
    bench = dict(obs.load_bench(bench_dir))
    bench.update(_fake_bench_rows())
    outcomes = []
    for c in cases:
        res = obs.one_case(c, bench[c], snapshot_root, ledger)
        outcomes.append(outcome_for_case(res))
    return outcomes


def run_label(out: Path, snapshot_root: Path, bench_dir: Path,
              fp_path: Path, repeat: int = 2,
              eval_cases: list[int] | None = None,
              fake_bench: dict[int, dict[str, Any]] | None = None) -> dict[str, Any]:
    global _FAKE_BENCH
    if eval_cases is None:
        eval_cases = EVAL_CASES
    if fake_bench is not None:
        _FAKE_BENCH = fake_bench
    run_dir = out
    run_dir.mkdir(parents=True, exist_ok=True)

    # 1. populate into a fresh ledger store
    source = run_dir / "ledger_source"
    if source.exists():
        shutil.rmtree(source)
    ledger = UtilityLedger(source, policy_version="p0")
    pop_stats = populate(ledger, snapshot_root, bench_dir, fp_path)
    ledger_store = ledger.dir

    # 2. freeze the ledger (deterministic ts mask), read-only copy
    frozen = run_dir / "ledger_frozen"
    if frozen.exists():
        shutil.rmtree(frozen)
    frozen_meta = freeze_ledger(ledger, frozen)
    frozen_ledger = UtilityLedger(frozen)

    # mutation guard over snapshot + frozen ledger during evaluation
    guarded_paths = [snapshot_root, frozen]
    before = _guard_state(guarded_paths)

    # 3. negative control: same eval with an empty ledger
    empty = UtilityLedger(run_dir / "ledger_empty", policy_version="p0")
    empty.reset()
    neg_iters = []
    for n in range(1, repeat + 1):
        blob = run_eval_iteration(eval_cases, snapshot_root, bench_dir, empty)
        neg_iters.append(sha1_bytes(blob))
        (run_dir / f"negative_iter{n}.jsonl").write_bytes(blob)

    # 4. shadow eval with the frozen ledger
    eval_iters = []
    for n in range(1, repeat + 1):
        blob = run_eval_iteration(eval_cases, snapshot_root, bench_dir, frozen_ledger)
        eval_iters.append(sha1_bytes(blob))
        (run_dir / f"shadow_iter{n}.jsonl").write_bytes(blob)

    if not _check_guard(before, guarded_paths):
        print("MUTATION GUARD TRIPPED — shadow wrote outside its artifacts", file=sys.stderr)
        sys.exit(2)

    # 5. classify the paired outcomes
    outcomes = classify(eval_cases, snapshot_root, bench_dir, frozen_ledger)
    counts: dict[str, int] = {}
    for o in outcomes:
        counts[o["class"]] = counts.get(o["class"], 0) + 1
    net = sum(o["net"] for o in outcomes)
    changed = sum(1 for o in outcomes if o["net"] != 0)

    manifest = {
        "run_id": f"plasticity_u42_shadow:{run_dir.name}",
        "git_commit": os.popen("git rev-parse HEAD 2>/dev/null").read().strip() or "unknown",
        "identity": {
            "snapshot_root": str(snapshot_root),
            "bench_dir": str(bench_dir),
            "train_cases": list(TRAIN_CASES),
            "eval_cases": eval_cases,
            "disjoint": len(set(TRAIN_CASES) & set(EVAL_CASES)) == 0,
            "config": {"depth": DEPTH, "top_k": TOP_K, "max_paths": MAX_PATHS,
                       "max_paths_per_evidence": MAX_PATHS_PER_EVIDENCE,
                       "budget_items": BUDGET_ITEMS, "budget_chars": BUDGET_CHARS,
                       "weight_utility": WEIGHT_UTILITY,
                       "hop_cost_observe": HOP_COST_OBSERVE},
        },
        "policy": {"lambda": 0.01, "eta": 0.10, "clip": 1.0, "k": 5.0,
                   "hop_cost": 0.15, "w_u": 0.5,
                   "signals": {"fact_presence": SIGNAL_FACT_PRESENCE,
                               "wasted_context": SIGNAL_WASTED,
                               "multi_evidence_complete": SIGNAL_MULTI,
                               "budget_respected": SIGNAL_BUDGET,
                               "cross_document_leak": SIGNAL_LEAK}},
        "population": pop_stats,
        "ledger_frozen": frozen_meta,
        "negative_control": {
            "iterations_sha1": neg_iters,
            "deterministic": len(set(neg_iters)) == 1,
            **({"matches_run1": neg_iters[0] == P1_RUN1_ITER_SHA1, "p1_run1_sha1": P1_RUN1_ITER_SHA1}
               if neg_iters else {}),
        },
        "shadow_eval": {
            "iterations_sha1": eval_iters,
            "deterministic": len(set(eval_iters)) == 1,
        },
        "outcome": {"counts": counts, "net": net, "changed_cases": changed, "per_case": outcomes},
    }
    (run_dir / "run_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n",
                                               encoding="utf-8")
    _write_summary(run_dir, manifest)
    return manifest


def _guard_state(paths: list[Path]) -> dict[str, Any]:
    state: dict[str, Any] = {}
    for p in paths:
        state[str(p.resolve())] = sorted((str(f.relative_to(p)), f.stat().st_size)
                                         for f in p.rglob("*") if f.is_file())
    return state


def _check_guard(before: dict[str, Any], paths: list[Path]) -> bool:
    now = _guard_state(paths)
    return now == before


def _write_summary(run_dir: Path, manifest: dict[str, Any]) -> None:
    lines = [
        "# plasticity P2 shadow — populated-ledger evaluation on U4.2",
        "",
        f"- run: `{manifest['run_id']}`",
        f"- git: `{manifest['git_commit']}`",
        f"- train pool (ledger): cases {manifest['identity']['train_cases'][0]}–{manifest['identity']['train_cases'][-1]} "
        f"(disjoint from eval: {manifest['identity']['disjoint']})",
        f"- eval set: cases {manifest['identity']['eval_cases'][0]}–{manifest['identity']['eval_cases'][-1]} "
        f"({len(manifest['identity']['eval_cases'])} cases)",
        f"- population: {json.dumps(manifest['population'], ensure_ascii=False)}",
        f"- ledger_frozen: {json.dumps(manifest['ledger_frozen'], ensure_ascii=False)}",
        f"- negative control (empty ledger): deterministic="
        f"{manifest['negative_control']['deterministic']} "
        f"matches_run1={manifest['negative_control'].get('matches_run1')}",
        f"- shadow eval determinism (shrun repeat): {manifest['shadow_eval']['deterministic']}",
        "",
        "| case | slice | class | net | base correct | plastic correct | Δchars | max ΔE |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for o in manifest["outcome"]["per_case"]:
        lines.append(
            f"| {o['case']} | {o['slice']} | {o['class']} | {o['net']:+d} "
            f"| {'Y' if o['base_correct'] else 'N'} "
            f"| {'Y' if o['plastic_correct'] else 'N'} "
            f"| {o['plastic_chars'] - o['base_chars']:+d} "
            f"| {o['max_energy_delta']:.4f} |"
        )
    counts = manifest["outcome"]["counts"]
    lines += [
        "",
        f"**classes: {json.dumps(counts, sort_keys=True)}**",
        "",
        f"**net = repaired − regressed = {manifest['outcome']['net']:+d} "
        f"({manifest['outcome']['changed_cases']}/30 cases changed)**",
        "",
        "Promotion (pre-registered §12.9): requires net ≥ +3 — and covers only",
        "the order/budget change caused by the frozen ledger on an identical payload.",
    ]
    (run_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="P2 shadow harness (populate → freeze → evaluate)")
    ap.add_argument("--snapshots", default="eval/graph_out/graphs/longmemeval")
    ap.add_argument("--bench-dir", default="eval/graph_out")
    ap.add_argument("--fact-presence", default="eval/graph_out/fact_presence_longmemeval.jsonl")
    ap.add_argument("--out", default="eval/results/plasticity_u42_shadow")
    ap.add_argument("--repeat", type=int, default=2)
    ap.add_argument("--fake", action="store_true", help="deterministic self-check under /tmp")
    args = ap.parse_args()

    if args.fake:
        return fake_self_check()

    snapshot_root = Path(args.snapshots)
    bench_dir = Path(args.bench_dir)
    fp_path = Path(args.fact_presence)
    out_root = Path(args.out)

    manifests = []
    per_case_seen: list[dict[str, Any]] = []
    for label in ("A", "B"):
        m = run_label(out_root / f"run{label}", snapshot_root, bench_dir, fp_path,
                      repeat=max(1, args.repeat))
        manifests.append(m)
        per_case_seen.append([(o["case"], o["class"], o["net"]) for o in m["outcome"]["per_case"]])

    rep = {
        "replication": {
            "frozen_sha1_equal": (manifests[0]["ledger_frozen"]["events_sha1"]
                                  == manifests[1]["ledger_frozen"]["events_sha1"])
                              and (manifests[0]["ledger_frozen"]["utility_sha1"]
                                   == manifests[1]["ledger_frozen"]["utility_sha1"]),
            "eval_iter_equal": (manifests[0]["shadow_eval"]["iterations_sha1"]
                                == manifests[1]["shadow_eval"]["iterations_sha1"]),
            "classification_equal": per_case_seen[0] == per_case_seen[1],
            "negative_matches_p1": all(
                m["negative_control"].get("matches_run1") for m in manifests),
        },
        "runs": [m["run_id"] for m in manifests],
        "nets": [m["outcome"]["net"] for m in manifests],
        "counts": [m["outcome"]["counts"] for m in manifests],
    }
    (out_root / "replication_manifest.json").write_text(json.dumps(rep, indent=2) + "\n",
                                                        encoding="utf-8")
    print(f"shadow: runs={[m['run_id'] for m in manifests]} "
          f"nets={rep['nets']} replication={rep['replication']}")
    return 0


def fake_self_check() -> int:
    import tempfile

    root = Path(tempfile.mkdtemp(prefix="pl-shadow-fake-"))
    snap = root / "graphs"
    bench_dir = root / "bench"
    fp_path = root / "fact_presence_longmemeval.jsonl"
    bench_dir.mkdir()
    train_rows = []
    fp_rows = []
    for case_no, q in ((0, "who managed Alpha project"), (1, "who owns Beta")):
        store = GraphStore(snap / f"case_{case_no:02d}")
        store.add_entity("Alpha", "project", "M0001", entity_id="E0001")
        store.add_entity("Alice", "person", "M0002", entity_id="E0002")
        store.add_entity("Beta", "project", "M0003", entity_id="E0003")
        store.add_entity("Gabriel", "person", "M0004", entity_id="E0004")
        store.add_relation(source="E0001", target="E0002", relation="managed",
                           memory_id="M0002", confidence=0.9, relation_id="R0001")
        store.add_relation(source="E0001", target="E0003", relation="related_to",
                           memory_id="M0003", confidence=0.7, relation_id="R0002")
        store.add_relation(source="E0003", target="E0004", relation="owned_by",
                           memory_id="M0004", confidence=0.6, relation_id="R0003")
        store.add_mention(memory_id="M0001", entity_id="E0001", confidence=0.8)
        train_rows.append({"case": case_no, "question": q, "gold": "",
                           "required_ids": ["M0002"]})
        fp_rows.append({"case": case_no, "arms": {"graph_off": {
            "items": {"M0002": {"delivered": True,
                                "item_facts": {"total": 2, "present": 2}}}}}})
    (bench_dir / "graph_bench_longmemeval.jsonl").write_text(
        "\n".join(json.dumps(r) for r in train_rows) + "\n", encoding="utf-8")
    (fp_path).write_text("\n".join(json.dumps(r) for r in fp_rows) + "\n", encoding="utf-8")
    # eval bench: same shape, disjoint case ids — fake uses synthetic ids 50/51
    eval_rows = [{"case": 50, "slice": "fake", "cat": "fake",
                  "question": "who owns the future",
                  "gold": "", "required_ids": ["M0004"]},
                 {"case": 51, "slice": "fake", "cat": "fake",
                  "question": "who manages Alpha again",
                  "gold": "", "required_ids": ["M0002"]}]
    for slice_id in ("u3a", "u3b"):
        (bench_dir / f"graph_bench_longmemeval_{slice_id}.jsonl").write_text(
            "\n".join(json.dumps(r) for r in eval_rows) + "\n", encoding="utf-8")

    out = root / "out"
    m = run_label(out / "runA", snap, bench_dir, fp_path, repeat=2,
                  eval_cases=[50, 51], fake_bench={r["case"]: r for r in eval_rows})
    ledger = UtilityLedger(out / "runA" / "ledger_frozen")
    ok_rows = ledger.rows() and m["population"]["edges"] > 0
    ok_neg = m["negative_control"]["deterministic"]
    ok_eval = m["shadow_eval"]["deterministic"]
    classes = set(o["class"] for o in m["outcome"]["per_case"])
    ok_class = "repaired" in classes or "stayed_correct" in classes or "stayed_incorrect" in classes
    print(f"fake: edges={m['population']['edges']} ledger_rows={len(ledger.rows())} "
          f"neg_det={ok_neg} eval_det={ok_eval} classes={sorted(classes)} "
          f"net={m['outcome']['net']}")
    return 0 if (ok_rows and ok_neg and ok_eval and ok_class) else 1


if __name__ == "__main__":
    sys.exit(main())