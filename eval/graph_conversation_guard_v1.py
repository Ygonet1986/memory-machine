#!/usr/bin/env python3
"""graph-conversation-guard-v1: candidate rescue for association-only evidence.

Frozen by docs/GRAPH_CONVERSATION_GUARD_V1_PREREG.md. Deterministic, no LLM:
builds each case's tape + graph from the fixture, prunes to active records
(production rule) and compares three arms:

    U  plain augment (no guard)
    G  promoted guard (floor 0.80, cap 3) over a hub-capped traversal
    C  G + conversation_rescue (floor 0.60, cap 2, association-only paths)

    PYTHONPATH=src python3 eval/graph_conversation_guard_v1.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "src"))

from memory_machine.graph import GraphStore  # noqa: E402
from memory_machine.graph_recall import (  # noqa: E402
    GraphRecall, conversation_rescue, guard_evidence,
)
from memory_machine.tape import MemoryRecord, Tape  # noqa: E402

FIXTURE = HERE / "fixtures" / "graph_conversation_guard_v1"
RESULTS = HERE / "results" / "graph_conversation_guard_v1"


def _load_fixture() -> dict[str, Any]:
    text = (FIXTURE / "cases.json").read_text(encoding="utf-8")
    manifest = json.loads((FIXTURE / "manifest.json").read_text(encoding="utf-8"))
    assert hashlib.sha256(text.encode("utf-8")).hexdigest() == \
        manifest["cases_sha256"], "fixture hash mismatch"
    return json.loads(text)


def _build_case(case: dict[str, Any], base: Path) -> tuple[GraphStore, dict]:
    tape = Tape(base / "tape.jsonl")
    for summary in case["records"]:
        tape.append(MemoryRecord(type="decision", summary=summary))
    store = GraphStore(base / "graph")
    for entity_id, name, kind, memory_id in case["entities"]:
        store.add_entity(name, kind, memory_id, entity_id=entity_id)
        store.add_mention(memory_id, entity_id)
    for source, relation, target, memory_id, confidence in case["relations"]:
        store.add_relation(source, relation, target, memory_id, confidence)
    return store, {"tape": tape}


def _admitted(result: Any) -> set[str]:
    return {item.memory_id for item in result.evidence}


def run_case(case: dict[str, Any], fixture: dict[str, Any],
             base: Path) -> dict[str, Any]:
    store, ctx = _build_case(case, base)
    index = store.index()
    index.prune_to_active({record.id for record in ctx["tape"].read()
                           if record.status == "active"})
    hub = int(fixture["hub_degree"])
    plain = GraphRecall(index, depth=int(fixture["depth"]),
                        hub_degree=0).recall(case["question"])
    capped = GraphRecall(index, depth=int(fixture["depth"]),
                         hub_degree=hub).recall(case["question"])
    promoted = guard_evidence(
        list(capped.evidence),
        min_score=float(fixture["promoted"]["min_score"]),
        max_items=int(fixture["promoted"]["max_items"]))
    rescued = conversation_rescue(
        [item for item in capped.evidence
         if item.memory_id not in {g.memory_id for g in promoted}],
        index,
        min_score=float(fixture["candidate"]["min_score"]),
        max_items=int(fixture["candidate"]["max_items"]))
    candidate = [*promoted, *rescued]
    return {
        "id": case["id"],
        "question": case["question"],
        "plain": sorted(_admitted(plain)),
        "promoted": sorted(g.memory_id for g in promoted),
        "candidate": sorted(g.memory_id for g in candidate),
        "capped_count": len(capped.evidence),
    }


def run(fixture: dict[str, Any], out: Path) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    second: list[dict[str, Any]] = []
    for case in fixture["association_cases"] + fixture["hub_cases"]:
        import tempfile

        base = Path(tempfile.mkdtemp(prefix="gc-guard-"))
        rows.append(run_case(case, fixture, base))
        base2 = Path(tempfile.mkdtemp(prefix="gc-guard-"))
        second.append(run_case(case, fixture, base2))

    association = {case["id"]: case for case in fixture["association_cases"]}
    hub = {case["id"]: case for case in fixture["hub_cases"]}
    by_id = {row["id"]: row for row in rows}

    linked_plain = sum(1 for case_id, case in association.items()
                       if case["linked"] in by_id[case_id]["plain"])
    linked_promoted = sum(1 for case_id, case in association.items()
                          if case["linked"] in by_id[case_id]["promoted"])
    linked_candidate = sum(1 for case_id, case in association.items()
                           if case["linked"] in by_id[case_id]["candidate"])
    noise_plain = sum(1 for case_id, case in hub.items()
                      if case["noise"] in by_id[case_id]["plain"])
    noise_promoted = sum(1 for case_id, case in hub.items()
                         if case["noise"] in by_id[case_id]["promoted"])
    noise_candidate = sum(1 for case_id, case in hub.items()
                          if case["noise"] in by_id[case_id]["candidate"])
    bounded = all(len(row["candidate"]) <= len(row["promoted"])
                  + int(fixture["candidate"]["max_items"]) for row in rows)
    gates = {
        "C1_candidate_recovers_links": linked_candidate == len(association),
        "C2_beats_promoted": linked_candidate > linked_promoted,
        "C3_noise_bounded": (noise_candidate == noise_promoted == 0
                             and noise_plain > 0),
        "C4_determinism": json.dumps(rows, sort_keys=True)
        == json.dumps(second, sort_keys=True),
        "C5_bounded_rescue": bounded,
    }
    report = {
        "prereg": "docs/GRAPH_CONVERSATION_GUARD_V1_PREREG.md",
        "fixture_sha256": hashlib.sha256(
            (FIXTURE / "cases.json").read_text(encoding="utf-8").encode()
        ).hexdigest(),
        "rows": rows,
        "linked": {"plain": linked_plain, "promoted": linked_promoted,
                   "candidate": linked_candidate},
        "noise": {"plain": noise_plain, "promoted": noise_promoted,
                  "candidate": noise_candidate},
        "gates": gates,
        "all_pass": all(gates.values()),
        "scope": ("lab mechanism test; the rescue is opt-in-unwired; adopting "
                  "it as a conversation default needs a new §8 restart"),
    }
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8")
    (out / "report.md").write_text(
        "\n".join(["# graph-conversation-guard-v1", "",
                   f"- linked memories: {json.dumps(report['linked'], sort_keys=True)}",
                   f"- hub noise: {json.dumps(report['noise'], sort_keys=True)}",
                   f"gates: {json.dumps(gates, sort_keys=True)}",
                   f"all_pass: {report['all_pass']}", ""]) + "\n",
        encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(RESULTS))
    args = parser.parse_args()
    report = run(_load_fixture(), Path(args.out))
    print(json.dumps({"linked": report["linked"], "noise": report["noise"],
                      "gates": report["gates"],
                      "all_pass": report["all_pass"]},
                     indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
