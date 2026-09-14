"""V2-0: replay auditável do controle de admissão sobre os grafos preservados.

Para cada caso da LME-12 e cada combinação (H hub cap, T threshold, N cap):

    travessia hub-aware -> evidência do grafo -> admissão (>=T, top-N)
    -> união com as anotações dos agentes -> payload (budget 4000) -> métricas

Colunas decisivas além das contagens: `would_displace_agent_gold` (o gold dos
agentes perdeu caracteres no payload?) e `graph_only_budget_share` (fatia do
budget ocupada por evidência exclusiva do grafo).

Nada é reexecutado com LLM e o core não é tocado: lê os grafos preservados do
root temporário da LME-12 + o snapshot `eval/graph_out/graph_bench_longmemeval.jsonl`.

Run:  PYTHONPATH=src:.:eval python3 eval/graph_guard_calib.py [--reuse-root DIR]
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import deque
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "src"))

from memory_machine.graph import GraphIndex, GraphStore  # noqa: E402
from memory_machine.graph_recall import DEPTH_PENALTY, GraphPath, GraphRecall  # noqa: E402
from memory_machine.payload import build_evidence_payload  # noqa: E402
from memory_machine.tape import Tape  # noqa: E402
from memory_machine.whiteboard import Annotation  # noqa: E402

DEFAULT_ROOT = Path(
    "/var/folders/3z/9n8mh2p12ld771wy19z5v7rw0000gn/T/mm-graph-x9parxkk"
)
BUDGET = 4000
HUB_CAPS = [10, 20, 30, 50, 5000]  # 5000 == sem hub cap
THRESHOLDS = [0.0, 0.80, 0.85, 0.90]
ITEM_CAPS = [2, 3, 5, 99]  # 99 == sem cap


def degree_map(index: GraphIndex) -> dict[str, int]:
    degree: dict[str, int] = {}
    for relation in index.relations.values():
        if relation.kind in {"resolution", "hypothesis"}:
            continue
        degree[relation.source] = degree.get(relation.source, 0) + 1
        degree[relation.target] = degree.get(relation.target, 0) + 1
    return degree


def hub_aware_paths(
    index: GraphIndex,
    seed: str,
    *,
    depth: int,
    hub_degree: int,
    degree: dict[str, int],
    max_paths: int = 400,
) -> list[GraphPath]:
    """Same BFS as GraphRecall, but never expands FROM a node above hub_degree."""
    if degree.get(seed, 0) > hub_degree:
        return []
    paths: list[GraphPath] = []
    seen_paths: set[tuple[tuple[str, ...], tuple[str, ...]]] = set()
    visited = {seed}
    queue: deque[tuple[str, list[str], list[str], float, int]] = deque(
        [(seed, [seed], [], 1.0, 0)]
    )
    while queue:
        current, nodes, relations, confidence, semantic = queue.popleft()
        if semantic >= depth:
            continue
        for chain, nxt, via_event in _semantic_neighbors(index, current, hub_degree, degree):
            chain_confidence = min([confidence, *(r.confidence for r in chain)])
            next_nodes = nodes + ([via_event] if via_event else []) + [nxt]
            next_relations = relations + [r.id for r in chain]
            path = GraphPath(
                nodes=next_nodes,
                relations=next_relations,
                score=chain_confidence * (DEPTH_PENALTY**semantic),
                semantic_depth=semantic + 1,
            )
            key = (tuple(path.nodes), tuple(path.relations))
            if key in seen_paths:
                continue
            seen_paths.add(key)
            paths.append(path)
            if nxt in visited or degree.get(nxt, 0) > hub_degree:
                continue  # record the edge into a hub, never expand from it
            visited.add(nxt)
            queue.append((nxt, next_nodes, next_relations, chain_confidence, semantic + 1))
            if len(paths) >= max_paths:
                return paths
    return paths


def _semantic_neighbors(
    index: GraphIndex, entity_id: str, hub_degree: int, degree: dict[str, int]
) -> list[tuple[list[Any], str, str]]:
    """GraphRecall's neighbor rule, without the extra hub checks (done by caller)."""
    out: list[tuple[list[Any], str, str]] = []
    for relation in index.edges_of(entity_id, direction="both"):
        other = relation.target if relation.source == entity_id else relation.source
        entity = index.entities.get(other)
        if entity is not None and entity.type == "event":
            for second in index.edges_of(other, direction="both", kinds=("agent", "object")):
                nxt = second.target if second.source == other else second.source
                if nxt == entity_id:
                    continue
                out.append(([relation, second], nxt, other))
            continue
        out.append(([relation], other, ""))
    return out


def replay_case(
    index: GraphIndex,
    question: str,
    *,
    hub_degree: int,
    threshold: float,
    item_cap: int,
    depth: int,
    top_k: int = 8,
) -> list[Any]:
    recall = GraphRecall(index, depth=depth, top_k=top_k)
    seeds = recall.resolve_query_entities(question)
    if not seeds:
        return []
    degree = degree_map(index)
    paths: list[GraphPath] = []
    seen: set[tuple[tuple[str, ...], tuple[str, ...]]] = set()
    for seed in seeds:
        for path in hub_aware_paths(
            index, seed, depth=depth, hub_degree=hub_degree, degree=degree
        ):
            key = (tuple(path.nodes), tuple(path.relations))
            if key not in seen:
                seen.add(key)
                paths.append(path)
    evidence = recall.evidence_from_paths(seeds, paths)
    # admission: threshold + cap over graph-only candidates happens in caller
    return evidence


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reuse-root", type=Path, default=DEFAULT_ROOT)
    args = parser.parse_args()

    snapshot = [
        json.loads(line)
        for line in (HERE / "graph_out" / "graph_bench_longmemeval.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]

    per_case: list[dict[str, Any]] = []
    for row in snapshot:
        case = row["case"]
        graph_dir = args.reuse_root / f"case_{case:02d}" / "graph_augment" / "graph"
        if not (graph_dir / "entities.jsonl").exists():
            print(f"case {case}: graph missing at {graph_dir}", flush=True)
            continue
        index = GraphStore(graph_dir).index()
        tape = Tape(args.reuse_root / f"case_{case:02d}" / "graph_augment" / "tape.jsonl")
        records = {record.id: record for record in tape.read()}
        required = set(row["required_ids"])
        off_ids = set(row["arms"]["graph_off"]["annotations"])
        agent_gold = required & off_ids
        current_graph_ids = {item["memory_id"] for item in row["arms"]["graph_augment"]["graph_evidence"]}
        per_case.append(
            {
                "case": case,
                "cat": row["cat"],
                "question": row["question"],
                "index": index,
                "records": records,
                "required": required,
                "off_ids": off_ids,
                "agent_gold": agent_gold,
                "current_graph_ids": current_graph_ids,
                "unjudged_correct_off": row["arms"]["graph_off"]["verdict"],
            }
        )

    rows: list[dict[str, Any]] = []
    for case in per_case:
        agent_annotations = [
            Annotation(memory_id=mid, note="agent", relevance=0.9, agent_id="agent")
            for mid in sorted(case["off_ids"])
        ]
        for hub in HUB_CAPS:
            for threshold in THRESHOLDS:
                for cap in ITEM_CAPS:
                    evidence = replay_case(
                        case["index"],
                        case["question"],
                        hub_degree=hub,
                        threshold=threshold,
                        item_cap=cap,
                        depth=2,
                    )
                    graph_only = [
                        item for item in evidence if item.memory_id not in case["off_ids"]
                    ]
                    baseline_graph_only = [
                        item
                        for item in evidence
                        if item.memory_id not in case["off_ids"]
                    ]
                    admitted = [item for item in graph_only if item.score >= threshold][:cap]
                    gold_admitted = [item.memory_id for item in admitted if item.memory_id in case["required"]]
                    non_gold_admitted = len(admitted) - len(gold_admitted)
                    gold_found = {item.memory_id for item in baseline_graph_only if item.memory_id in case["required"]}
                    gold_lost = sorted(gold_found - set(gold_admitted))

                    annotations = list(agent_annotations)
                    known = {a.memory_id: a for a in annotations}
                    for item in admitted:
                        current = known.get(item.memory_id)
                        if current is None or item.score > current.relevance:
                            annotations = [a for a in annotations if a.memory_id != item.memory_id]
                            annotations.append(
                                Annotation(
                                    memory_id=item.memory_id,
                                    note=item.label or "graph",
                                    relevance=max(0.05, float(item.score)),
                                    agent_id="graph",
                                )
                            )
                    payload = build_evidence_payload(
                        case["records"], annotations, budget=BUDGET, min_item_chars=200
                    )
                    by_id = {item["memory_id"]: item for item in payload}
                    agent_gold_alloc = sum(
                        by_id[mid]["allocated_chars"] for mid in case["agent_gold"] if mid in by_id
                    )
                    agent_gold_dropped = sorted(mid for mid in case["agent_gold"] if mid not in by_id)
                    graph_alloc = sum(
                        item["allocated_chars"]
                        for item in payload
                        if item["memory_id"] in {a.memory_id for a in admitted}
                    )
                    used = sum(item["used_chars"] for item in payload) or 1
                    rows.append(
                        {
                            "case": case["case"],
                            "cat": case["cat"],
                            "H": hub,
                            "T": threshold,
                            "N": cap,
                            "graph_only_candidates": len(baseline_graph_only),
                            "admitted": len(admitted),
                            "gold_admitted": len(gold_admitted),
                            "non_gold_admitted": non_gold_admitted,
                            "gold_lost": "|".join(gold_lost),
                            "agent_gold_alloc": agent_gold_alloc,
                            "agent_gold_dropped": "|".join(agent_gold_dropped),
                            "graph_only_budget_share": round(graph_alloc / used, 4),
                        }
                    )

    out_csv = HERE / "graph_out" / "guard_calib.csv"
    with out_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    # Aggregate per configuration
    def base_alloc(case_id: int) -> int:
        case_rows = [r for r in rows if r["case"] == case_id and r["H"] == 5000 and r["T"] == 0.0 and r["N"] == 99]
        return case_rows[0]["agent_gold_alloc"] if case_rows else 0

    summary: dict[tuple[int, float, int], dict[str, Any]] = {}
    for row in rows:
        key = (row["H"], row["T"], row["N"])
        item = summary.setdefault(
            key,
            {
                "H": row["H"],
                "T": row["T"],
                "N": row["N"],
                "gold_only_kept": 0,
                "gold_only_total": 0,
                "overlap_kept": 0,
                "non_gold_admitted": 0,
                "admitted": 0,
                "candidates": 0,
                "agent_gold_alloc": 0,
                "agent_gold_alloc_unguarded": 0,
                "agent_gold_dropped": 0,
                "graph_share": [],
                "gold_lost": [],
            },
        )
        item["gold_only_kept"] += row["gold_admitted"]
        item["overlap_kept"] += 0
        item["non_gold_admitted"] += row["non_gold_admitted"]
        item["admitted"] += row["admitted"]
        item["candidates"] += row["graph_only_candidates"]
        item["agent_gold_alloc"] += row["agent_gold_alloc"]
        item["agent_gold_alloc_unguarded"] += base_alloc(row["case"])
        item["agent_gold_dropped"] += len(row["agent_gold_dropped"].split("|")) if row["agent_gold_dropped"] else 0
        item["graph_share"].append(row["graph_only_budget_share"])
        if row["gold_lost"]:
            item["gold_lost"].extend(row["gold_lost"].split("|"))

    # total graph-only gold in the unguarded snapshot (reference)
    golden_reference = sum(
        1
        for case in per_case
        for mid in case["current_graph_ids"] - case["off_ids"]
        if mid in case["required"]
    )

    summary_rows = []
    for key, item in sorted(summary.items()):
        summary_rows.append(
            {
                "H": item["H"],
                "T": item["T"],
                "N": item["N"],
                "gold_only_kept_of_ref": f"{item['gold_only_kept']}/{golden_reference}",
                "gold_only_kept": item["gold_only_kept"],
                "non_gold_admitted": item["non_gold_admitted"],
                "admitted_total": item["admitted"],
                "graph_candidates_total": item["candidates"],
                "agent_gold_alloc_ratio": round(
                    item["agent_gold_alloc"] / item["agent_gold_alloc_unguarded"], 4
                )
                if item["agent_gold_alloc_unguarded"]
                else None,
                "agent_gold_dropped": item["agent_gold_dropped"],
                "graph_share_mean": round(sum(item["graph_share"]) / len(item["graph_share"]), 4),
                "gold_lost": "|".join(sorted(set(item["gold_lost"]))),
            }
        )
    out_summary = HERE / "graph_out" / "guard_calib_summary.csv"
    with out_summary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(summary_rows[0].keys()))
        writer.writeheader()
        writer.writerows(summary_rows)

    # Readable markdown: focus grid H x T x N with gold/non-gold/agent ratio
    lines = [
        "# V2-0 guard calibration (LME-12 replay)",
        "",
        f"Reference: graph-only gold in the unguarded snapshot = {golden_reference}.",
        "",
        "| H | T | N | gold-only kept | non-gold admitted | agent gold alloc ratio | agent gold dropped | graph share | gold lost |",
        "|---:|---:|---:|---|---:|---:|---:|---:|---|",
    ]
    for item in summary_rows:
        lines.append(
            f"| {item['H']} | {item['T']:.2f} | {item['N']} | {item['gold_only_kept_of_ref']} "
            f"| {item['non_gold_admitted']} | {item['agent_gold_alloc_ratio']} "
            f"| {item['agent_gold_dropped']} | {item['graph_share_mean']} | {item['gold_lost']} |"
        )
    lines.append("")
    (HERE / "graph_out" / "guard_calib.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {out_csv}, {out_summary} and guard_calib.md")
    print(f"reference graph-only gold: {golden_reference}")
    for item in summary_rows:
        if item["gold_only_kept"] == golden_reference:
            print(
                f"  keeps all: H={item['H']} T={item['T']:.2f} N={item['N']} "
                f"non_gold={item['non_gold_admitted']} ratio={item['agent_gold_alloc_ratio']}"
            )


if __name__ == "__main__":
    main()
