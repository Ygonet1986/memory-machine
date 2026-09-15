#!/usr/bin/env python3
"""Deterministic generator for the P2b shared-graph substrate.

Builds ONE persistent graph (a single GraphStore — "one Memory Machine
project") plus a bench of DISTINCT questions over it, split into a train set
and an eval set whose texts never overlap, with mechanical gold derived from
the graph construction itself (never from an LLM or labeled answers M0155).

The graph deliberately contains two weakly-connected topic regions so the P2b
exposure split is structural, not tuned:

- **trained region**: modules ``{payments, auth, search, gateway, ledger}`` +
  techs ``{kafka..flink}`` + persons ``{alice,bob,carol}``. Train questions and
  a portion of eval questions are about these facts; their search spaces share
  hub edges, which is what makes ``exposed`` evaluable instances non-empty.
- **unexposed region**: modules ``{inventory, shipping, analytics}`` + techs
  ``{mongodb..solr}`` + persons ``{dave,erin,frank}``. Eval questions about
  these facts share ZERO edge keys with the ledger by construction, so they act
  as the negative control that must remain byte-identical.

Instrument (pre-registered in docs/PLASTICITY_V1.md §13, decision 2026-09-14):
search candidate pool `recall_top_k=32`, delivery budget still §12.5 (top 8
items / 4000 chars). This makes the delivery budget bind (otherwise the
delivered set is structurally the whole pool and reordering could not flip
outcomes — the P1/P2 instrument was blind to ordering).

Queries are mechanical and never reveal their gold: a question mentions its
module (hub entity) but not the target tech/fact, and the required memory is
the ``decided_on`` fact of that module's cell — derived from construction.

Everything below is a fixed function of ``--seed`` (deterministic across
invocations). Outputs under ``--out`` (committed under
``eval/plasticity_fixtures/u42_shared/``):

- ``graph/`` — GraphStore snapshot files (entities/relations/mentions/meta).
- ``bench.jsonl`` — every question: qid, split (train|eval), region
  (trained|unexposed), question text, required_ids, fact.
- ``ground.jsonl`` — mechanical fact-presence ground per question
  (``arms.graph_off.items`` keyed by memory id: delivered + item_facts),
  computed by replaying the frozen deterministic recall (no LLM).
- ``manifest.json`` — seed, counts, sha1 of every output file and of the graph
  snapshot (the frozen substrate identity P2b pins).

The P2b harness (`eval/plasticity_shared.py`) is the pre-registered consumer.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from memory_machine.graph import GraphStore, GraphIndex
from memory_machine.graph_recall import GraphRecall

DEPTH = 2
RECALL_TOP_K = 32          # search candidate pool (§13, decision 2026-09-14)
BUDGET_ITEMS = 8           # delivery budget §12.5 (unchanged)
BUDGET_CHARS = 4000
MAX_PATHS = 400
DEFAULT_HUB_EDGES = 8       # decided_on edges per module (per region tech list)
SEED = 20260914

REGIONS = {
    "trained": {
        "modules": ["payments", "auth", "search", "gateway", "ledger"],
        "techs": ["kafka", "postgres", "redis", "grpc", "elasticsearch",
                  "rabbitmq", "prometheus", "flink"],
        "persons": ["alice", "bob", "carol"],
    },
    "unexposed": {
        "modules": ["inventory", "shipping", "analytics"],
        "techs": ["mongodb", "hive", "spark", "cassandra", "nats", "duckdb",
                  "clickhouse", "solr"],
        "persons": ["dave", "erin", "frank"],
    },
}

# Question families. Modulo/module counters keep texts unique; questions never
# mention the target tech, so the gold is non-trivial (mechanical, que-R+m0155).
TRAIN_TEMPLATES = [
    "which technology was chosen for the {module} module?",
    "what did we decide to run for the {module} service?",
    "the team picked a stack for {module} — what is it?",
    "confirm the technology decision for the {module} component",
    "which infra runs inside {module} these days?",
    "the {module} backend relies on which technology?",
    "remind me of the tech decision for the {module} platform",
    "what did the review settle on for {module}?",
]
EVAL_EXPOSED_TEMPLATES = [
    "remind me what runs the {module} service these days",
    "is the {module} stack still on the chosen tech?",
    "we are re-architecting {module} — what is the current pick?",
    "which technology is the {module} module pinned to?",
    "what did we agree to deploy for {module}?",
    "looking back at {module}, what tech did we settle on?",
    "the {module} project uses which backend?",
    "what is the decided stack for the {module} component?",
]
EVAL_UNEXPOSED_TEMPLATES = [
    "remind me what runs the {module} service these days",
    "is the {module} stack still on the chosen tech?",
    "we are re-architecting {module} — what is the current pick?",
    "which technology is the {module} module pinned to?",
    "what did we agree to deploy for {module}?",
    "looking back at {module}, what tech did we settle on?",
    "the {module} project uses which backend?",
    "what is the decided stack for the {module} component?",
]
GROUND_SIGNAL_SCOPE = "chunk"


def sha1_bytes(blob: bytes) -> str:
    return hashlib.sha1(blob).hexdigest()


def deterministic(method: str, seed: int, *parts: str, n: int = 0) -> int:
    h = hashlib.sha256("|".join((method, str(seed), *parts)).encode("utf-8"))
    value = int(h.hexdigest()[:12], 16)
    return value % n if n else value


def build_graph(store: GraphStore) -> dict[str, Any]:
    """One persistent graph with weakly-connected trained/unexposed regions.

    In the trained region each ``decided_on`` fact gets a **shadow fact**: a
    second memory on the SAME edge ``(module, decided_on, tech)`` with a lower
    seeded confidence. Shadows are the P2b *repair-capable* eval targets: they
    carry zero answer of their own into the ledger (their memory id is never a
    train target, so no eval label leaks), yet their navigation rides the very
    edge the ledger learns — different question, same navigation, mechanical
    gold (M0155). The extra ``uses``/``integrates_with``/``owns``/``depends_on``
    edges add candidate noise so the search pool exceeds the delivery budget.
    """
    rid = 0
    mid = 0
    ent: dict[str, str] = {}

    def add(name: str, typ: str) -> None:
        nonlocal mid
        mid += 1
        rid_e = f"E{len(ent)+1:04d}"
        ent[name] = rid_e
        store.add_entity(name, typ, f"M{mid:04d}", entity_id=rid_e,
                         extraction_scope=GROUND_SIGNAL_SCOPE)
        store.add_mention(memory_id=f"M{mid:04d}", entity_id=rid_e,
                          confidence=0.9, extraction_scope=GROUND_SIGNAL_SCOPE)

    facts: list[dict[str, Any]] = []
    shadows: list[dict[str, Any]] = []

    for region, cfg in REGIONS.items():
        for name in cfg["modules"] + cfg["techs"] + cfg["persons"]:
            add(name, "module" if name in cfg["modules"] else
                ("technology" if name in cfg["techs"] else "person"))
        n_mod = len(cfg["modules"])
        for mi, name in enumerate(cfg["modules"]):
            picked_techs = [cfg["techs"][(mi * DEFAULT_HUB_EDGES + j) % len(cfg["techs"])]
                            for j in range(DEFAULT_HUB_EDGES)]
            for j, tech in enumerate(picked_techs):
                conf = round(0.55 + 0.40 * (deterministic("conf", SEED, name, tech, n=1000) / 1000.0), 3)
                mid += 1
                store.add_relation(
                    source=ent[name], relation="decided_on", target=ent[tech],
                    memory_id=f"M{mid:04d}", confidence=conf,
                    relation_id=f"R{rid}", extraction_scope=GROUND_SIGNAL_SCOPE)
                facts.append({"region": region, "module": name, "tech": tech,
                              "fact_memory": f"M{mid:04d}", "confidence": conf})
                rid += 1
                if region == "trained":
                    shadow_conf = round(0.22 + 0.16 * (deterministic("shadow", SEED, name, tech, n=1000) / 1000.0), 3)
                    mid += 1
                    store.add_relation(
                        source=ent[name], relation="decided_on", target=ent[tech],
                        memory_id=f"M{mid:04d}", confidence=shadow_conf,
                        relation_id=f"R{rid}", extraction_scope=GROUND_SIGNAL_SCOPE)
                    shadows.append({"region": region, "module": name, "tech": tech,
                                    "fact_memory": f"M{mid:04d}", "confidence": shadow_conf})
                    rid += 1
            for j in range(2):
                other = cfg["modules"][(mi + 1 + j) % n_mod]
                conf = round(0.60 + 0.35 * (deterministic("int", SEED, name, other, n=1000) / 1000.0), 3)
                mid += 1
                store.add_relation(
                    source=ent[name], relation="integrates_with", target=ent[other],
                    memory_id=f"M{mid:04d}", confidence=conf,
                    relation_id=f"R{rid}", extraction_scope=GROUND_SIGNAL_SCOPE)
                rid += 1
                conf = round(0.60 + 0.35 * (deterministic("use", SEED, name, other, n=1000) / 1000.0), 3)
                mid += 1
                store.add_relation(
                    source=ent[name], relation="uses", target=ent[cfg["techs"][j % len(cfg["techs"])]],
                    memory_id=f"M{mid:04d}", confidence=conf,
                    relation_id=f"R{rid}", extraction_scope=GROUND_SIGNAL_SCOPE)
                rid += 1
        for pi, person in enumerate(cfg["persons"]):
            mod = cfg["modules"][pi % n_mod]
            conf = round(0.70 + 0.20 * (deterministic("own", SEED, person, mod, n=1000) / 1000.0), 3)
            mid += 1
            store.add_relation(
                source=ent[person], relation="owns", target=ent[mod],
                memory_id=f"M{mid:04d}", confidence=conf,
                relation_id=f"R{rid}", extraction_scope=GROUND_SIGNAL_SCOPE)
            rid += 1
        for j in range(len(cfg["techs"]) - 1):
            a, b = cfg["techs"][j], cfg["techs"][j + 1]
            conf = round(0.65 + 0.30 * (deterministic("dep", SEED, a, b, n=1000) / 1000.0), 3)
            mid += 1
            store.add_relation(
                source=ent[a], relation="depends_on", target=ent[b],
                memory_id=f"M{mid:04d}", confidence=conf,
                relation_id=f"R{rid}", extraction_scope=GROUND_SIGNAL_SCOPE)
            rid += 1

    return {"entities": len(ent), "relations": rid, "memories": mid,
            "facts": facts, "shadows": shadows}


def build_bench(facts: list[dict[str, Any]],
                shadows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    bench: list[dict[str, Any]] = []
    qid = 0

    def emit(split: str, region: str, fact: dict[str, Any], templ: str) -> None:
        nonlocal qid
        qid += 1
        bench.append({
            "qid": qid,
            "split": split,
            "region": region,
            "fact": f"{fact['module']}##{fact['tech']}",
            "question": templ.format(module=fact["module"]),
            "required_ids": [fact["fact_memory"]],
        })

    for region, cfg in REGIONS.items():
        for module in cfg["modules"]:
            mod_facts = sorted((f for f in facts if f["module"] == module),
                               key=lambda f: f["tech"])
            if region == "trained":
                # first half trained, second half eval exposed (share hub edges)
                for k, fact in enumerate(mod_facts[:4]):
                    emit("train", "trained", fact, TRAIN_TEMPLATES[k])
                for k, fact in enumerate(mod_facts[4:8]):
                    emit("eval", "trained", fact, EVAL_EXPOSED_TEMPLATES[k % 4])
                # shadow targets: same edge as a trained fact → repair-capable
                mod_shadows = sorted((s for s in shadows if s["module"] == module),
                                     key=lambda s: s["tech"])
                for k, shadow in enumerate(mod_shadows):
                    emit("eval", "trained", shadow, EVAL_EXPOSED_TEMPLATES[4 + k % 4])
            else:
                # untouched-region facts: eval negative control (edges never learned)
                for k, fact in enumerate(mod_facts):
                    emit("eval", "unexposed", fact, EVAL_UNEXPOSED_TEMPLATES[k % 8])

    return bench


def build_ground(graph_dir: Path, bench: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Mechanical fact-presence ground (mirrors the archived longmemeval shape).

    Replays the frozen deterministic recall (pool=RECALL_TOP_K). An item is
    ``delivered`` iff it lands in the §12.5 delivery budget (top BUDGET_ITEMS by
    base score, ≤ BUDGET_CHARS). ``item_facts.present`` = how many of the
    question's required ids the item's retained paths carry. No LLM, no labeled
    answer — pure search properties (M0155).
    """
    index = GraphIndex.load(GraphStore(graph_dir))
    recall = GraphRecall(index, depth=DEPTH, top_k=RECALL_TOP_K, max_paths=MAX_PATHS)
    rows: list[dict[str, Any]] = []
    for br in bench:
        res = recall.recall(br["question"])
        required = set(br["required_ids"])
        budgeted = _budgeted_evidence(res.evidence)
        items: dict[str, Any] = {}
        for item in budgeted:
            carried = sum(1 for rid in item.relation_ids
                          if index.relations[rid].memory_id in required)
            items[item.memory_id] = {
                "delivered": True,
                "item_facts": {"total": len(required), "present": carried},
            }
        rows.append({
            "qid": br["qid"], "split": br["split"], "region": br["region"],
            "question": br["question"],
            "arms": {"graph_off": {"items": items}},
            "graph": {"seeds": list(res.seeds), "seed_labels": list(res.seed_labels),
                      "paths_considered": res.paths_considered,
                      "evidence_ids": [i.memory_id for i in res.evidence]},
        })
    return rows


def _budgeted_evidence(evidence) -> list[Any]:
    """§12.5 delivery budget: top items by base score, ≤ BUDGET_ITEMS / chars."""
    keep: list[Any] = []
    chars = 0
    for item in evidence:  # evidence already score-sorted (-score, memory_id)
        cost = len(_frame_label(item))
        if keep and (len(keep) >= BUDGET_ITEMS or chars + cost > BUDGET_CHARS):
            break
        keep.append(item)
        chars += cost
    return keep


def _frame_label(item: Any) -> str:
    """Cost proxy for the §12.5 delivery budget — must equal the harness's
    ``budgeted_ids`` cost, which uses the rendered path ``label``."""
    return item.label or ""


def _mask_graph_timestamps(graph_dir: Path, seed: int) -> None:
    """Replace non-deterministic `created_at` with a fixed ts mask.

    GraphStore stamps nodes/relations with the real wall clock; ``created_at``
    never enters EdgeKey, scores or ranking (audit-only), so masking it makes
    the snapshot byte-reproducible without changing any recall outcome.
    """
    import re
    for name in ("entities.jsonl", "relations.jsonl", "mentions.jsonl"):
        path = graph_dir / name
        if not path.exists():
            continue
        lines = []
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            lines.append(re.sub(
                r'("created_at"\s*:\s*")[^"]*(")',
                lambda m: f'{m.group(1)}2026-09-15T00:{(i // 60) % 24:02d}:{i % 60:02d}+00:00{m.group(2)}',
                line))
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", required=True)
    ap.add_argument("--seed", type=int, default=SEED)
    args = ap.parse_args()

    out = Path(args.out)
    graph_dir = out / "graph"
    if out.exists():
        import shutil
        shutil.rmtree(out)
    store = GraphStore(graph_dir)
    meta = build_graph(store)
    _mask_graph_timestamps(graph_dir, args.seed)
    bench = build_bench(meta["facts"], meta["shadows"])
    ground = build_ground(graph_dir, bench)

    (out / "bench.jsonl").write_text(
        "\n".join(json.dumps(b, ensure_ascii=False) for b in bench) + "\n", encoding="utf-8")
    (out / "ground.jsonl").write_text(
        "\n".join(json.dumps(g, ensure_ascii=False) for g in ground) + "\n", encoding="utf-8")

    def sh(path: Path) -> str:
        return sha1_bytes(path.read_bytes())

    graph_blob = b"\n".join(sorted(p.read_bytes() for p in graph_dir.glob("*") if p.is_file()))
    manifest = {
        "seed": args.seed,
        "substrate": "u42_shared_shared-graph",
        "config": {"depth": DEPTH, "recall_top_k": RECALL_TOP_K,
                   "max_paths": MAX_PATHS, "budget_items": BUDGET_ITEMS,
                   "budget_chars": BUDGET_CHARS, "hub_edges": DEFAULT_HUB_EDGES,
                   "scope": GROUND_SIGNAL_SCOPE},
        "graph": {"entities": meta["entities"], "relations": meta["relations"],
                  "memories": meta["memories"], "shadows": len(meta["shadows"]),
                  "sha1": sha1_bytes(graph_blob)},
        "bench": {"total": len(bench),
                  "train": sum(1 for b in bench if b["split"] == "train"),
                  "eval": sum(1 for b in bench if b["split"] == "eval"),
                  "eval_exposed_region": sum(1 for b in bench
                                             if b["split"] == "eval" and b["region"] == "trained"),
                  "eval_unexposed_region": sum(1 for b in bench
                                               if b["split"] == "eval" and b["region"] == "unexposed")},
        "files": {p: sh(out / p) for p in ("bench.jsonl", "ground.jsonl")},
        "disjoint_train_eval": len({b["question"] for b in bench if b["split"] == "train"}
                                   & {b["question"] for b in bench if b["split"] == "eval"}) == 0,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())