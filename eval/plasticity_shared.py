#!/usr/bin/env python3
"""P2b shared-graph harness — populated ledger evaluating the ONE shared graph.

Substrate:      eval/plasticity_fixtures/u42_shared/  (committed, see
                eval/gen_graph_shared.py — deterministic seed, single GraphStore,
                mechanical gold, region split trained vs unexposed).
Pre-registration: docs/PLASTICITY_V1.md §13 (frozen; decisions: 2026-09-14
                search pool recall_top_k=32, delivery budget unchanged §12.5 =
                top 8 items / 4000 chars, shadow targets on trained edges).

Pipeline per run label (A and B, both from scratch):

1. POPULATE (mechanical, no eval label): replay deterministic recall per TRAIN
   qid over the SHARED graph, and per delivered item in the ground record the
   frozen composite signal (§12.3) on every edge of its retained candidate
   paths (≤ max_paths_per_evidence=3 by base score).
2. FREEZE: copy the ledger read-only with a deterministic ts mask (audit-only),
   sha1 recorded in the manifest.
3. CLASSIFY EXPOSURE (BEFORE seeing any outcome): for each EVAL qid, „exposed“ ⇔
   its search-space EdgeKey set intersects the frozen ledger keys (≥1 learned
   edge); „unexposed“ ⇔ empty intersection. Deterministic, mechanical, written
   before evaluation — never after outcomes are known.
4. EVALUATE (shadow): frozen ledger adjusts ranking by energy E = D − w_u·U;
   base arm = score ranking. Per-case outcome uses the §12.5 budgeted payload
   (top 8 items / 4000 chars over the 32-candidate pool); correct ⇔ required ⊆
   delivered.
5. CLASSIFY results: repaired / regressed / stayed-correct / stayed-incorrect ⇒
   net = repaired − regressed. PRIMARY metric = net over EXPOSED cases; TOTAL
   net also reported (§13). Unexposed must remain unchanged (negative control).
6. NEGATIVE CONTROL: same eval with an empty ledger reproduces the base ranking
   byte-identically (0 changed) and every unexposed case is unchanged.
7. REPLICATE: runA and runB must produce byte-identical frozen ledger (sha1),
   identical exposure classification, identical eval iterations and identical
   per-case classification (§12.8 discipline).

Nothing here runs an LLM or writes outside ``--out`` (mutation guard, exit 2).
The graph/ledger directories are read-only during evaluation.

Expected usage:

    PYTHONPATH=src python3 eval/plasticity_shared.py \
        --fixtures eval/plasticity_fixtures/u42_shared \
        --out eval/results/plasticity_u42_shared

    PYTHONPATH=src python3 eval/plasticity_shared.py --fake   # self-check
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
    WEIGHT_UTILITY,
    EdgeKey,
    NavPath,
    UtilityLedger,
    shrink,
)

import plasticity_observe as obs

DEPTH = obs.DEPTH
RECALL_TOP_K = 32                      # §13 search candidate pool (decision 2026-09-14)
MAX_PATHS = obs.MAX_PATHS
MAX_PATHS_PER_EVIDENCE = 3             # frozen search limit (§12.3, unchanged)
BUDGET_ITEMS = 8                       # §12.5 delivery budget (unchanged)
BUDGET_CHARS = 4000                    # §12.5 delivery budget (unchanged)

SIGNAL_FACT_PRESENCE = 0.60
SIGNAL_WASTED = -0.40
SIGNAL_MULTI = 0.30
SIGNAL_BUDGET = 0.10
SIGNAL_LEAK = -0.60


def sha1_bytes(blob: bytes) -> str:
    return hashlib.sha1(blob).hexdigest()


def sha1_file(path: Path) -> str:
    return sha1_bytes(path.read_bytes())


def load_bench(fixtures: Path) -> dict[int, dict[str, Any]]:
    rows = {}
    for line in (fixtures / "bench.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        rows[int(r["qid"])] = r
    return rows


def load_ground(fixtures: Path) -> dict[int, dict[str, Any]]:
    rows = {}
    for line in (fixtures / "ground.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        rows[int(r["qid"])] = r
    return rows


def _path_composite_edges(path, index: GraphIndex) -> tuple[list[EdgeKey], bool]:
    rels = [index.relations[rid] for rid in path.relations if rid in index.relations]
    if not rels:
        return [], False
    leak = len({(r.source_document or "").strip() for r in rels if (r.source_document or "").strip()}) > 1
    return [EdgeKey.from_relation(r) for r in rels], leak


def _path_edge_keys(path, index: GraphIndex) -> list[EdgeKey]:
    return [EdgeKey.from_relation(index.relations[rid])
            for rid in path.relations if rid in index.relations]


def _search_space_edge_keys(result, index: GraphIndex) -> set[str]:
    """All EdgeKey strings reachable by the deterministic search for a query."""
    keys: set[str] = set()
    for item in result.evidence:
        for p in item.paths:
            for k in _path_edge_keys(p, index):
                keys.add(k.to_key())
    return keys


def signal_for_item(delivered: bool, present: int, total: int, budget_respected: bool) -> float:
    s = 0.0
    if delivered:
        s += SIGNAL_FACT_PRESENCE if present >= 1 else SIGNAL_WASTED
    if total >= 2 and present == total:
        s += SIGNAL_MULTI
    if delivered and budget_respected:
        s += SIGNAL_BUDGET
    return max(-1.0, min(1.0, s))


def populate(ledger: UtilityLedger, fixtures: Path, graph_dir: Path) -> dict[str, Any]:
    bench = load_bench(fixtures)
    fp_rows = load_ground(fixtures)
    index = GraphIndex.load(GraphStore(graph_dir))
    recall = GraphRecall(index, depth=DEPTH, top_k=RECALL_TOP_K, max_paths=MAX_PATHS)
    stats = {"qids": 0, "items": 0, "paths": 0, "edges": 0, "leaks": 0, "skipped_items": []}
    for qid, row in sorted((q, r) for q, r in bench.items() if r["split"] == "train"):
        ground = fp_rows.get(qid)
        if ground is None or "graph_off" not in ground["arms"]:
            continue
        items_ground = ground["arms"]["graph_off"]["items"]
        result = recall.recall(row["question"])
        evidence = {item.memory_id: item for item in result.evidence}
        budget_respected = len(result.evidence) <= BUDGET_ITEMS
        stats["qids"] += 1
        for memory_id in items_ground:
            item = evidence.get(memory_id)
            if item is None:
                stats["skipped_items"].append(f"{qid}:{memory_id}")
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
                        path_ref=f"qid_{qid}@{memory_id}",
                        evidenced=not leak,
                    )
                    stats["edges"] += 1
    return stats


def freeze_ledger(ledger: UtilityLedger, frozen_dir: Path, epoch: int = 0) -> dict[str, Any]:
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
    return {"events": sum(1 for _ in (out_dir / "events.jsonl").read_text().splitlines() if _.strip()),
            "rows": sum(1 for _ in (out_dir / "utility.jsonl").read_text().splitlines() if _.strip()),
            "events_sha1": sha1_file(out_dir / "events.jsonl"),
            "utility_sha1": sha1_file(out_dir / "utility.jsonl"),
            "policy_version": ledger.policy_version}


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


def _path_utility(path, index: GraphIndex, ledger: UtilityLedger) -> float:
    rows = [ledger.get(EdgeKey.from_relation(r)) for rid in path.relations
            if (r := index.relations.get(rid)) is not None]
    if not rows:
        return 0.0
    return sum(shrink(row.utility, row.observations) for row in rows) / len(rows)


def _item_energy(item, index: GraphIndex, ledger: UtilityLedger) -> float:
    utilities = [_path_utility(p, index, ledger) for p in item.paths if p.relations]
    learned = sum(utilities) / len(utilities) if utilities else 0.0
    return (1.0 - item.score) - WEIGHT_UTILITY * learned


def one_case(qid: int, row: dict[str, Any], graph_dir: Path,
             ledger: UtilityLedger) -> dict[str, Any]:
    index = GraphIndex.load(GraphStore(graph_dir))
    recall = GraphRecall(index, depth=DEPTH, top_k=RECALL_TOP_K, max_paths=MAX_PATHS)
    result = recall.recall(row["question"])

    base_items = result.evidence
    plastic_items = [(item, _item_energy(item, index, ledger)) for item in base_items]
    plastic_items.sort(key=lambda ie: (ie[1], -ie[0].score, ie[0].memory_id))

    def render(items) -> dict[str, Any]:
        out_items = []
        for item in items:
            out_items.append({
                "memory_id": item.memory_id,
                "score": round(item.score, 4),
                "via": item.via,
                "entities": list(item.entity_ids),
                "relations": list(item.relation_ids),
                "label": item.label,
                "paths": [{"nodes": p.nodes, "relations": p.relations,
                           "score": round(p.score, 4)} for p in item.paths],
            })
        return out_items

    base_rendered = render(base_items)
    plastic_rendered = render([ie[0] for ie in plastic_items])
    return {
        "qid": qid,
        "split": row["split"],
        "region": row["region"],
        "question": row["question"],
        "required_ids": sorted(set(row["required_ids"])),
        "seeds": list(result.seeds),
        "seed_labels": list(result.seed_labels),
        "paths_considered": result.paths_considered,
        "ledger": {"policy_version": ledger.policy_version, "rows": len(ledger.rows())},
        "base": {"evidence": base_rendered},
        "plastic": {"evidence": plastic_rendered},
    }


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
    return {
        "qid": res["qid"],
        "required_ids": sorted(required),
        "base_delivered": base_ids,
        "plastic_delivered": plastic_ids,
        "base_correct": base_correct,
        "plastic_correct": plastic_correct,
        "class": cls,
        "net": {"repaired": 1, "regressed": -1}.get(cls, 0),
        "base_chars": sum(len(it["label"]) for it in res["base"]["evidence"][:BUDGET_ITEMS]),
        "plastic_chars": sum(len(it["label"]) for it in res["plastic"]["evidence"][:BUDGET_ITEMS]),
        "evidence_order_changed": [i["memory_id"] for i in res["base"]["evidence"]] !=
                                  [i["memory_id"] for i in res["plastic"]["evidence"]],
        "max_energy_delta": res.get("max_energy_delta", 0.0),
    }


def classify_exposure(eval_rows: list[dict[str, Any]], graph_dir: Path,
                      ledger: UtilityLedger) -> list[dict[str, Any]]:
    """Mechanical exposure classification — runs BEFORE any outcome is computed.

    «exposed» ⇔ the query's search-space EdgeKey set intersects the frozen
    ledger keys (≥1 learned edge). Written to a ledger-independent artifact so
    the classification is auditable without any outcome knowledge.
    """
    index = GraphIndex.load(GraphStore(graph_dir))
    recall = GraphRecall(index, depth=DEPTH, top_k=RECALL_TOP_K, max_paths=MAX_PATHS)
    ledger_keys = set(ledger.rows())
    out: list[dict[str, Any]] = []
    for row in eval_rows:
        result = recall.recall(row["question"])
        space = _search_space_edge_keys(result, index)
        shared = sorted(space & ledger_keys)
        out.append({
            "qid": row["qid"],
            "exposed": len(shared) > 0,
            "shared_edge_keys": len(shared),
            "search_space_edges": len(space),
            "ledger_keys": len(ledger_keys),
        })
    return out


def run_label(out: Path, fixtures: Path, repeat: int = 2,
              eval_rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    graph_dir = fixtures / "graph"
    bench = load_bench(fixtures)
    if eval_rows is None:
        eval_rows = [r for r in bench.values() if r["split"] == "eval"]
    eval_rows = sorted(eval_rows, key=lambda r: int(r["qid"]))

    run_dir = out
    run_dir.mkdir(parents=True, exist_ok=True)

    # 1. populate into a fresh ledger store
    source = run_dir / "ledger_source"
    if source.exists():
        shutil.rmtree(source)
    ledger = UtilityLedger(source, policy_version="p0")
    pop_stats = populate(ledger, fixtures, graph_dir)

    # 2. freeze the ledger (deterministic ts mask), read-only copy
    frozen = run_dir / "ledger_frozen"
    if frozen.exists():
        shutil.rmtree(frozen)
    frozen_meta = freeze_ledger(ledger, frozen)
    frozen_ledger = UtilityLedger(frozen)

    # 3. exposure classification (BEFORE evaluation outcomes)
    exposure = classify_exposure(eval_rows, graph_dir, frozen_ledger)
    (run_dir / "exposure.jsonl").write_text(
        "\n".join(json.dumps(e, ensure_ascii=False, sort_keys=True) for e in exposure) + "\n",
        encoding="utf-8")
    exposure_by_qid = {e["qid"]: e for e in exposure}

    # mutation guard over fixture + frozen ledger during evaluation
    guarded_paths = [fixtures, frozen]
    before = _guard_state(guarded_paths)

    # 4. negative control: same eval with an empty ledger
    empty = UtilityLedger(run_dir / "ledger_empty", policy_version="p0")
    empty.reset()
    neg_iters = []
    neg_matches_base = True
    for n in range(1, repeat + 1):
        res_rows = [one_case(int(r["qid"]), r, graph_dir, empty) for r in eval_rows]
        blob = b"".join(json.dumps(r, ensure_ascii=False, sort_keys=True).encode("utf-8") + b"\n"
                        for r in res_rows)
        neg_iters.append(sha1_bytes(blob))
        (run_dir / f"negative_iter{n}.jsonl").write_bytes(blob)
        if not all(r["plastic"]["evidence"] == r["base"]["evidence"] for r in res_rows):
            neg_matches_base = False

    # 5. shadow eval with the frozen ledger
    eval_iters = []
    for n in range(1, repeat + 1):
        res_rows = [one_case(int(r["qid"]), r, graph_dir, frozen_ledger) for r in eval_rows]
        blob = b"".join(json.dumps(r, ensure_ascii=False, sort_keys=True).encode("utf-8") + b"\n"
                        for r in res_rows)
        eval_iters.append(sha1_bytes(blob))
        (run_dir / f"shadow_iter{n}.jsonl").write_bytes(blob)

    if not _check_guard(before, guarded_paths):
        print("MUTATION GUARD TRIPPED — shadow wrote outside its artifacts", file=sys.stderr)
        sys.exit(2)

    # 6. classify outcomes (NOW — after exposure was already frozen)
    outcomes = [outcome_for_case(one_case(int(r["qid"]), r, graph_dir, frozen_ledger))
                for r in eval_rows]

    def counts(subset: list[dict[str, Any]]) -> dict[str, int]:
        c: dict[str, int] = {}
        for o in subset:
            c[o["class"]] = c.get(o["class"], 0) + 1
        return c

    def net(subset: list[dict[str, Any]]) -> int:
        return sum(o["net"] for o in subset)

    exposed_outcomes = [o for o in outcomes if exposure_by_qid[o["qid"]]["exposed"]]
    unexposed_outcomes = [o for o in outcomes if not exposure_by_qid[o["qid"]]["exposed"]]
    unexposed_changed = [o for o in unexposed_outcomes
                         if o["net"] != 0 or o["evidence_order_changed"]]

    manifest = {
        "run_id": f"plasticity_u42_shared:{run_dir.name}",
        "git_commit": os.popen("git rev-parse HEAD 2>/dev/null").read().strip() or "unknown",
        "identity": {
            "fixtures": str(fixtures),
            "fixture_manifest": sha1_file(fixtures / "manifest.json"),
            "graph_sha1": json.loads((fixtures / "manifest.json").read_text())["graph"]["sha1"],
            "eval_qids": [int(r["qid"]) for r in eval_rows],
            "config": {"depth": DEPTH, "recall_top_k": RECALL_TOP_K,
                       "max_paths": MAX_PATHS, "max_paths_per_evidence": MAX_PATHS_PER_EVIDENCE,
                       "budget_items": BUDGET_ITEMS, "budget_chars": BUDGET_CHARS,
                       "weight_utility": WEIGHT_UTILITY},
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
        "exposure": {
            "classified_before_outcomes": True,
            "per_case": exposure,
            "exposed": sum(1 for e in exposure if e["exposed"]),
            "unexposed": sum(1 for e in exposure if not e["exposed"]),
        },
        "negative_control": {
            "iterations_sha1": neg_iters,
            "deterministic": len(set(neg_iters)) == 1,
            "matches_base": neg_matches_base,
        },
        "shadow_eval": {"iterations_sha1": eval_iters,
                        "deterministic": len(set(eval_iters)) == 1},
        "outcome": {
            "exposed": {"counts": counts(exposed_outcomes),
                        "net": net(exposed_outcomes),
                        "changed": sum(1 for o in exposed_outcomes if o["net"] != 0),
                        "per_case": exposed_outcomes},
            "unexposed": {"counts": counts(unexposed_outcomes),
                          "net": net(unexposed_outcomes),
                          "changed": len(unexposed_changed),
                          "per_case": unexposed_outcomes},
            "total": {"counts": counts(outcomes), "net": net(outcomes),
                      "changed": sum(1 for o in outcomes if o["net"] != 0),
                      "per_case": outcomes},
        },
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
    return _guard_state(paths) == before


def _write_summary(run_dir: Path, manifest: dict[str, Any]) -> None:
    exp = manifest["outcome"]["exposed"]
    une = manifest["outcome"]["unexposed"]
    tot = manifest["outcome"]["total"]
    lines = [
        "# plasticity P2b shared-graph — populated-ledger evaluation on one graph",
        "",
        f"- run: `{manifest['run_id']}`",
        f"- git: `{manifest['git_commit']}`",
        f"- fixtures: `{manifest['identity']['fixtures']}`"
        f" (graph sha1 `{manifest['identity']['graph_sha1']}`)",
        f"- eval qids: {manifest['identity']['eval_qids'][0]}–{manifest['identity']['eval_qids'][-1]} "
        f"({len(manifest['identity']['eval_qids'])} cases)",
        f"- config: {json.dumps(manifest['identity']['config'], ensure_ascii=False)}",
        f"- population: {json.dumps(manifest['population'], ensure_ascii=False)}",
        f"- ledger frozen: {json.dumps(manifest['ledger_frozen'], ensure_ascii=False)}",
        f"- exposure (classified BEFORE outcomes): exposed="
        f"{manifest['exposure']['exposed']}, unexposed={manifest['exposure']['unexposed']}",
        f"- negative control: deterministic={manifest['negative_control']['deterministic']} "
        f"matches_base={manifest['negative_control']['matches_base']} "
        f"unexposed_changed={une['changed']}",
        f"- shadow determinism: {manifest['shadow_eval']['deterministic']}",
        "",
        "## Exposed (primary metric)",
        "",
        "| qid | class | net | base correct | plastic correct | Δchars | order changed |",
        "|---|---|---|---|---|---|---|",
    ]
    for o in exp["per_case"]:
        lines.append(
            f"| {o['qid']} | {o['class']} | {o['net']:+d} "
            f"| {'Y' if o['base_correct'] else 'N'} "
            f"| {'Y' if o['plastic_correct'] else 'N'} "
            f"| {o['plastic_chars'] - o['base_chars']:+d} "
            f"| {'Y' if o['evidence_order_changed'] else 'N'} |"
        )
    lines.append("")
    lines.append(f"**exposed: {json.dumps(exp['counts'], sort_keys=True)} — "
                 f"net = {exp['net']:+d} ({exp['changed']})**")
    lines.append("")
    lines.append("## Unexposed (negative control)")
    lines.append("")
    lines.append(f"**unexposed: {json.dumps(une['counts'], sort_keys=True)} — "
                 f"changed = {une['changed']}** (must remain unchanged)")
    lines.append("")
    lines.append(f"**total: {json.dumps(tot['counts'], sort_keys=True)} — net = {tot['net']:+d}**")
    lines.append("")
    lines.append("Promotion (pre-registered §13): requires exposed net ≥ +3 (frozen from §12.9)")
    lines.append("— with unexposed unchanged, controls green, replication equal.")
    (run_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="P2b shared-graph harness")
    ap.add_argument("--fixtures", default="eval/plasticity_fixtures/u42_shared")
    ap.add_argument("--out", default="eval/results/plasticity_u42_shared")
    ap.add_argument("--repeat", type=int, default=2)
    ap.add_argument("--fake", action="store_true", help="deterministic self-check under /tmp")
    args = ap.parse_args()

    if args.fake:
        return fake_self_check()

    fixtures = Path(args.fixtures)
    out_root = Path(args.out)

    manifests = []
    per_case_seen: list[dict[str, Any]] = []
    for label in ("A", "B"):
        m = run_label(out_root / f"run{label}", fixtures, repeat=max(1, args.repeat))
        manifests.append(m)
        per_case_seen.append([(o["qid"], o["class"], o["net"])
                              for o in m["outcome"]["total"]["per_case"]])

    rep = {
        "replication": {
            "frozen_sha1_equal": (manifests[0]["ledger_frozen"]["events_sha1"]
                                  == manifests[1]["ledger_frozen"]["events_sha1"])
                              and (manifests[0]["ledger_frozen"]["utility_sha1"]
                                   == manifests[1]["ledger_frozen"]["utility_sha1"]),
            "eval_iter_equal": (manifests[0]["shadow_eval"]["iterations_sha1"]
                                == manifests[1]["shadow_eval"]["iterations_sha1"]),
            "exposure_equal": ((manifests[0]["exposure"]["exposed"],
                                manifests[0]["exposure"]["unexposed"])
                               == (manifests[1]["exposure"]["exposed"],
                                   manifests[1]["exposure"]["unexposed"])),
            "classification_equal": per_case_seen[0] == per_case_seen[1],
        },
        "runs": [m["run_id"] for m in manifests],
        "exposed_nets": [m["outcome"]["exposed"]["net"] for m in manifests],
        "total_nets": [m["outcome"]["total"]["net"] for m in manifests],
        "counts": [m["outcome"]["total"]["counts"] for m in manifests],
    }
    (out_root / "replication_manifest.json").write_text(json.dumps(rep, indent=2) + "\n",
                                                        encoding="utf-8")
    print(f"shared: runs={[m['run_id'] for m in manifests]} "
          f"exposed_nets={rep['exposed_nets']} total_nets={rep['total_nets']} "
          f"replication={rep['replication']}")
    return 0


def fake_self_check() -> int:
    import tempfile

    root = Path(tempfile.mkdtemp(prefix="pl-shared-fake-"))
    fixtures = root / "fixtures"
    graph_dir = fixtures / "graph"
    store = GraphStore(graph_dir)
    store.add_entity("Alpha", "project", "M0001", entity_id="E0001")
    store.add_entity("Alice", "person", "M0002", entity_id="E0002")
    store.add_entity("Beta", "project", "M0003", entity_id="E0003")
    store.add_entity("Gabriel", "person", "M0004", entity_id="E0004")
    store.add_entity("Gamma", "project", "M0005", entity_id="E0005")
    store.add_entity("Hugo", "person", "M0006", entity_id="E0006")
    store.add_relation(source="E0001", target="E0002", relation="managed",
                       memory_id="M0002", confidence=0.9, relation_id="R0001")
    store.add_relation(source="E0001", target="E0003", relation="related_to",
                       memory_id="M0003", confidence=0.7, relation_id="R0002")
    store.add_relation(source="E0003", target="E0004", relation="owned_by",
                       memory_id="M0004", confidence=0.6, relation_id="R0003")
    store.add_relation(source="E0005", target="E0006", relation="owned_by",
                       memory_id="M0006", confidence=0.6, relation_id="R0004")
    store.add_mention(memory_id="M0001", entity_id="E0001", confidence=0.8)
    # train (qid 1) teaches the managed edge; eval exposed (qid 2) asks the same edge
    bench = [
        {"qid": 1, "split": "train", "region": "trained", "fact": "Alpha##x",
         "question": "who managed the Alpha project?", "required_ids": ["M0002"]},
        {"qid": 2, "split": "eval", "region": "trained", "fact": "Alpha##x",
         "question": "who owns the Alpha project oversight?", "required_ids": ["M0002"]},
        {"qid": 3, "split": "eval", "region": "unexposed", "fact": "Gamma##x",
         "question": "who owns the Gamma project?", "required_ids": ["M0006"]},
    ]
    (fixtures / "bench.jsonl").write_text(
        "\n".join(json.dumps(r) for r in bench) + "\n", encoding="utf-8")
    # mechanical ground: qid1 delivered managed item (present), qid2/3 empty for fake
    ground = [
        {"qid": 1, "split": "train", "arms": {"graph_off": {"items": {
            "M0002": {"delivered": True, "item_facts": {"total": 1, "present": 1}}}}}},
        {"qid": 2, "split": "eval", "arms": {"graph_off": {"items": {}}}},
        {"qid": 3, "split": "eval", "arms": {"graph_off": {"items": {}}}},
    ]
    (fixtures / "ground.jsonl").write_text(
        "\n".join(json.dumps(r) for r in ground) + "\n", encoding="utf-8")
    (fixtures / "manifest.json").write_text(json.dumps({
        "graph": {"sha1": ""}, "bench": {}, "config": {}}) + "\n", encoding="utf-8")

    out = root / "out"
    m = run_label(out / "runA", fixtures, repeat=2,
                  eval_rows=[r for r in bench if r["split"] == "eval"])
    ok_pop = m["population"]["edges"] > 0
    ok_neg = m["negative_control"]["deterministic"]
    ok_eval = m["shadow_eval"]["deterministic"]
    ok_exp = m["exposure"]["exposed"] >= 1 and m["exposure"]["unexposed"] >= 1
    ok_une = m["outcome"]["unexposed"]["changed"] == 0
    ok_rep = m["negative_control"]["matches_base"]
    print(f"fake: edges={m['population']['edges']} exposed={m['exposure']['exposed']} "
          f"unexposed={m['exposure']['unexposed']} unexp_changed={m['outcome']['unexposed']['changed']} "
          f"neg_det={ok_neg} eval_det={ok_eval} matches_base={ok_rep} "
          f"exposed_net={m['outcome']['exposed']['net']}")
    return 0 if (ok_pop and ok_neg and ok_eval and ok_exp and ok_une and ok_rep) else 1


if __name__ == "__main__":
    sys.exit(main())