#!/usr/bin/env python3
"""Deterministic generator for the admission-portfolio-v1 lab fixture.

80 cases (8 scenarios x 10) with known gold, template-only, no LLM. Isolated
lab artifact: it never touches product code or real shadow data.

    python3 eval/gen_admission_portfolio_v1.py --out eval/fixtures/admission_portfolio_v1
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date, timedelta
from pathlib import Path

GENERATOR_VERSION = 1
CASES_PER_SCENARIO = 10
SCENARIOS = (
    "current_state", "supersession", "origin", "contradiction",
    "related_context", "multi_memory", "no_answer", "distractor_volume",
)
PROJECTS = ("Atlas", "Boreal", "Cobalt", "Delta")
SETTINGS = (
    ("payload budget", "4000 characters", "2500 characters"),
    ("retry limit", "3 attempts", "5 attempts"),
    ("checkout timeout", "30 seconds", "10 seconds"),
    ("cache TTL", "300 seconds", "60 seconds"),
    ("batch size", "500 rows", "200 rows"),
)


def _iso(offset: int) -> str:
    return (date(2026, 1, 1) + timedelta(days=offset)).isoformat()


def _rec(record_id: str, rtype: str, summary: str, why: str, day: int) -> dict:
    return {"memory_id": record_id, "type": rtype, "summary": summary,
            "why": why, "created_at": _iso(day)}


def _case(scenario: str, index: int, question: str, records: list[dict],
          gold_records: list[dict], expectation: str = "deliver") -> dict:
    code = SCENARIOS.index(scenario) + 1
    case_id = f"P{code}-{index:02d}"
    for number, record in enumerate(records, start=1):
        record["memory_id"] = f"{case_id}-R{number:02d}"
    return {"case_id": case_id, "scenario": scenario, "question": question,
            "records": records,
            "gold": [record["memory_id"] for record in gold_records],
            "expectation": expectation}


def _noise(case_id: str, project: str, count: int) -> list[dict]:
    topics = ("deploy pipeline", "logging format", "timezone handling",
              "review cadence", "metrics endpoint", "backup cadence",
              "style guide", "alert thresholds")
    return [
        _rec(f"{case_id}-N{j+1}", "decision",
             f"{topics[j % len(topics)].title()} decided for {project}",
             f"routine {project} decision", 3 + j)
        for j in range(count)
    ]


def build_cases() -> list[dict]:
    cases: list[dict] = []
    for i in range(1, CASES_PER_SCENARIO + 1):
        project = PROJECTS[(i - 1) % 4]
        setting, current, old = SETTINGS[(i - 1) % len(SETTINGS)]
        cid = f"P1-{i:02d}"
        noise = _noise(cid, project, 4)
        old_rec = _rec("", "decision", f"{project} {setting} was {old}",
                       "the original value", 6)
        new_rec = _rec("", "decision", f"{project} {setting} is now {current}",
                       "current configuration", 27)
        records = noise + [old_rec, new_rec]
        cases.append(_case("current_state", i,
                           f"What is the current {setting} for {project}?",
                           records, [new_rec]))

    for i in range(1, CASES_PER_SCENARIO + 1):
        project = PROJECTS[(i - 1) % 4]
        cid = f"P2-{i:02d}"
        noise = _noise(cid, project, 4)
        old_rec = _rec("", "decision", f"Use SQLite for {project} metrics",
                       "zero-ops at the time", 5)
        correction = _rec("", "decision",
                          f"Correction: {project} metrics moved to Postgres",
                          "lock contention; supersedes the earlier decision", 22)
        records = noise + [old_rec, correction]
        cases.append(_case("supersession", i,
                           f"Which database does {project} metrics use now?",
                           records, [correction]))

    for i in range(1, CASES_PER_SCENARIO + 1):
        project = PROJECTS[(i - 1) % 4]
        setting, current, _old = SETTINGS[(i - 1) % len(SETTINGS)]
        cid = f"P3-{i:02d}"
        noise = _noise(cid, project, 4)
        fact = _rec("", "decision",
                    f"{project} {setting} is {current}",
                    "adopted for the payload policy", 18)
        origin = _rec("", "lesson",
                      f"The {setting} value comes from the H3 compression curve "
                      f"documented in docs/PAPER.md for {project}",
                      "measured knee around 4000 characters", 17)
        records = noise + [fact, origin]
        cases.append(_case("origin", i,
                           f"Where does the {setting} value come from in {project}?",
                           records, [fact, origin]))

    for i in range(1, CASES_PER_SCENARIO + 1):
        project = PROJECTS[(i - 1) % 4]
        cid = f"P4-{i:02d}"
        noise = _noise(cid, project, 4)
        older = _rec("", "decision", f"{project} log retention is 30 days",
                     "initial compliance review", 8)
        newer = _rec("", "decision", f"{project} log retention is 90 days",
                     "operations requested a longer window", 26)
        records = noise + [older, newer]
        cases.append(_case("contradiction", i,
                           f"What is the log retention period for {project}?",
                           records, [older, newer]))

    for i in range(1, CASES_PER_SCENARIO + 1):
        project = PROJECTS[(i - 1) % 4]
        cid = f"P5-{i:02d}"
        noise = _noise(cid, project, 4)
        decision = _rec("", "decision",
                        f"{project} truncates the payload deterministically",
                        "relevance-ordered, why cut first", 20)
        rationale = _rec("", "lesson",
                         f"The H3 curve showed a knee near 4000 characters in {project}; "
                         "an unlimited-context run collapsed below the budget",
                         "evidence for the deterministic truncation", 19)
        records = noise + [decision, rationale]
        cases.append(_case("related_context", i,
                           f"Why does {project} truncate the payload deterministically?",
                           records, [decision, rationale]))

    for i in range(1, CASES_PER_SCENARIO + 1):
        project = PROJECTS[(i - 1) % 4]
        cid = f"P6-{i:02d}"
        noise = _noise(cid, project, 4)
        pool = _rec("", "decision", f"{project} connection pool set to 20",
                    "matches database limits", 12)
        timeout = _rec("", "decision",
                       f"{project} request timeout set to 30 seconds",
                       "p99 cancellation budget", 13)
        records = noise + [pool, timeout]
        cases.append(_case("multi_memory", i,
                           f"How are the {project} connection pool and request timeout configured?",
                           records, [pool, timeout]))

    for i in range(1, CASES_PER_SCENARIO + 1):
        project = PROJECTS[(i - 1) % 4]
        cid = f"P7-{i:02d}"
        records = _noise(cid, project, 5)
        cases.append(_case("no_answer", i,
                           f"What was decided about {project} encryption key rotation?",
                           records, [], expectation="abstain"))

    for i in range(1, CASES_PER_SCENARIO + 1):
        project = PROJECTS[(i - 1) % 4]
        cid = f"P8-{i:02d}"
        records = [ _rec(f"{cid}-N{j+1}", "decision",
                         f"{project} change {j // 8 + 1}",
                         "routine adjustment", 2 + (j % 25))
                    for j in range(41) ]
        match = _rec("", "build",
                     "etl_runner.py pinned to v3 in the export image",
                     "v4 broke the idempotency keys", 20)
        records.append(match)
        cases.append(_case("distractor_volume", i,
                           "Which version of etl_runner.py is pinned?",
                           records, [match]))
    return cases


def generate(out_dir: Path) -> dict:
    cases = build_cases()
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = "".join(json.dumps(case, ensure_ascii=False, sort_keys=True) + "\n"
                      for case in cases)
    (out_dir / "cases.jsonl").write_text(payload, encoding="utf-8")
    counts = {scenario: sum(1 for c in cases if c["scenario"] == scenario)
              for scenario in SCENARIOS}
    manifest = {
        "generator": "gen_admission_portfolio_v1.py",
        "generator_version": GENERATOR_VERSION,
        "scenarios": list(SCENARIOS),
        "cases_per_scenario": CASES_PER_SCENARIO,
        "cases": len(cases),
        "counts_by_scenario": counts,
        "records": sum(len(c["records"]) for c in cases),
        "gold_occurrences": sum(len(c["gold"]) for c in cases),
        "abstain_cases": sum(1 for c in cases if c["expectation"] == "abstain"),
        "cases_sha256": hashlib.sha256(payload.encode("utf-8")).hexdigest(),
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="eval/fixtures/admission_portfolio_v1")
    args = parser.parse_args()
    manifest = generate(Path(args.out))
    print(json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
