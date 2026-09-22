#!/usr/bin/env python3
"""Deterministic generator for the admission-causal holdout fixture.

New rationales, relations, decoys and absence cases (different domains and
wording from the exploration fixture). Design-time invariant verified with
the product BM25: rationales buried beyond rank 2, decisions discoverable,
absence cases relation-free.

    python3 eval/gen_admission_causal_holdout.py --out eval/fixtures/admission_causal_holdout
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
SCENARIOS = ("causal_buried", "factual_control", "causal_absent", "causal_chain")
PER_SCENARIO = {"causal_buried": 12, "factual_control": 8,
                "causal_absent": 10, "causal_chain": 10}
PROJECTS = ("Vega", "Orion", "Lyra", "Pavo")
SETTINGS = (
    ("ingest window", "15 minutes"),
    ("schema version", "v7"),
    ("rate limit", "120 requests"),
    ("feature flag", "checkout_v2"),
    ("retention tier", "cold storage"),
)


def _iso(offset: int) -> str:
    return (date(2026, 2, 1) + timedelta(days=offset)).isoformat()


def _rec(rtype: str, summary: str, why: str, day: int) -> dict:
    return {"memory_id": "", "type": rtype, "summary": summary, "why": why,
            "created_at": _iso(day)}


def _decoys(project: str, setting: str, value: str, count: int) -> list[dict]:
    texts = (
        f"{project} discussion about why the {setting} is {value}",
        f"why operators ask about {value} for the {setting} in {project}",
        f"{project} notes: the {setting} at {value} appears in reviews",
        f"why {project} compares {setting} values such as {value}",
        f"{project} retrospective mentions {value} for the {setting}",
        f"the {setting} question for {project} covers {value} briefly",
        f"{project} changelog lists {setting} entries near {value}",
    )
    return [_rec("decision", texts[j % len(texts)],
                 "context note only, no decision", 3 + j)
            for j in range(count)]


def _case(scenario: str, index: int, question: str, records: list[dict],
          gold: list[dict]) -> dict:
    code = SCENARIOS.index(scenario) + 1
    case_id = f"H{code}-{index:02d}"
    for number, record in enumerate(records, start=1):
        record["memory_id"] = f"{case_id}-R{number:02d}"
    return {"case_id": case_id, "scenario": scenario, "question": question,
            "records": records,
            "gold": [record["memory_id"] for record in gold]}


def _link(case: dict, source_id: str, key: str, target_id: str) -> None:
    record = next(r for r in case["records"] if r["memory_id"] == source_id)
    record.setdefault("relations", {})[key] = [target_id]


def build_cases() -> list[dict]:
    cases: list[dict] = []
    for i in range(1, PER_SCENARIO["causal_buried"] + 1):
        project = PROJECTS[(i - 1) % 4]
        setting, value = SETTINGS[(i - 1) % len(SETTINGS)]
        records = _decoys(project, setting, value, 6)
        decision = _rec("decision", f"{project} {setting} set to {value}",
                        "adopted after the capacity review", 19)
        rationale = _rec("lesson",
                         "The capacity study measured a knee in the load curve",
                         "approved by the platform review", 17)
        records += [decision, rationale]
        case = _case("causal_buried", i,
                     f"Why was the {setting} set to {value} in {project}?",
                     records, [decision, rationale])
        _link(case, case["gold"][0], "justified_by", case["gold"][1])
        cases.append(case)

    for i in range(1, PER_SCENARIO["factual_control"] + 1):
        project = PROJECTS[(i - 1) % 4]
        setting, value = SETTINGS[(i - 1) % len(SETTINGS)]
        records = _decoys(project, setting, value, 6)
        decision = _rec("decision", f"{project} {setting} set to {value}",
                        "adopted after the capacity review", 19)
        rationale = _rec("lesson",
                         "The capacity study measured a knee in the load curve",
                         "approved by the platform review", 17)
        records += [decision, rationale]
        case = _case("factual_control", i,
                     f"What is the {setting} for {project}?", records, [decision])
        _link(case, case["gold"][0], "justified_by", rationale["memory_id"])
        cases.append(case)

    for i in range(1, PER_SCENARIO["causal_absent"] + 1):
        project = PROJECTS[(i - 1) % 4]
        setting, value = SETTINGS[(i - 1) % len(SETTINGS)]
        records = _decoys(project, setting, value, 7)
        decision = _rec("decision", f"{project} {setting} set to {value}",
                        "no justification recorded for this decision", 21)
        records.append(decision)
        cases.append(_case("causal_absent", i,
                           f"Why was the {setting} set to {value} in {project}?",
                           records, [decision]))

    for i in range(1, PER_SCENARIO["causal_chain"] + 1):
        project = PROJECTS[(i - 1) % 4]
        setting, value = SETTINGS[(i - 1) % len(SETTINGS)]
        records = _decoys(project, setting, value, 5)
        old = _rec("decision", f"{project} {setting} was the default value",
                   "the original choice", 5)
        new = _rec("decision", f"{project} {setting} change: now {value}",
                   "replaced the original value after the review", 23)
        rationale = _rec("lesson",
                         "The capacity study measured a knee in the load curve",
                         "the reason it was approved", 21)
        records += [old, new, rationale]
        case = _case("causal_chain", i,
                     f"What led to the {setting} change in {project}?",
                     records, [new, rationale])
        _link(case, case["gold"][0], "justified_by", case["gold"][1])
        _link(case, case["gold"][0], "supersedes", old["memory_id"])
        cases.append(case)
    return cases


def _buried(case: dict, record_id: str) -> int:
    texts = [f"{r['summary']} {r['why']}" for r in case["records"]]
    scores = bm25(case["question"], texts)
    order = sorted(range(len(texts)), key=lambda i: -scores[i])
    ranked = [case["records"][i]["memory_id"] for i in order if scores[i] > 0]
    if record_id in ranked:
        return ranked.index(record_id) + 1
    return len(case["records"]) + 1


def verify(cases: list[dict]) -> None:
    for case in cases:
        scenario = case["scenario"]
        if scenario in {"causal_buried", "causal_chain"}:
            assert _buried(case, case["gold"][1]) > 2, (case["case_id"], "rationale visible")
            assert 1 <= _buried(case, case["gold"][0]) <= 2, (case["case_id"], "decision hidden")
        if scenario == "causal_absent":
            assert not any(record.get("relations") for record in case["records"]), \
                (case["case_id"], "relations in absence case")
        if scenario == "factual_control":
            assert 1 <= _buried(case, case["gold"][0]) <= 2, (case["case_id"], "decision hidden")


def generate(out_dir: Path) -> dict:
    cases = build_cases()
    verify(cases)
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = "".join(json.dumps(case, ensure_ascii=False, sort_keys=True) + "\n"
                      for case in cases)
    (out_dir / "cases.jsonl").write_text(payload, encoding="utf-8")
    manifest = {
        "generator": "gen_admission_causal_holdout.py",
        "generator_version": GENERATOR_VERSION,
        "scenarios": list(SCENARIOS),
        "cases": len(cases),
        "counts_by_scenario": {s: sum(1 for c in cases if c["scenario"] == s)
                               for s in SCENARIOS},
        "records": sum(len(c["records"]) for c in cases),
        "gold_occurrences": sum(len(c["gold"]) for c in cases),
        "buried_verified": sum(1 for c in cases
                               if c["scenario"] in {"causal_buried", "causal_chain"}),
        "cases_sha256": hashlib.sha256(payload.encode("utf-8")).hexdigest(),
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="eval/fixtures/admission_causal_holdout")
    args = parser.parse_args()
    print(json.dumps(generate(Path(args.out)), indent=2, ensure_ascii=False,
                     sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
