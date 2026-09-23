#!/usr/bin/env python3
"""agent-map-v2: margin + bounded rescue stopping rule (M1-M5).

Frozen by docs/AGENT_MAP_V2_PREREG.md. Deterministic, no LLM; reuses the
agent_map_v1 helpers and the frozen fixture.

    PYTHONPATH=src:.:eval python3 eval/agent_map_v2.py
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

import agent_map_v1 as am  # noqa: E402
import delivery_combined_v1 as dc  # noqa: E402
from memory_machine.retrieval import bm25  # noqa: E402

MARGIN = 0.5
CAP = 3
RESCUE_K = 3
TAU_REF = 0.5
ARMS = ("B0", "B1", "B2", "B3", "B4")


def _record_scores(case: dict[str, Any], maps: dict[str, Any],
                   records: dict[tuple[int, str], dict]
                   ) -> tuple[list[tuple[str, str]], list[float]]:
    flat = []
    texts = []
    for pid in sorted(maps):
        for rid in maps[pid]["record_ids"]:
            record = records[(case["case"], rid)]
            flat.append((pid, rid))
            texts.append(f"{record['summary']} {record['why']}".strip())
    return flat, bm25(case["question"], texts)


def consult(case: dict[str, Any], maps: dict[str, Any], arm: str,
            records: dict[tuple[int, str], dict]) -> list[str]:
    order = [pid for _score, pid in am.partition_scores(case["question"], maps)]
    if arm == "B0":
        return order
    if arm == "B1":
        return order[:1]

    flat, scores = _record_scores(case, maps, records)
    best = max(scores) if scores else 0.0
    rescue = {flat[i][0] for i in
              sorted(range(len(flat)), key=lambda i: -scores[i])[:RESCUE_K]}
    candidates = {order[0]}
    if arm in ("B2", "B3"):
        for (pid, _rid), score in zip(flat, scores):
            if best > 0 and score >= MARGIN * best:
                candidates.add(pid)
    if arm == "B2":
        candidates |= rescue
    if arm == "B4":
        consulted: list[str] = []
        for pid in order:
            consulted.append(pid)
            if (am.token_coverage(case["question"], maps, consulted) >= TAU_REF
                    or len(consulted) >= CAP):
                break
        return consulted

    def rank(pid: str) -> tuple[int, str]:
        return (order.index(pid), pid)

    chosen = [pid for pid in sorted(candidates, key=rank)][:CAP]
    return sorted(chosen)


def collect() -> dict[str, Any]:
    cases = am.load_cases()
    _cases, records = dc.load_fixture(HERE / "fixtures" / "composition_u4")
    rows = []
    pointer_ok = True
    for case in cases:
        maps = am.build_maps(case, records)
        for entry in maps.values():
            for pointers in entry["terms"].values():
                if not pointers or not all(p.get("memory_id") and p.get("date")
                                           for p in pointers):
                    pointer_ok = False
        required = set(case["required"])
        row = {"block": case["block"], "case": case["case"],
               "required": sorted(required), "arms": {}}
        for arm in ARMS:
            consulted = consult(case, maps, arm, records)
            hosted = {rid for pid in consulted
                      for rid in maps[pid]["record_ids"]}
            row["arms"][arm] = {
                "consulted": consulted,
                "routing_coverage": round(len(required & hosted) / len(required), 4)
                if required else 1.0,
            }
        rows.append(row)

    def coverage(arm: str) -> float:
        return round(sum(e["arms"][arm]["routing_coverage"] for e in rows)
                     / len(rows), 4) if rows else 0.0

    consulted = {arm: sum(len(e["arms"][arm]["consulted"]) for e in rows)
                 for arm in ARMS}
    report = {
        "prereg": "docs/AGENT_MAP_V2_PREREG.md",
        "cases": len(rows), "rows": rows,
        "routing_coverage": {arm: coverage(arm) for arm in ARMS},
        "consulted_partitions": consulted,
        "gates": {
            "M1_no_case_lost": all(
                e["arms"]["B2"]["routing_coverage"]
                >= e["arms"]["B0"]["routing_coverage"] for e in rows),
            "M2_economy": consulted["B2"] < consulted["B0"],
            "M5_pointers": pointer_ok,
        },
    }
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out",
                        default=str(HERE / "results" / "agent_map_v2"))
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    report = collect()
    second = collect()
    report["gates"]["M4_determinism"] = (
        json.dumps(report["rows"], sort_keys=True)
        == json.dumps(second["rows"], sort_keys=True))
    report["all_pass"] = all(report["gates"].values())
    report["scope_limit"] = ("K=2 artificial partitions test the mechanism; "
                             "real (4-group) economy is the shadow addendum "
                             "at met:true")
    (out / "report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8")
    lines = ["# agent-map-v2", "",
             f"- cases: {report['cases']}",
             f"- routing coverage: {json.dumps(report['routing_coverage'], sort_keys=True)}",
             f"- consulted partitions: {json.dumps(report['consulted_partitions'], sort_keys=True)}",
             "", f"gates: {json.dumps(report['gates'], sort_keys=True)}",
             f"all_pass: {report['all_pass']}", "",
             f"scope: {report['scope_limit']}"]
    markdown = "\n".join(lines) + "\n"
    (out / "report.md").write_text(markdown, encoding="utf-8")
    print(markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
