#!/usr/bin/env python3
"""P1 observe — shadow ranking comparison over frozen graph snapshots.

Replicates the deterministic graph-recall search space (read-only) and
computes, per case, the base ranking (score) vs a plastic ranking (energy
over the UtilityLedger, read-only). Nothing in the system — tape, graph,
evidence, recall, delivered results — is touched: the harness only reads
frozen snapshots and the ledger, and writes separated artifacts under ``--out``
with snapshot/config identifiers.

Energy (P1 operational definition, docs/PLASTICITY_V1.md §6/§11):

    E(path) = D − wᵤ · U_eff ,   D = 1 − base_score ,   H = R = 0 in P1

Base score already carries the hop penalty (0.85**(depth−1)); H/R enter live
ranking in later phases only by re-pre-registration. With an empty ledger
U_eff = 0 ⇒ the plastic ranking is byte-identical to the base ranking; any
difference is purely learned-nav driven.

Two invocations of the same case set must produce byte-identical artifacts
(determinism proof); the harness also guards that nothing under the snapshot or
ledger directories changed during the run.

Expected usage:

    PYTHONPATH=src python3 eval/plasticity_observe.py \
        --out eval/results/plasticity_u42_observe/run1

    PYTHONPATH=src python3 eval/plasticity_observe.py --fake   # self-check
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

from memory_machine.graph import GraphIndex, GraphStore
from memory_machine.graph_recall import GraphRecall
from memory_machine.graph_utility import (
    DEFAULT_SCOPE,
    WEIGHT_UTILITY,
    EdgeKey,
    NavPath,
    UtilityLedger,
    energy,
    shrink,
)

DEPTH = 2
TOP_K = 8
MAX_PATHS = 400
HOP_COST_OBSERVE = 0.0  # folded into base score in P1; see module docstring
SNAPSHOT_FILES = (
    "entities.jsonl",
    "relations.jsonl",
    "mentions.jsonl",
    "aliases.jsonl",
    "extracted.jsonl",
    "meta.json",
)
SLICES = (("u3a", range(12, 27)), ("u3b", range(27, 42)))


def sha1_digest(path: Path) -> str:
    h = hashlib.sha1()
    h.update(path.name.encode("utf-8", "replace"))
    h.update(path.read_bytes())
    return h.hexdigest()


def snapshot_identity(case_dir: Path) -> dict[str, Any]:
    rows = []
    digest = hashlib.sha1()
    for name in sorted(SNAPSHOT_FILES):
        path = case_dir / name
        if not path.exists():
            continue
        blob = path.read_bytes()
        digest.update(name.encode("utf-8", "replace"))
        digest.update(blob)
        rows.append({"file": name, "sha1": hashlib.sha1(blob).hexdigest()})
    return {"dir": case_dir.name, "content_sha1": digest.hexdigest(), "files": rows}


def load_bench(bench_dir: Path) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    for slice_id, _cases in SLICES:
        path = bench_dir / f"graph_bench_longmemeval_{slice_id}.jsonl"
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            out[int(row["case"])] = {
                "slice": slice_id,
                "question": row["question"],
                "gold": row.get("gold", ""),
                "required_ids": list(row.get("required_ids", [])),
                "cat": row.get("cat", ""),
            }
    return out


def _path_energy(path, index: GraphIndex, ledger: UtilityLedger) -> float:
    edges = [
        EdgeKey.from_relation(r)
        for rid in path.relations
        if (r := index.relations.get(rid)) is not None
    ]
    nav = NavPath(edges=tuple(edges), semantic_depth=path.semantic_depth)
    return energy(
        nav,
        query_distance=(1.0 - path.score),
        ledger=ledger,
        weight_utility=WEIGHT_UTILITY,
        hop_cost=HOP_COST_OBSERVE,
        risk_penalty=0.0,
    )


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


def one_case(
    case: int,
    row: dict[str, Any],
    snapshot_root: Path,
    ledger: UtilityLedger,
) -> dict[str, Any]:
    case_dir = snapshot_root / f"case_{case:02d}"
    index = GraphIndex.load(GraphStore(case_dir))
    recall = GraphRecall(index, depth=DEPTH, top_k=TOP_K, max_paths=MAX_PATHS)
    result = recall.recall(row["question"])

    flat_paths = list({id(p): p for p in (_p for item in result.evidence for _p in item.paths)}.values())
    paths = sorted(flat_paths, key=lambda p: (tuple(p.nodes), tuple(p.relations)))

    base_order = sorted(
        paths, key=lambda p: (-p.score, p.semantic_depth, tuple(p.nodes), tuple(p.relations))
    )
    scored = [(p, _path_energy(p, index, ledger)) for p in paths]
    plastic_order = sorted(
        scored,
        key=lambda pe: (pe[1], -pe[0].score, pe[0].semantic_depth, tuple(pe[0].nodes), tuple(pe[0].relations)),
    )

    base_items = result.evidence
    plastic_items = [
        (item, _item_energy(item, index, ledger)) for item in base_items
    ]
    plastic_items.sort(key=lambda ie: (ie[1], -ie[0].score, ie[0].memory_id))

    def render(items) -> dict[str, Any]:
        out_items = []
        for item in items:
            out_items.append(
                {
                    "memory_id": item.memory_id,
                    "score": round(item.score, 4),
                    "via": item.via,
                    "entities": list(item.entity_ids),
                    "relations": list(item.relation_ids),
                    "label": item.label,
                    "paths": [{"nodes": p.nodes, "relations": p.relations,
                               "score": round(p.score, 4)} for p in item.paths],
                }
            )
        return {"items": out_items,
                "delivered_ids": [i["memory_id"] for i in out_items],
                "budget_items": len(out_items),
                "budget_est_chars": sum(len(i["label"]) for i in out_items)}

    base_rendered = render(base_items)
    plastic_rendered = render([ie[0] for ie in plastic_items])
    base_paths = [
        {"nodes": p.nodes, "relations": p.relations, "score": round(p.score, 4),
         "energy": round(_path_energy(p, index, ledger), 4)} for p in base_order[:TOP_K]
    ]
    plastic_paths = [
        {"nodes": pe[0].nodes, "relations": pe[0].relations, "score": round(pe[0].score, 4),
         "energy": round(pe[1], 4)} for pe in plastic_order[:TOP_K]
    ]

    required = set(row["required_ids"])
    base_delivered = set(base_rendered["delivered_ids"])
    plastic_delivered = set(plastic_rendered["delivered_ids"])
    diff = {
        "paths_equal": [p["nodes"] for p in base_paths] == [p["nodes"] for p in plastic_paths],
        "path_order_equal": all(
            a["nodes"] == b["nodes"] and a["score"] == b["score"]
            for a, b in zip(base_paths, plastic_paths)
        ),
        "evidence_order_equal": base_rendered["delivered_ids"] == plastic_rendered["delivered_ids"],
        "targets_delivered_equal": sorted(base_delivered & required) == sorted(plastic_delivered & required),
        "targets_missing_equal": sorted(required - plastic_delivered) == sorted(required - base_delivered),
        "max_energy_delta": max(
            (abs(bp["energy"] - pp["energy"]) for bp, pp in zip(base_paths, plastic_paths)),
            default=0.0,
        ),
    }
    return {
        "case": case,
        "slice": row["slice"],
        "cat": row["cat"],
        "question": row["question"],
        "required_ids": sorted(required),
        "snapshot": snapshot_identity(case_dir),
        "seeds": list(result.seeds),
        "seed_labels": list(result.seed_labels),
        "paths_considered": result.paths_considered,
        "ledger": {"policy_version": ledger.policy_version, "rows": len(ledger.rows())},
        "base": {
            "paths": base_paths,
            "evidence": base_rendered["items"],
            "targets_delivered": sorted(base_delivered & required),
            "targets_missing": sorted(required - base_delivered),
            "budget_est_chars": base_rendered["budget_est_chars"],
            "budget_items": base_rendered["budget_items"],
        },
        "plastic": {
            "paths": plastic_paths,
            "evidence": plastic_rendered["items"],
            "targets_delivered": sorted(plastic_delivered & required),
            "targets_missing": sorted(required - plastic_delivered),
            "budget_est_chars": plastic_rendered["budget_est_chars"],
            "budget_items": plastic_rendered["budget_items"],
        },
        "diff": diff,
    }


def _ledger_id(ledger: UtilityLedger) -> dict[str, Any]:
    if not ledger.dir.exists():
        return {"policy_version": ledger.policy_version, "rows": 0, "sha1": "empty"}
    files = sorted(p for p in ledger.dir.iterdir() if p.is_file())
    digest = hashlib.sha1()
    for p in files:
        digest.update(p.name.encode("utf-8", "replace"))
        digest.update(p.read_bytes())
    return {"policy_version": ledger.policy_version, "rows": len(ledger.rows()),
            "files": [p.name for p in files], "sha1": digest.hexdigest()}


def mutation_guard(paths: list[Path]) -> tuple[dict[str, Any], list[Path]]:
    state: dict[str, Any] = {}
    for p in paths:
        key = str(p.resolve())
        entries = []
        for f in sorted(p.rglob("*")):
            entries.append((f.name, f.stat().st_size, f.stat().st_mtime_ns))
        state[key] = entries
    return state, list(paths)


def check_no_mutation(before: dict[str, Any], paths: list[Path]) -> bool:
    for p in paths:
        entries = []
        for f in sorted(p.rglob("*")):
            entries.append((f.name, f.stat().st_size, f.stat().st_mtime_ns))
        if entries != before.get(str(p.resolve()), []):
            return False
    return True


def run(cases: list[int], snapshot_root: Path, bench_dir: Path, ledger: UtilityLedger,
        out: Path, repeat: int = 2) -> list[dict[str, Any]]:
    bench = load_bench(bench_dir)
    out.mkdir(parents=True, exist_ok=True)
    guarded = [snapshot_root, ledger.dir] if ledger.dir.exists() else [snapshot_root]
    before, guards = mutation_guard(guarded)
    identity = {"snapshot_root": str(snapshot_root), "bench_dir": str(bench_dir),
                "ledger": _ledger_id(ledger), "config": {"depth": DEPTH, "top_k": TOP_K,
                "max_paths": MAX_PATHS, "weight_utility": WEIGHT_UTILITY,
                "hop_cost_observe": HOP_COST_OBSERVE}}
    iterations: list[str] = []
    for run_no in range(1, repeat + 1):
        rows = [one_case(c, bench[c], snapshot_root, ledger) for c in cases]
        blob = "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows)
        iterations.append(hashlib.sha1(blob.encode("utf-8")).hexdigest())
        (out / f"observer_iter{run_no}.jsonl").write_text(blob, encoding="utf-8")
    deterministic = len(set(iterations)) == 1
    if not check_no_mutation(before, guards):
        print("MUTATION GUARD TRIPPED — observer wrote outside its own artifacts", file=sys.stderr)
        sys.exit(2)
    manifest = {"run_id": f"plasticity_u42_observe:{out.name}", "git_commit": os.popen(
        "git rev-parse HEAD 2>/dev/null").read().strip() or "unknown",
        "identity": identity, "deterministic": deterministic,
        "iterations_sha1": iterations}
    (out / "run_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return [{"deterministic": deterministic, "iterations_sha1": iterations}, identity, rows]


def _write_summary(out: Path, rows: list[dict[str, Any]], identity: dict[str, Any],
                   deterministic: bool) -> None:
    lines = [
        "# plasticity P1 observe — shadow ranking comparison (what would change)",
        "",
        f"- cases: {len(rows)} (U4.2: u3a 12–26 + u3b 27–41)",
        f"- snapshot: `{identity['snapshot_root']}`",
        f"- ledger: `{identity['ledger']}`",
        f"- config: `{identity['config']}`",
        f"- determinism (2 identical iterations): `{deterministic}`",
        "",
        "| case | slice | seeds | paths | order equal | targets equal | missing equal | max ΔE | budget Δchars |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        d = r["diff"]
        lines.append(
            f"| {r['case']} | {r['slice']} | {len(r['seeds'])} | {r['paths_considered']} "
            f"| {'Y' if d['path_order_equal'] else 'N'} "
            f"| {'Y' if d['targets_delivered_equal'] else 'N'} "
            f"| {'Y' if d['targets_missing_equal'] else 'N'} "
            f"| {d['max_energy_delta']:.4f} "
            f"| {r['plastic']['budget_est_chars'] - r['base']['budget_est_chars']:+d} |"
        )
    changed = sum(1 for r in rows if not r["diff"]["targets_delivered_equal"]
                  or not r["diff"]["targets_missing_equal"] or not r["diff"]["path_order_equal"])
    lines += [
        "",
        f"**Cases whose delivered targets or path order would change: {changed}/{len(rows)}**",
        "",
        "Deliverable: an auditable 'what would change' table with nothing changed.",
    ]
    (out / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _synthetic_fake(cases: list[int]) -> dict[int, dict[str, Any]]:
    return {c: {"slice": "fake", "question": "who managed Alpha project",
                "gold": "", "required_ids": ["M0001", "M0002"], "cat": "fake"} for c in cases}


def fake_self_check() -> int:
    import tempfile

    root = Path(tempfile.mkdtemp(prefix="pl-observe-fake-"))
    cases: list[int] = []
    for case_no, extra in ((0, None), (1, None)):
        store = GraphStore(root / f"case_{case_no:02d}")
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
        cases.append(case_no)
    bench = _synthetic_fake(cases)
    ledger = UtilityLedger(root / "ledger")
    rows = [one_case(c, bench[c], root, ledger) for c in cases]
    empty = all(r["diff"]["path_order_equal"] and r["diff"]["targets_delivered_equal"]
                and r["diff"]["targets_missing_equal"] and r["diff"]["max_energy_delta"] == 0.0
                for r in rows)
    if not empty:
        print("fault: empty ledger must produce byte-identical base/plastic ranking", file=sys.stderr)
        return 1
    for _ in range(40):  # saturate the weaker edge: utility must flip ordering
        ledger.record(EdgeKey("E0001", "related_to", "E0003", DEFAULT_SCOPE), signal=+1.0)
    rows2 = [one_case(c, bench[c], root, ledger) for c in cases]
    flipped = any(not r["diff"]["path_order_equal"] for r in rows2 if r["base"]["paths"])
    print(f"fake: empty-ledger identical={empty}, ledger-loaded order flipped={flipped}, paths={len(rows2[0]['base']['paths'])}")
    return 0 if (empty and rows2 and rows2[0]["base"]["paths"] and flipped) else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="P1 observe harness (shadow ranking, no effect)")
    ap.add_argument("--snapshots", default="eval/graph_out/graphs/longmemeval")
    ap.add_argument("--bench-dir", default="eval/graph_out")
    ap.add_argument("--ledger-root", default="", help="project root with a plasticity/ ledger (read-only)")
    ap.add_argument("--out", default="eval/results/plasticity_u42_observe/run1")
    ap.add_argument("--repeat", type=int, default=2, help="identical iterations for determinism proof")
    ap.add_argument("--fake", action="store_true", help="deterministic self-check, writes under /tmp")
    args = ap.parse_args()

    if args.fake:
        return fake_self_check()

    cases = [c for _, r in SLICES for c in r]
    snapshot_root = Path(args.snapshots)
    bench_dir = Path(args.bench_dir)
    ledger = UtilityLedger(Path(args.ledger_root)) if args.ledger_root else UtilityLedger(Path("/tmp/__pl_empty__"), policy_version="p0")
    rows_all = run(cases, snapshot_root, bench_dir, ledger, Path(args.out), repeat=max(1, args.repeat))
    _, identity, rows = rows_all
    deterministic = rows_all[0]["deterministic"]
    _write_summary(Path(args.out), rows, identity, deterministic)
    changed = sum(1 for r in rows if not r["diff"]["path_order_equal"]
                  or not r["diff"]["targets_delivered_equal"] or not r["diff"]["targets_missing_equal"])
    print(f"observe: {len(rows)} cases → artifacts at {args.out}/ ; determinism={deterministic} changed={changed}")
    return 0


if __name__ == "__main__":
    sys.exit(main())