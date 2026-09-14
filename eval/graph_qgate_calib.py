"""P2: deterministic calibration of the question-facing gate.

Candidates are every graph-only memory the unguarded augment arm considered
(top-k evidence per case, shared-agent snapshot). For each candidate we compute
question-conditioned signals and ask: which rule blocks the graph-only noise
WITHOUT blocking any graph-only gold, and with the least reliance on lexical
similarity (so the gate does not become another BM25)?

Signals (all deterministic, no LLM):
  S1 text coverage   tokens(question) covered by the memory text (and IDF variant)
  S2 bm25 positive   BM25(question, [memory text]) > 0
  S3 entity coverage tokens(question) covered by entity names on the path
  S4 label coverage  tokens(question) covered by the evidence label
  S5 seed anchor     any query seed appears among the path nodes; first depth
  S6 structural      any path with semantic_depth >= 2 or an event hop

Run:  PYTHONPATH=src:.:eval python3 eval/graph_qgate_calib.py --reuse-root <root>
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import Counter
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "src"))

from memory_machine.graph import GraphStore, normalize_name  # noqa: E402
from memory_machine.retrieval import rank, tokenize  # noqa: E402
from memory_machine.tape import Tape  # noqa: E402

DEFAULT_ROOT = Path(
    "/var/folders/3z/9n8mh2p12ld771wy19z5v7rw0000gn/T/mm-graph-t5w86fv7"
)
STOP = {
    "how", "many", "did", "i", "the", "a", "an", "to", "on", "in", "of", "my",
    "was", "is", "it", "and", "for", "what", "when", "where", "that", "at",
    "me", "you", "have", "has", "been", "much", "per", "day", "days", "there",
}


def question_tokens(question: str) -> set[str]:
    return {t for t in tokenize(question) if t not in STOP and len(t) > 2}


def coverage(tokens: set[str], text: str) -> float:
    if not tokens:
        return 0.0
    have = set(tokenize(text))
    return len(tokens & have) / len(tokens)


def idf_coverage(tokens: set[str], text: str, idf: dict[str, float]) -> float:
    total = sum(idf.get(t, 0.0) for t in tokens)
    if total <= 0:
        return 0.0
    have = set(tokenize(text))
    return sum(idf.get(t, 0.0) for t in tokens & have) / total


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reuse-root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--snapshot", default=str(HERE / "graph_out" / "graph_bench_longmemeval.jsonl"))
    parser.add_argument("--arm", default="graph_augment")
    args = parser.parse_args()

    rows = [
        json.loads(line)
        for line in Path(args.snapshot).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    candidates: list[dict[str, Any]] = []
    for row in rows:
        case = row["case"]
        if "agent_ids" not in row:
            raise SystemExit("snapshot is not the shared-agent replay (no agent_ids)")
        required = set(row["required_ids"])
        agent_ids = set(row["agent_ids"])
        case_dir = args.reuse_root / f"case_{case:02d}" / "graph_augment"
        store = GraphStore(case_dir / "graph")
        index = store.index()
        tape = Tape(case_dir / "tape.jsonl")
        records = {record.id: record for record in tape.read()}
        question = row["question"]
        tokens = question_tokens(question)
        # case idf over session/memory texts
        docs = [f"{r.summary} {r.why}" for r in records.values()]
        idf: Counter[str] = Counter()
        for doc in docs:
            for token in set(tokenize(doc)):
                idf[token] += 1
        n_docs = max(1, len(docs))
        idf_values = {t: math.log((n_docs + 1) / (idf[t] + 1)) + 1 for t in idf}
        seeds = {token for token in tokens}
        verdicts = {
            variant: row["arms"][variant]["verdict"]
            for variant in row["arms"]
            if row["arms"][variant]["verdict"]
        }
        for evidence in row["arms"][args.arm]["graph_evidence"]:
            memory_id = evidence["memory_id"]
            if memory_id in agent_ids:
                continue
            record = records.get(memory_id)
            text = f"{record.summary} {record.why}" if record else ""
            paths = evidence["paths"]
            nodes = [node for path in paths for node in path["nodes"]]
            node_names = [
                index.entities[node].name for node in nodes if node in index.entities
            ]
            seed_nodes = [
                node for node in set(nodes)
                if node in index.entities
                and normalize_name(index.entities[node].name) in {normalize_name(s) for s in tokens}
            ]
            structural = any(
                path["semantic_depth"] >= 2
                or len(path["relations"]) > path["semantic_depth"]
                for path in paths
            )
            candidates.append(
                {
                    "case": case,
                    "cat": row["cat"],
                    "memory_id": memory_id,
                    "gold": int(memory_id in required),
                    "score": evidence["score"],
                    "via": evidence["via"],
                    "s1_text_cov": round(coverage(tokens, text), 4),
                    "s1_idf_cov": round(idf_coverage(tokens, text, idf_values), 4),
                    "s2_bm25_positive": int(bool(rank(question, [text], limit=1))),
                    "s3_entity_cov": round(coverage(tokens, " ".join(node_names)), 4),
                    "s4_label_cov": round(coverage(tokens, evidence["label"]), 4),
                    "s5_seed_anchor": int(bool(seed_nodes)),
                    "s6_structural": int(structural),
                    "verdicts": json.dumps(verdicts),
                }
            )

    out = HERE / "graph_out" / "qgate_calib.csv"
    fields = list(candidates[0].keys())
    with out.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(candidates)

    # Rule sweep: a rule blocks a candidate when it says "no".
    def rules(item: dict[str, Any]) -> dict[str, bool]:
        t1 = 0.30
        return {
            "lex_0.20": item["s1_text_cov"] >= 0.20,
            "lex_0.30": item["s1_text_cov"] >= 0.30,
            "lex_0.40": item["s1_text_cov"] >= 0.40,
            "idf_0.30": item["s1_idf_cov"] >= 0.30,
            "entity_0.20": item["s3_entity_cov"] >= 0.20,
            "bm25_pos": bool(item["s2_bm25_positive"]),
            "struct_exempt_0.30": (
                item["s1_text_cov"] >= t1
                or (item["s6_structural"] and item["s5_seed_anchor"])
                or item["s3_entity_cov"] >= 0.20
            ),
            "struct_exempt_0.40": (
                item["s1_text_cov"] >= 0.40
                or (item["s6_structural"] and item["s5_seed_anchor"])
                or item["s3_entity_cov"] >= 0.30
            ),
        }

    summary: dict[str, dict[str, Any]] = {}
    for item in candidates:
        for name, admitted in rules(item).items():
            entry = summary.setdefault(
                name,
                {"rule": name, "gold_total": 0, "gold_kept": 0, "non_gold_total": 0, "non_gold_blocked": 0},
            )
            if item["gold"]:
                entry["gold_total"] += 1
                entry["gold_kept"] += int(admitted)
            else:
                entry["non_gold_total"] += 1
                entry["non_gold_blocked"] += int(not admitted)

    summary_rows = []
    for name, entry in sorted(summary.items()):
        summary_rows.append(
            {
                **entry,
                "gold_blocked": entry["gold_total"] - entry["gold_kept"],
            }
        )
    out_rules = HERE / "graph_out" / "qgate_rules.csv"
    with out_rules.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(summary_rows[0].keys()))
        writer.writeheader()
        writer.writerows(summary_rows)

    lines = [
        "# P2 question-gate calibration (shared-agent snapshot)",
        "",
        f"Candidates: {len(candidates)} graph-only items "
        f"({sum(item['gold'] for item in candidates)} gold).",
        "",
        "| rule | gold kept | gold blocked | non-gold blocked / total |",
        "|---|---:|---:|---:|",
    ]
    for item in summary_rows:
        lines.append(
            f"| {item['rule']} | {item['gold_kept']}/{item['gold_total']} | {item['gold_blocked']} "
            f"| {item['non_gold_blocked']}/{item['non_gold_total']} |"
        )
    (HERE / "graph_out" / "qgate_calib.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {out}, {out_rules} and qgate_calib.md")
    for item in summary_rows:
        print(
            f"  {item['rule']:<20} gold {item['gold_kept']}/{item['gold_total']} "
            f"| non-gold blocked {item['non_gold_blocked']}/{item['non_gold_total']}"
        )


if __name__ == "__main__":
    main()
