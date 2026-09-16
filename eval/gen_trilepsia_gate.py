#!/usr/bin/env python3
"""B2 vs B2+ gate — deterministic corpus/case generator (and frozen build).

Implements `docs/TRILEPSIA_GATE_SPEC.md` (commit 538077a). Phases, in the
frozen order (the spec's contamination rule: extraction is frozen BEFORE the
cases/gold exist and never reads them):

    --phase docs      write the 10 planted documents (deterministic)
    --phase build     one-time LLM extraction (graph + trilepsia units) over
                      the documents; writes the frozen machine root
    --phase cases     write cases.jsonl (deterministic; never reads extraction)
    --phase manifest  write manifest.json (digests of every frozen artifact)

Everything except `build` is deterministic and offline. No question or gold
ever enters extraction: `docs`/`cases` are pure data, and `build` uses the
document layer + `trilepsia ingest` only.

Run: PYTHONPATH=src python3 eval/gen_trilepsia_gate.py --phase docs|build|cases|manifest
     [--out eval/fixtures/trilepsia_gate_v1]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "src"))

SCHEMA = "gate_claims_v1"
WINDOW_CHARS = 12000

# ---------------------------------------------------------------------------
# Planted constants (the single source for documents AND gold)

K = {
    "reported_hit_rate": 80,          # D1, second-hand
    "measured_hit_rate": 71.4,        # D2, metrics tool
    "p95_normal": 350,                # D6, cache enabled
    "p95_degraded": 620,              # D6, cache disabled
    "reported_failures_a": 12,        # D5, customer A
    "reported_failures_b": 4,         # D5, customer B
    "restore_failures": 5,            # D7, failures during the ttl-restore hour
    "old_ttl": 300,                   # D4, update 2.2
    "new_ttl": 120,                   # D4, update 2.3
    "weeks": {"W1": 120, "W2": 150, "W3": 175, "W4": 160, "W5": 190, "W6": 205},
    "severe_p95": 500,                # D8 convention
}

D1 = f"""Nimbus weekly project log (week of 2026-03-02)

Monday: deployment review for the gateway. The team agreed to keep the current
rollout plan. No blocking issues were raised.

Tuesday: design review for the metering service; the team decided to defer the
schema change to 2.4. Action item: revisit in two weeks.

Wednesday: Dev mentioned that the cache hit rate is about {K['reported_hit_rate']}%
since the update. This number came from a team conversation, not from the
metrics pipeline, and nobody has verified it against the dashboard yet.

Thursday: incident follow-up meeting. The gateway had restarted twice in the
week. The team took notes but did not run any controlled test; no instrumentation
was changed and no rollback was attempted.

Friday: roadmap check. The team agreed that any claim about the root cause of
the restarts still needs evidence before it goes into the release notes.
"""

D2 = f"""Metrics pipeline export (gateway service)

Date range: 2026-02-24 to 2026-03-06. Instrument: metrics-dashboard v1,
aggregation window 5 minutes, service label "nimbus-gateway".

p95 latency per day (cache enabled, production load):
  2026-02-24 362 ms | 2026-02-25 355 ms | 2026-02-26 349 ms | 2026-02-27 351 ms
  2026-02-28 344 ms | 2026-03-01 358 ms | 2026-03-02 355 ms | 2026-03-03 361 ms
  2026-03-04 350 ms | 2026-03-05 347 ms | 2026-03-06 353 ms

Cache counters (same instrument, service "nimbus-gateway"):
  cache hit rate measured {K['measured_hit_rate']}% on 2026-03-02.
  cache hit rate measured 70.8% on 2026-03-05.

Note from the on-call engineer: the {K['reported_hit_rate']}% figure discussed in
the project log does not match this export; the export is the instrument of
record for latency and cache counters.
"""

D3 = f"""Incident note — gateway restarts

Timeline:
  2026-03-01 22:10  update 2.3 deployed by the release bot.
  2026-03-03 09:14  gateway restarted (automatic recovery, 38 s outage).
  2026-03-03 17:40  gateway restarted again (automatic recovery, 25 s outage).

Observed: both restarts happened after the 2.3 deployment. Before 2.3, the
service had been stable for 21 days in this environment.

Not observed: no memory dump was captured, no configuration drift check ran,
and the restarts were never reproduced under control. One unrelated config
change (log level) was also deployed on 2026-03-02.

Conclusion of the note: the temporal association is documented, but no
intervention was performed and no mechanism was tested; the note does not
establish that 2.3 caused the restarts, and alternative explanations
(configuration drift, pre-existing defect) remain open.
"""

D4 = f"""Release changelog — gateway

2.1  cache introduced; default ttl={K['old_ttl']} s.
2.2  cache metrics added; ttl unchanged (ttl={K['old_ttl']} s).
2.3  cache eviction rework: the default ttl changed from {K['old_ttl']} s to
     {K['new_ttl']} s. This update supersedes 2.2; the ttl={K['old_ttl']} s
     setting is no longer in effect after the 2.3 rollout.
2.4  (planned) metering schema change; no cache changes planned.

Operator note: for any question about the current default, read 2.3; the
older value belongs to a superseded release. The changelog is the source of
record for the current configuration value.
"""

D5 = f"""Support thread — failure counts (exported 2026-03-04)

Message 1 — customer A: "We saw {K['reported_failures_a']} failures in our
gateway calls in the first week of March. We are sure of the count because our
retry logs are complete."

Message 2 — customer B: "We only saw {K['reported_failures_b']} failures in the
same window, same region. Our logs also look complete."

Message 3 — support: "The two reports disagree and neither side has shared raw
logs. We have not been able to reproduce either count independently. Until
those logs are provided, the number of failures in that window is contested;
do not act on a single number."

Message 4 — customer A: "We will share logs next week."
"""

D6 = f"""Experiment log — cache effect on latency (controlled)

Setup: staging gateway, fixed load generator (600 req/s), same build, same
dataset. One variable changed at a time.

Run A (cache enabled): p95 = {K['p95_normal']} ms over 30 minutes.
Run B (cache disabled): p95 = {K['p95_degraded']} ms over 30 minutes.
Order: A then B; the load generator and dataset were unchanged; the only
difference between runs was the cache flag.

Interpretation: under this controlled setup (same load, same build, cache the
only difference), the cache reduces p95 latency by {K['p95_degraded'] - K['p95_normal']} ms
relative to the disabled run. The claim "the cache reduces p95 under this
load" is supported by this experiment; the experiment does not speak to other
loads or to production incidents.
"""

D7 = f"""Hypothesis test — ttl cause claim

Claim under test: "the ttl={K['new_ttl']} s change causes the gateway failures."

Test: for one hour on 2026-03-04, the gateway ran with ttl restored to
{K['old_ttl']} s (a controlled intervention; only the ttl changed, the 2.3
build stayed deployed).

Result: {K['restore_failures']} failures occurred during the restore hour,
within the same range as the preceding hours with ttl={K['new_ttl']} s.

Conclusion: under this test (restored ttl, same build), the failures
continued, so the claim "ttl={K['new_ttl']} s causes the failures" is refuted
under the tested condition. The test does not identify what else causes them;
it only removes this candidate under the stated condition.
"""

D8 = f"""Project conventions and scope (Nimbus gateway)

- "severe": any p95 latency above {K['severe_p95']} ms, measured by the metrics
  pipeline (not by user reports).
- "ttl" is measured in seconds.
- "failure": a gateway restart with automatic recovery, as recorded by the
  supervisor log; user-side errors are counted separately.
- Scope: these conventions apply to the Nimbus gateway only. Other services
  keep their own thresholds and are out of scope for this document.

Terminology note: a user report is not a measurement. A measurement is
produced by an instrument named in the record (dashboard, probe, supervisor
log). When a value has both a report and a measurement, the measurement is the
instrument of record.
"""

D9 = f"""Capacity planning table — weekly units

Week | units shipped
W1   | {K['weeks']['W1']}
W2   | {K['weeks']['W2']}
W3   | {K['weeks']['W3']}
W4   | {K['weeks']['W4']}
W5   | {K['weeks']['W5']}
W6   | {K['weeks']['W6']}

Notes: counts are whole units, verified against the warehouse ledger. The
table is the source of record for weekly units; no adjustments were applied.
The February error count is not in this table (see the vendor note).
"""

D10 = f"""Vendor note — missing data

The vendor was asked for the February error count for the gateway. As of
2026-03-06 the vendor has not replied; no copy of the February count exists in
our systems (the export starts 2026-02-24 and contains no error-count column).

Status: the February error count is currently unknown and cannot be determined
from the available records. Any statement of a February error count would be a
guess; the correct state of this datum is indeterminate, not zero.
"""

DOCS: dict[str, str] = {
    "project-log.txt": D1,
    "measurements.txt": D2,
    "incident.txt": D3,
    "changelog.txt": D4,
    "support-thread.txt": D5,
    "experiment.txt": D6,
    "refutation.txt": D7,
    "conventions.txt": D8,
    "capacity-table.txt": D9,
    "vendor-note.txt": D10,
}


def _case(case_id: str, klass: str, ctype: str, question: str, gold: str,
          state: Any, refs: list[str], notes: str = "") -> dict[str, Any]:
    return {
        "case_id": case_id,
        "class": klass,
        "type": ctype,
        "question": question,
        "gold_answer": gold,
        "gold_state": state,
        "required_refs": refs,
        "notes": notes,
    }


def build_cases() -> list[dict[str, Any]]:
    weeks = K["weeks"]
    total = sum(weeks.values())
    mx = max(weeks.values())
    mn = min(weeks.values())
    delta = K["p95_degraded"] - K["p95_normal"]
    cases: list[dict[str, Any]] = [
        # ---- factual (20): joins / arithmetic / max-min / ratios
        _case("g001", "factual", "difference",
              "By how many milliseconds did p95 drop with the cache enabled in the controlled experiment?",
              f"{delta} ms", None, ["experiment.txt"],
              "620 - 350"),
        _case("g002", "factual", "difference",
              "What is the gap between the reported cache hit rate and the measured one?",
              f"{K['reported_hit_rate'] - K['measured_hit_rate']:.1f} percentage points",
              None, ["project-log.txt", "measurements.txt"]),
        _case("g003", "factual", "sum",
              "What is the total number of units shipped across W1 to W6?",
              str(total), None, ["capacity-table.txt"]),
        _case("g004", "factual", "max_min",
              "What is the difference between the best and the worst week in the capacity table?",
              str(mx - mn), None, ["capacity-table.txt"]),
        _case("g005", "factual", "value",
              "What is the current default cache ttl for the gateway?",
              f"{K['new_ttl']} s", None, ["changelog.txt"]),
        _case("g006", "factual", "value",
              "What was the default cache ttl before update 2.3?",
              f"{K['old_ttl']} s", None, ["changelog.txt"]),
        _case("g007", "factual", "sum",
              "How many units were shipped in W1 and W2 combined?",
              str(weeks["W1"] + weeks["W2"]), None, ["capacity-table.txt"]),
        _case("g008", "factual", "sum",
              "How many units were shipped in W3 through W6 combined?",
              str(weeks["W3"] + weeks["W4"] + weeks["W5"] + weeks["W6"]), None,
              ["capacity-table.txt"]),
        _case("g009", "factual", "difference",
              "How many more units were shipped in W6 than in W1?",
              str(weeks["W6"] - weeks["W1"]), None, ["capacity-table.txt"]),
        _case("g010", "factual", "value",
              "What is the measured cache hit rate on 2026-03-02?",
              f"{K['measured_hit_rate']}%", None, ["measurements.txt"]),
        _case("g011", "factual", "value",
              "What is the p95 latency measured with the cache disabled in the controlled experiment?",
              f"{K['p95_degraded']} ms", None, ["experiment.txt"]),
        _case("g012", "factual", "value",
              "What is the p95 latency measured with the cache enabled in the controlled experiment?",
              f"{K['p95_normal']} ms", None, ["experiment.txt"]),
        _case("g013", "factual", "count",
              "How many failures were recorded during the ttl-restore test hour?",
              str(K["restore_failures"]), None, ["refutation.txt"]),
        _case("g014", "factual", "count",
              "How many gateway restarts are listed in the incident note?",
              "2", None, ["incident.txt"]),
        _case("g015", "factual", "value",
              "What p95 threshold defines a 'severe' latency in this project?",
              f"{K['severe_p95']} ms", None, ["conventions.txt"]),
        _case("g016", "factual", "sum",
              "What is the average weekly shipped units over W1 to W6 (rounded down)?",
              str(total // 6), None, ["capacity-table.txt"],
              "sum//6"),
        _case("g017", "factual", "difference",
              "How many more units were shipped in W5 than in W4?",
              str(weeks["W5"] - weeks["W4"]), None, ["capacity-table.txt"]),
        _case("g018", "factual", "value",
              "Which update superseded 2.2?",
              "2.3", None, ["changelog.txt"]),
        _case("g019", "factual", "value",
              "When was update 2.3 deployed, per the incident note?",
              "2026-03-01 22:10", None, ["incident.txt"]),
        _case("g020", "factual", "count",
              "How many weeks are listed in the capacity table?",
              "6", None, ["capacity-table.txt"]),
        # ---- epistemic (16)
        _case("e001", "epistemic", "reported_vs_measured",
              "What is the epistemic status of the 80% cache hit rate figure?",
              "It is a reported figure, not a measured one; the number came from a team "
              "conversation and was never verified against the metrics pipeline.",
              "reported", ["project-log.txt"],
              "B2 head-payload may deliver the number without the qualifier sentence"),
        _case("e002", "epistemic", "reported_vs_measured",
              "What is the epistemic status of the 71.4% cache hit rate figure?",
              "It is an observed measurement from the metrics dashboard.",
              "observed", ["measurements.txt"]),
        _case("e003", "epistemic", "contested",
              "How many gateway failures were reported in the first week of March?",
              "The count is contested: customer A reported 12 and customer B reported 4 "
              "for the same window, and neither raw log set has been provided.",
              "contested", ["support-thread.txt"]),
        _case("e004", "epistemic", "contested",
              "Is the number of failures in the first week of March settled?",
              "No. Two conflicting reports (12 vs 4) remain unresolved; the count is contested.",
              "contested", ["support-thread.txt"]),
        _case("e005", "epistemic", "refuted_under_X",
              "Is the claim that ttl=120 s causes the gateway failures supported?",
              "No. Under the ttl-restore test (same build, ttl back to 300 s for one "
              "hour) failures continued, so the claim is refuted under that tested condition.",
              "refuted", ["refutation.txt", "changelog.txt"]),
        _case("e006", "epistemic", "refuted_under_X",
              "What happened to the hypothesis that the ttl change causes the failures?",
              "It was refuted under the ttl-restore condition; the test only removes this "
              "candidate under the stated condition.",
              "refuted", ["refutation.txt"]),
        _case("e007", "epistemic", "supported_under_X",
              "Does the cache reduce p95 latency?",
              "It is supported under the controlled staging setup (600 req/s, same build, "
              "cache the only difference): p95 350 ms enabled vs 620 ms disabled.",
              "supported", ["experiment.txt"]),
        _case("e008", "epistemic", "supported_under_X",
              "Under which conditions is the cache latency benefit supported?",
              "Under the controlled staging experiment (same load and build, cache the only "
              "variable); it does not speak to other loads or to production incidents.",
              "supported", ["experiment.txt"]),
        _case("e009", "epistemic", "superseded",
              "What happened to the ttl=300 s setting?",
              "It is superseded: update 2.3 replaced it with ttl=120 s.",
              "superseded", ["changelog.txt"]),
        _case("e010", "epistemic", "superseded",
              "Which cache ttl value is current for the gateway?",
              "120 s (2.3); the 300 s value belongs to the superseded 2.2 release.",
              "superseded", ["changelog.txt"]),
        _case("e011", "epistemic", "unknown",
              "How many errors occurred in February?",
              "Indeterminate: the vendor never provided the February count and no copy "
              "exists in the available records.",
              "unknown", ["vendor-note.txt"]),
        _case("e012", "epistemic", "unknown",
              "Can you state the February error count?",
              "No. The datum is currently unknown and cannot be determined from the records.",
              "unknown", ["vendor-note.txt"]),
        _case("e013", "epistemic", "causal_caution",
              "Did update 2.3 cause the gateway restarts?",
              "Not established: the restarts followed the deployment, but no intervention "
              "or mechanism test was performed and alternatives remain open.",
              "unknown", ["incident.txt", "changelog.txt"]),
        _case("e014", "epistemic", "causal_caution",
              "Can we conclude that the 2.3 update caused the incidents?",
              "No. This is an association only; causation was not tested and is not established.",
              "unknown", ["incident.txt"]),
        _case("e015", "epistemic", "domain_scope",
              "Does the 'severe latency' threshold apply to every service in the project?",
              "No. The convention is scoped to the Nimbus gateway only.",
              "unknown", ["conventions.txt"]),
        _case("e016", "epistemic", "reported_vs_measured",
              "Which figure is the instrument of record for the cache hit rate, and why?",
              "The measured 71.4% from the metrics pipeline; the conventions say a report "
              "is not a measurement and the measurement instrument is the record.",
              "observed", ["measurements.txt", "conventions.txt"]),
    ]
    return cases


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def phase_docs(out: Path) -> None:
    docs_dir = out / "documents"
    if docs_dir.exists():
        shutil.rmtree(docs_dir)
    docs_dir.mkdir(parents=True)
    for name, text in DOCS.items():
        (docs_dir / name).write_text(text.strip() + "\n", encoding="utf-8")
    print(f"docs: {len(DOCS)} written under {docs_dir}")


def phase_cases(out: Path) -> None:
    cases = build_cases()
    blob = "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
                   for row in cases).encode("utf-8")
    (out / "cases.jsonl").write_bytes(blob)
    factual = sum(1 for row in cases if row["class"] == "factual")
    epistemic = len(cases) - factual
    print(f"cases: {len(cases)} written ({factual} factual, {epistemic} epistemic) "
          f"sha1 {hashlib.sha1(blob).hexdigest()}")


def phase_build(out: Path, *, timeout: int = 300) -> None:
    """One-time LLM extraction: document layer (graph) + trilepsia units."""
    import os

    from memory_machine.attachments import _file_hash
    from memory_machine.config import Config
    from memory_machine.coordinator import Machine
    from memory_machine.trilepsia import TrilepsiaExtractor, ingest_trilepsia

    from composition_e1 import load_dotenv_key  # reuse the key loader

    api_key = load_dotenv_key()
    if not api_key:
        raise SystemExit("set DEEPSEEK_API_KEY (env or .env)")
    os.environ.setdefault("DEEPSEEK_API_KEY", api_key)
    machine = Machine(out, config=Config())
    for name in DOCS:
        path = out / "documents" / name
        result = machine.ingest_document(path)  # tape -> registry -> graph
        print(f"graph {name}: {result.get('status', result)}", flush=True)
        text = path.read_text(encoding="utf-8").strip()
        doc_source = f"{path.name}#{_file_hash(text)}"
        tri = ingest_trilepsia(
            tape=machine.tape, root=machine.root, doc_source=doc_source,
            schema=SCHEMA, client=machine._ensure_client(),
            extractor=TrilepsiaExtractor(machine._ensure_client()),
            window_chars=WINDOW_CHARS,
            scope="gate_v1",
        )
        print(f"trilepsia {name}: {tri}", flush=True)
    print("build: extraction frozen")


def phase_manifest(out: Path) -> None:
    files = {}
    for path in sorted(out.rglob("*")):
        if path.is_file() and path.name != "manifest.json":
            files[str(path.relative_to(out))] = {
                "sha256": sha256(path), "bytes": path.stat().st_size,
            }
    blob = json.dumps(files, sort_keys=True).encode("utf-8")
    manifest = {
        "builder": "eval/gen_trilepsia_gate.py",
        "spec": "docs/TRILEPSIA_GATE_SPEC.md (538077a)",
        "schema": SCHEMA,
        "files": files,
        "sha1": hashlib.sha1(blob).hexdigest(),
    }
    (out / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"manifest: {len(files)} files | sha1 {manifest['sha1']}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", required=True,
                        choices=["docs", "build", "cases", "manifest", "all-offline"])
    parser.add_argument("--out", default="eval/fixtures/trilepsia_gate_v1")
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    if args.phase in {"docs", "all-offline"}:
        phase_docs(out)
    if args.phase in {"cases", "all-offline"}:
        phase_cases(out)
    if args.phase in {"manifest", "all-offline"}:
        phase_manifest(out)
    if args.phase == "build":
        phase_build(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
