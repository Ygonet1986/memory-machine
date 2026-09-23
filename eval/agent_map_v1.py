#!/usr/bin/env python3
"""agent-map-v1: verifiable per-agent maps + tape verification (L1-L5).

Frozen by docs/AGENT_MAP_V1_PREREG.md. Deterministic, no LLM; reuses the
`agent_index_v1` fixture (K=2 partitions per case).

    PYTHONPATH=src:.:eval python3 eval/agent_map_v1.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "src"))

import delivery_combined_v1 as dc  # noqa: E402
from memory_machine.retrieval import bm25, tokenize  # noqa: E402

FIXTURE = HERE / "fixtures" / "agent_index_v1"
TAU = 0.5
K_MAX = 3
ARMS = ("A0", "A1", "A2", "A3")


def load_cases() -> list[dict[str, Any]]:
    return [json.loads(line) for line in
            (FIXTURE / "cases.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()]


def build_maps(case: dict[str, Any],
               records: dict[tuple[int, str], dict]) -> dict[str, Any]:
    """Term -> record pointers per partition (verifiable map)."""
    maps = {}
    for part in case["partitions"]:
        entries: dict[str, list[dict[str, str]]] = {}
        texts = []
        for rid in part["record_ids"]:
            record = records[(case["case"], rid)]
            text = f"{record['summary']} {record['why']}".strip()
            texts.append(text)
            for token in set(tokenize(text)):
                entries.setdefault(token, []).append(
                    {"memory_id": rid, "date": record["created_at"][:10]})
        maps[part["partition_id"]] = {
            "terms": entries,
            "texts": texts,
            "record_ids": list(part["record_ids"]),
        }
    return maps


def partition_scores(question: str, maps: dict[str, Any]) -> list[tuple[float, str]]:
    scores = []
    for pid in sorted(maps):
        inner = bm25(question, maps[pid]["texts"])
        score = max(inner) if inner else 0.0
        scores.append((round(score, 4), pid))
    scores.sort(key=lambda item: (-item[0], item[1]))
    return scores


def token_coverage(question: str, maps: dict[str, Any],
                   consulted: list[str]) -> float:
    q_tokens = set(tokenize(question))
    if not q_tokens:
        return 1.0
    union: set[str] = set()
    for pid in consulted:
        for text in maps[pid]["texts"]:
            union |= set(tokenize(text))
    return round(len(q_tokens & union) / len(q_tokens), 4)


def consult(case: dict[str, Any], maps: dict[str, Any], arm: str) -> list[str]:
    order = [pid for _score, pid in partition_scores(case["question"], maps)]
    if arm == "A0":
        return order
    if arm == "A1":
        return order[:1]
    if arm == "A2":
        _cases, records = dc.load_fixture(HERE / "fixtures" / "composition_u4")
        part_of = {rid: part["partition_id"] for part in case["partitions"]
                   for rid in part["record_ids"]}
        texts = {rid: f"{records[(case['case'], rid)]['summary']} "
                      f"{records[(case['case'], rid)]['why']}"
                 for rid in part_of}
        flat = sorted(texts)
        scores = bm25(case["question"], [texts[rid] for rid in flat])
        top = sorted(range(len(flat)), key=lambda i: -scores[i])[:3]
        return sorted({order[0], *[part_of[flat[i]] for i in top]})
    # A3: map order + verification against the tape
    consulted: list[str] = []
    for pid in order:
        consulted.append(pid)
        if (token_coverage(case["question"], maps, consulted) >= TAU
                or len(consulted) >= K_MAX):
            break
    return consulted


def collect() -> dict[str, Any]:
    cases = load_cases()
    _cases, records = dc.load_fixture(HERE / "fixtures" / "composition_u4")
    rows = []
    map_pointer_ok = True
    for case in cases:
        maps = build_maps(case, records)
        for pid, entry in maps.items():
            for token, pointers in entry["terms"].items():
                if not pointers or not all(p.get("memory_id") and p.get("date")
                                           for p in pointers):
                    map_pointer_ok = False
        required = set(case["required"])
        entry = {"block": case["block"], "case": case["case"],
                 "required": sorted(required), "arms": {}}
        for arm in ARMS:
            consulted = consult(case, maps, arm)
            hosted = {rid for pid in consulted
                      for rid in maps[pid]["record_ids"]}
            entry["arms"][arm] = {
                "consulted": consulted,
                "routing_coverage": round(len(required & hosted) / len(required), 4)
                if required else 1.0,
            }
        entry["coverage_after_verify"] = token_coverage(
            case["question"], maps, entry["arms"]["A3"]["consulted"])
        rows.append(entry)

    def coverage(arm: str) -> float:
        return round(sum(e["arms"][arm]["routing_coverage"] for e in rows)
                     / len(rows), 4) if rows else 0.0

    consulted = {arm: sum(len(e["arms"][arm]["consulted"]) for e in rows)
                 for arm in ARMS}
    report = {
        "prereg": "docs/AGENT_MAP_V1_PREREG.md",
        "cases": len(rows), "rows": rows,
        "routing_coverage": {arm: coverage(arm) for arm in ARMS},
        "consulted_partitions": consulted,
        "gates": {
            "L1_no_case_lost": all(
                e["arms"]["A3"]["routing_coverage"]
                >= e["arms"]["A0"]["routing_coverage"] for e in rows),
            "L2_fewer_activations": consulted["A3"] < consulted["A0"],
            "L3_vs_union": consulted["A3"] <= consulted["A2"],
            "L5_pointers": map_pointer_ok,
        },
    }
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out",
                        default=str(HERE / "results" / "agent_map_v1"))
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    report = collect()
    second = collect()
    report["gates"]["L4_determinism"] = (
        json.dumps(report["rows"], sort_keys=True)
        == json.dumps(second["rows"], sort_keys=True))
    report["all_pass"] = all(report["gates"].values())
    report["scope_limit"] = ("K=2 artificial partitions test the routing "
                             "mechanism; real economy is measured only in "
                             "the shadow addendum at met:true")
    (out / "report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8")
    lines = ["# agent-map-v1", "",
             f"- cases: {report['cases']} · routing coverage: "
             f"{json.dumps(report['routing_coverage'], sort_keys=True)}",
             f"- consulted partitions: "
             f"{json.dumps(report['consulted_partitions'], sort_keys=True)}",
             "", f"gates: {json.dumps(report['gates'], sort_keys=True)}",
             f"all_pass: {report['all_pass']}", "",
             f"scope: {report['scope_limit']}"]
    markdown = "\n".join(lines) + "\n"
    (out / "report.md").write_text(markdown, encoding="utf-8")
    print(markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
