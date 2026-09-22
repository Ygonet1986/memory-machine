#!/usr/bin/env python3
"""Deterministic generator for the admission-synthetic-v1 fixture.

Builds 10 scenarios x 10 cases with **known gold evidence** - no LLM, no
randomness, pure templates and index arithmetic. Each case is an isolated
mini-tape: records (id/type/summary/why/created_at), one question, the gold
memory ids, and the expected behavior ("deliver" or "abstain").

The scenarios cover the ten situations declared in
``docs/ADMISSION_SYNTHETIC_V1_PREREG.md``. Regenerating must be byte-identical
(enforced by ``eval/validate_admission_synthetic_v1.py``).

    python3 eval/gen_admission_synthetic_v1.py --out eval/fixtures/admission_synthetic_v1
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date, timedelta
from pathlib import Path

GENERATOR_VERSION = 2
CASES_PER_SCENARIO = 10
SCENARIOS = (
    "easy_single",
    "near_duplicate",
    "corrected",
    "shared_subject",
    "short_ambiguous",
    "long_specific",
    "no_answer",
    "old_vs_recent",
    "multi_memory",
    "distractor_volume",
)
PROJECTS = ("Atlas", "Boreal", "Cobalt", "Delta")
CODENAMES = ("kestrel", "marlin", "onix", "sable", "tundra",
             "vulcan", "zephyr", "coral", "lupus", "nimbus")


def _iso(offset_days: int) -> str:
    return (date(2026, 1, 1) + timedelta(days=offset_days)).isoformat()


def _rec(case_id: str, number: int, rtype: str, summary: str, why: str,
         offset_days: int) -> dict[str, str]:
    return {
        "memory_id": f"{case_id}-R{number:02d}",
        "type": rtype,
        "summary": summary,
        "why": why,
        "created_at": _iso(offset_days),
    }


def _case(scenario: str, index: int, question: str,
          records: list[dict[str, str]], gold_records: list[dict[str, str]],
          expectation: str = "deliver") -> dict[str, object]:
    """Renumber records, then resolve gold from the mutated refs.

    Generator v2 fix: v1 passed gold ids computed before renumbering, which
    mapped S1's gold to the wrong record.
    """
    code = SCENARIOS.index(scenario) + 1
    case_id = f"S{code}-{index:02d}"
    for number, record in enumerate(records, start=1):
        record["memory_id"] = f"{case_id}-R{number:02d}"
    return {
        "case_id": case_id,
        "scenario": scenario,
        "question": question,
        "records": records,
        "gold": [record["memory_id"] for record in gold_records],
        "expectation": expectation,
    }


def _distractors(case_id: str, project: str, count: int) -> list[dict[str, str]]:
    topics = (
        "deploy pipeline", "logging format", "timezone handling", "retry policy",
        "metrics endpoint", "backup cadence", "release checklist", "style guide",
        "incident rotation", "alert thresholds",
    )
    out = []
    for j in range(count):
        topic = topics[j % len(topics)]
        out.append(_rec(case_id, j + 1, "decision",
                        f"{topic.title()} decided for {project}",
                        f"agreed in the {project} sync", 2 + j))
    return out


def build_cases() -> list[dict[str, object]]:
    cases: list[dict[str, object]] = []

    for i in range(1, CASES_PER_SCENARIO + 1):
        project = PROJECTS[(i - 1) % len(PROJECTS)]
        code = CODENAMES[i - 1]
        cid = f"S1-{i:02d}"
        records = _distractors(cid, project, 8)
        gold_rec = _rec(cid, 9, "decision",
                        f"Decision on {code}: use the {code} queue for ingestion",
                        f"the {code} codename was chosen for {project} ingestion", 15)
        records.insert(4, gold_rec)
        cases.append(_case("easy_single", i,
                           f"What was decided about {code} in {project}?",
                           records, [gold_rec]))

    for i in range(1, CASES_PER_SCENARIO + 1):
        project = PROJECTS[(i - 1) % len(PROJECTS)]
        cid = f"S2-{i:02d}"
        endpoints = ("/v1/orders", "/v2/orders", "/v1/users", "/v2/users",
                     "/v2/invoices")
        records = []
        for j, endpoint in enumerate(endpoints):
            prefix = endpoint.strip("/").replace("/", ":")
            records.append(_rec(
                cid, j + 1, "decision",
                f"Cache strategy for {endpoint} in {project}: TTL 300s and key prefix {prefix}",
                "stale-while-revalidate enabled", 10 + j))
        records.append(_rec(cid, 6, "lesson",
                            f"Cache keys must include the API version in {project}",
                            "a version bump served stale payloads", 20))
        cases.append(_case("near_duplicate", i,
                           f"Which cache settings apply to /v2/orders in {project}?",
                           records, [records[1]]))

    for i in range(1, CASES_PER_SCENARIO + 1):
        project = PROJECTS[(i - 1) % len(PROJECTS)]
        cid = f"S3-{i:02d}"
        records = [
            _rec(cid, 1, "decision",
                 f"Use SQLite for {project} metrics store",
                 "zero-ops, single writer", 3),
            _rec(cid, 2, "lesson",
                 f"{project} deploy uses blue/green",
                 "rollback is one switch", 5),
            _rec(cid, 3, "decision",
                 f"Correction: {project} metrics store moved to Postgres",
                 "SQLite lock contention under load; supersedes the earlier decision",
                 21),
            _rec(cid, 4, "build",
                 f"{project} metrics exporter v2 shipped",
                 "reads from the new store", 25),
            _rec(cid, 5, "decision",
                 f"Alert thresholds set for {project}",
                 "p95 latency above 400ms pages", 12),
            _rec(cid, 6, "preference",
                 f"{project} dashboards use the team palette",
                 "readability", 8),
        ]
        cases.append(_case("corrected", i,
                           f"Which database do we use for {project} metrics now?",
                           records, [records[2]]))

    for i in range(1, CASES_PER_SCENARIO + 1):
        cid = f"S4-{i:02d}"
        records = [
            _rec(cid, 1, "decision", "Atlas cache strategy: Redis with 5 minute TTL",
                 "shared across services", 6),
            _rec(cid, 2, "decision", "Boreal cache strategy: CDN edge cache with 60s TTL",
                 "mobile clients need low latency", 9),
            _rec(cid, 3, "lesson", "Atlas cache stampede during deploys",
                 "add jitter to TTLs", 14),
            _rec(cid, 4, "decision", "Atlas uses a read-through cache for catalog",
                 "catalog reads dominate", 11),
            _rec(cid, 5, "lesson", "Boreal cache invalidation after releases",
                 "version keys avoid stale payloads", 18),
            _rec(cid, 6, "decision", "Boreal cache layer runs in the edge region",
                 "latency budget is 80ms", 22),
            _rec(cid, 7, "build", "Atlas cache client v3 shipped",
                 "connection pooling", 16),
            _rec(cid, 8, "preference", "Boreal prefers explicit cache keys",
                 "debuggability", 20),
        ]
        cases.append(_case("shared_subject", i,
                           "In project Boreal, which cache strategy was chosen?",
                           records, [records[1]]))

    for i in range(1, CASES_PER_SCENARIO + 1):
        cid = f"S5-{i:02d}"
        records = [
            _rec(cid, 1, "decision", "Atlas cache: in-memory LRU per worker",
                 "simple and fast", 5),
            _rec(cid, 2, "decision", "Boreal cache: CDN edge caching",
                 "mobile latency budget", 12),
            _rec(cid, 3, "decision", "Cobalt cache: Redis cluster with 10s TTL",
                 "shared sessions", 27),
            _rec(cid, 4, "lesson", "Cobalt cache eviction spikes at noon",
                 "warm up before peak", 13),
            _rec(cid, 5, "decision", "Cobalt rate limits set to 50 rps",
                 "protect the origin", 24),
            _rec(cid, 6, "build", "Cobalt cache client upgraded",
                 "metrics added", 26),
        ]
        cases.append(_case("short_ambiguous", i,
                           "And the cache?",
                           records, [records[2]]))

    for i in range(1, CASES_PER_SCENARIO + 1):
        project = PROJECTS[(i - 1) % len(PROJECTS)]
        cid = f"S6-{i:02d}"
        records = [
            _rec(cid, 1, "decision",
                 f"{project} nightly export: batch size 500, retry limit 3, strict idempotency keys",
                 "idempotency required by the audit", 17),
            _rec(cid, 2, "decision",
                 f"{project} nightly export: batch size 200, retry limit 5",
                 "legacy defaults before the audit", 4),
            _rec(cid, 3, "lesson",
                 f"{project} export throttling during peak hours",
                 "schedule after 02:00", 10),
            _rec(cid, 4, "decision",
                 f"{project} import job: batch size 500 without idempotency",
                 "one-off migration", 15),
            _rec(cid, 5, "build",
                 f"{project} export worker rewritten",
                 "streaming writer", 19),
            _rec(cid, 6, "preference",
                 f"{project} logs keep 30 days",
                 "cost control", 7),
        ]
        cases.append(_case(
            "long_specific", i,
            (f"For the {project} ingest job, what batch size and retry limit "
             "were set for the nightly export with the strict idempotency "
             "requirement?"),
            records, [records[0]]))

    for i in range(1, CASES_PER_SCENARIO + 1):
        project = PROJECTS[(i - 1) % len(PROJECTS)]
        cid = f"S7-{i:02d}"
        records = [
            _rec(cid, 1, "decision", f"{project} review cadence is biweekly",
                 "keeps scope tight", 6),
            _rec(cid, 2, "lesson", f"{project} rollout needs a canary step",
                 "caught a bad build", 9),
            _rec(cid, 3, "decision", f"{project} uses trunk-based development",
                 "small merges", 13),
            _rec(cid, 4, "preference", f"{project} prefers UTC timestamps",
                 "avoids DST bugs", 16),
            _rec(cid, 5, "build", f"{project} docs site rebuilt",
                 "search enabled", 21),
        ]
        cases.append(_case("no_answer", i,
                           f"What was decided about {project} encryption key rotation?",
                           records, [], expectation="abstain"))

    for i in range(1, CASES_PER_SCENARIO + 1):
        project = PROJECTS[(i - 1) % len(PROJECTS)]
        cid = f"S8-{i:02d}"
        records = [
            _rec(cid, 1, "decision", f"{project} session cache: use Redis",
                 "fast, familiar", 4),
            _rec(cid, 2, "decision",
                 f"{project} session cache: migrate to Valkey",
                 "license change; supersedes Redis", 28),
            _rec(cid, 3, "lesson", f"{project} session TTL kept at 24h",
                 "product requirement", 11),
            _rec(cid, 4, "decision", f"{project} sticky sessions disabled",
                 "cache made them unnecessary", 15),
            _rec(cid, 5, "build", f"{project} session service v4 deployed",
                 "instrumentation added", 24),
            _rec(cid, 6, "preference", f"{project} prefers managed datastores",
                 "operational load", 8),
        ]
        cases.append(_case("old_vs_recent", i,
                           f"What is the current session cache recommendation for {project}?",
                           records, [records[1]]))

    for i in range(1, CASES_PER_SCENARIO + 1):
        cid = f"S9-{i:02d}"
        records = [
            _rec(cid, 1, "decision", "Checkout connection pool set to 20",
                 "matches database limits", 12),
            _rec(cid, 2, "decision", "Checkout request timeout set to 30 seconds",
                 "p99 cancellation budget", 13),
            _rec(cid, 3, "decision", "Checkout retry policy: 2 attempts",
                 "idempotent endpoints only", 14),
            _rec(cid, 4, "lesson", "Checkout pool exhaustion during flash sales",
                 "queueing hides latency", 18),
            _rec(cid, 5, "decision", "Search connection pool set to 8",
                 "lower traffic", 15),
            _rec(cid, 6, "decision", "Search timeout set to 10 seconds",
                 "fast failure for queries", 16),
            _rec(cid, 7, "build", "Checkout service v6 shipped",
                 "new pool metrics", 22),
            _rec(cid, 8, "preference", "Checkout logs include the request id",
                 "tracing", 9),
        ]
        cases.append(_case(
            "multi_memory", i,
            "How are the checkout connection pool and request timeout configured?",
            records, [records[0], records[1]]))

    for i in range(1, CASES_PER_SCENARIO + 1):
        project = PROJECTS[(i - 1) % len(PROJECTS)]
        cid = f"S10-{i:02d}"
        records = []
        themes = ("service", "deploy", "configuration", "database", "endpoint",
                  "logging", "pipeline", "cache")
        for j in range(41):
            theme = themes[j % len(themes)]
            records.append(_rec(
                cid, j + 1, "decision",
                f"{project} {theme} change {j // len(themes) + 1}",
                f"routine {theme} adjustment", 2 + (j % 25)))
        gold_rec = _rec(cid, 42, "build",
                        "etl_runner.py pinned to v3 in the export image",
                        "v4 broke the idempotency keys", 20)
        records.append(gold_rec)
        cases.append(_case("distractor_volume", i,
                           "Which version of etl_runner.py is pinned in the export image?",
                           records, [gold_rec]))

    return cases


def generate(out_dir: Path) -> dict[str, object]:
    cases = build_cases()
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = "".join(
        json.dumps(case, ensure_ascii=False, sort_keys=True) + "\n"
        for case in cases)
    (out_dir / "cases.jsonl").write_text(payload, encoding="utf-8")
    counts = {scenario: sum(1 for c in cases if c["scenario"] == scenario)
              for scenario in SCENARIOS}
    records = sum(len(c["records"]) for c in cases)
    gold = sum(len(c["gold"]) for c in cases)
    manifest = {
        "generator": "gen_admission_synthetic_v1.py",
        "generator_version": GENERATOR_VERSION,
        "seed": None,
        "scenarios": list(SCENARIOS),
        "cases_per_scenario": CASES_PER_SCENARIO,
        "cases": len(cases),
        "counts_by_scenario": counts,
        "records": records,
        "gold_occurrences": gold,
        "abstain_cases": sum(1 for c in cases if c["expectation"] == "abstain"),
        "cases_sha256": hashlib.sha256(payload.encode("utf-8")).hexdigest(),
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="eval/fixtures/admission_synthetic_v1")
    args = parser.parse_args()
    manifest = generate(Path(args.out))
    print(json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
