#!/usr/bin/env python3
"""Deterministic generator for the admission-causal-v1 lab fixture.

40 cases (4 scenarios x 10) with known gold and **explicit relations**
(decision -> justified_by -> rationale, decision -> based_on -> evidence).
Design-time invariant, verified with the product BM25 before writing: in
`causal_buried` and `causal_chain` the rationale is buried (rank > 2) while
the decision is discoverable (rank <= 2).

    python3 eval/gen_admission_causal_v1.py --out eval/fixtures/admission_causal_v1
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

from memory_machine.retrieval import bm25  # noqa: E402

GENERATOR_VERSION = 1
CASES_PER_SCENARIO = 10
SCENARIOS = ("causal_buried", "factual_control", "causal_absent", "causal_chain")
PROJECTS = ("Atlas", "Boreal", "Cobalt", "Delta")
SETTINGS = (
    ("payload budget", "4000 characters"),
    ("retry limit", "3 attempts"),
    ("checkout timeout", "30 seconds"),
    ("cache TTL", "300 seconds"),
    ("batch size", "500 rows"),
)


def _iso(offset: int) -> str:
    return (date(2026, 1, 1) + timedelta(days=offset)).isoformat()


def _rec(record_id: str, rtype: str, summary: str, why: str, day: int,
         relations: dict | None = None) -> dict:
    record = {"memory_id": record_id, "type": rtype, "summary": summary,
              "why": why, "created_at": _iso(day)}
    if relations:
        record["relations"] = relations
    return record


def _decoys(case_id: str, project: str, setting: str, value: str,
            count: int) -> list[dict]:
    """High-overlap noise that mentions why/because without justifying."""
    texts = (
        f"{project} {setting} discussion mentioned why the value {value} mattered",
        f"why {project} tracks the {setting} at {value} every quarter",
        f"{project} review asked why {value} for the {setting} because of audits",
        f"the {setting} question for {project}: why {value} and when",
        f"{project} notes on the {setting}: because the value {value} recurs",
        f"why teams compare {project} {setting} values such as {value}",
        f"{project} {setting} history mentions {value} for context only",
    )
    return [_rec(f"{case_id}-D{j+1}", "decision", texts[j % len(texts)],
                 "discussion only, no decision", 4 + j)
            for j in range(count)]


def _case(scenario: str, index: int, question: str, records: list[dict],
          gold_records: list[dict], expectation: str = "deliver") -> dict:
    code = SCENARIOS.index(scenario) + 1
    case_id = f"C{code}-{index:02d}"
    for number, record in enumerate(records, start=1):
        record["memory_id"] = f"{case_id}-R{number:02d}"
    return {"case_id": case_id, "scenario": scenario, "question": question,
            "records": records,
            "gold": [record["memory_id"] for record in gold_records],
            "expectation": expectation}



def _link(case: dict, source_id: str, key: str, target_ids: list[str]) -> None:
    record = next(r for r in case["records"] if r["memory_id"] == source_id)
    record.setdefault("relations", {})[key] = list(target_ids)


def build_cases() -> list[dict]:
    cases: list[dict] = []
    for i in range(1, CASES_PER_SCENARIO + 1):
        project = PROJECTS[(i - 1) % 4]
        setting, value = SETTINGS[(i - 1) % len(SETTINGS)]
        cid = f"C1-{i:02d}"
        decoys = _decoys(cid, project, setting, value, 6)
        decision = _rec("", "decision",
                        f"{project} {setting} set to {value}",
                        "adopted after the compression review", 20)
        rationale = _rec("", "lesson",
                         f"The H3 compression curve showed a knee near {value}",
                         "unlimited context collapsed below the budget in the audit",
                         18)
        records = decoys + [decision, rationale]
        case = _case("causal_buried", i,
                     f"Why was the {setting} set to {value} in {project}?",
                     records, [decision, rationale])
        _link(case, case["gold"][0], "justified_by", [case["gold"][1]])
        cases.append(case)

    for i in range(1, CASES_PER_SCENARIO + 1):
        project = PROJECTS[(i - 1) % 4]
        setting, value = SETTINGS[(i - 1) % len(SETTINGS)]
        cid = f"C2-{i:02d}"
        decoys = _decoys(cid, project, setting, value, 6)
        decision = _rec("", "decision",
                        f"{project} {setting} set to {value}",
                        "adopted after the compression review", 20)
        rationale = _rec("", "lesson",
                         f"The H3 compression curve showed a knee near {value}",
                         "evidence from the audit", 18)
        records = decoys + [decision, rationale]
        case = _case("factual_control", i,
                     f"What is the {setting} for {project}?",
                     records, [decision])
        _link(case, case["gold"][0], "justified_by", [rationale["memory_id"]])
        cases.append(case)

    for i in range(1, CASES_PER_SCENARIO + 1):
        project = PROJECTS[(i - 1) % 4]
        setting, value = SETTINGS[(i - 1) % len(SETTINGS)]
        cid = f"C3-{i:02d}"
        decoys = _decoys(cid, project, setting, value, 7)
        decision = _rec("", "decision",
                        f"{project} {setting} set to {value}",
                        "no justification recorded for this decision", 21)
        records = decoys + [decision]
        cases.append(_case("causal_absent", i,
                           f"Why was the {setting} set to {value} in {project}?",
                           records, [decision]))

    for i in range(1, CASES_PER_SCENARIO + 1):
        project = PROJECTS[(i - 1) % 4]
        setting, value = SETTINGS[(i - 1) % len(SETTINGS)]
        cid = f"C4-{i:02d}"
        decoys = _decoys(cid, project, setting, value, 5)
        old_value = "2500 characters" if setting == "payload budget" else "the old value"
        old = _rec("", "decision", f"{project} {setting} was {old_value}",
                   "the original choice", 6)
        new = _rec("", "decision", f"{project} {setting} change: now {value}",
                   "replaced the original value after the review", 24)
        rationale = _rec("", "lesson",
                         "The compression audit measured a knee in the context curve",
                         "the reason it was approved", 22)
        records = decoys + [old, new, rationale]
        case = _case("causal_chain", i,
                     f"What led to the {setting} change in {project}?",
                     records, [new, rationale])
        _link(case, case["gold"][0], "justified_by", [case["gold"][1]])
        _link(case, case["gold"][0], "supersedes",
              [r["memory_id"] for r in case["records"] if r["type"] == "decision"][-2:-1])
        cases.append(case)
    return cases


def _buried(case: dict, record_id: str) -> int:
    """1-based BM25 rank of a record among the case records (0 = not ranked)."""
    texts = [f"{r['summary']} {r['why']}" for r in case["records"]]
    scores = bm25(case["question"], texts)
    order = sorted(range(len(texts)), key=lambda i: -scores[i])
    ranked = [case["records"][i]["memory_id"] for i in order if scores[i] > 0]
    if record_id in ranked:
        return ranked.index(record_id) + 1
    return len(case["records"]) + 1  # unranked counts as maximally buried


def verify(cases: list[dict]) -> None:
    for case in cases:
        scenario = case["scenario"]
        gold = case["gold"]
        if scenario in {"causal_buried", "causal_chain"}:
            rationale = gold[-1]
            decision = gold[0]
            assert _buried(case, rationale) > 2, (case["case_id"], "rationale not buried")
            assert 1 <= _buried(case, decision) <= 2, (case["case_id"], "decision not discoverable")
        if scenario == "causal_absent":
            assert not any(record.get("relations") for record in case["records"]), \
                (case["case_id"], "relations present in a no-justification case")
        if scenario == "factual_control":
            assert 1 <= _buried(case, gold[0]) <= 2, (case["case_id"], "decision not discoverable")


def generate(out_dir: Path) -> dict:
    cases = build_cases()
    verify(cases)
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = "".join(json.dumps(case, ensure_ascii=False, sort_keys=True) + "\n"
                      for case in cases)
    (out_dir / "cases.jsonl").write_text(payload, encoding="utf-8")
    manifest = {
        "generator": "gen_admission_causal_v1.py",
        "generator_version": GENERATOR_VERSION,
        "scenarios": list(SCENARIOS),
        "cases_per_scenario": CASES_PER_SCENARIO,
        "cases": len(cases),
        "counts_by_scenario": {s: sum(1 for c in cases if c["scenario"] == s)
                               for s in SCENARIOS},
        "records": sum(len(c["records"]) for c in cases),
        "gold_occurrences": sum(len(c["gold"]) for c in cases),
        "buried_verified": sum(
            1 for c in cases
            if c["scenario"] in {"causal_buried", "causal_chain"}),
        "cases_sha256": hashlib.sha256(payload.encode("utf-8")).hexdigest(),
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="eval/fixtures/admission_causal_v1")
    args = parser.parse_args()
    manifest = generate(Path(args.out))
    print(json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
