# Benchmark archive (v1.0)

Frozen raw artifacts behind the v1.0 results. Do not re-run these experiments
for the paper: the numbers below are the ones reported, and re-running would
inject LLM sampling variance.

- `routing/*.json` — view-router / dimension / attention benchmark results
  (`eval/view_router_bench.py`); each file holds one arm on the frozen fixture.
- `logs/*.log` — stability, conversation, ingestion ablation, e2e and tagging
  runs (stdout tables).
- `scripts/*.py` — the ad-hoc analysis scripts used during the experiments
  (superseded by `eval/report.py`).
- `CHECKSUMS.txt` — sha256 of every archived file plus the `eval/out` snapshots.

Regenerable from the harnesses: `routing/` (deterministic lexical arms;
LLM-plan arms vary), `logs/` tables, and `eval/out/*.jsonl` (LLM-dependent).
Not archived: the continuity benchmark output (single 18-recall run); its
numbers are recorded in the manual, section 40.8.
