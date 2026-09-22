# Admission shadow instrumentation v1

Status: implemented, off by default. Date: 2026-09-22.

## Why

The two-tier line closed with a clear division of labour:

1. **Preservation** is solved by the tape.
2. **Candidate discovery** is strong: the four lifecycle false discards were
   recovered at rank 1 by a cheap lexical index, with zero LLM calls.
3. **Admission to context** is the open problem: unconditional top-5 delivery
   carried almost half inadequate evidence (precision 0.512), and bounding by
   score margin traded availability for precision with no point meeting both
   gates.

So the next component is not another retriever. It is an **evidence admission
controller**: a multissignal, budgeted decision about which found candidates
deserve the payload's characters. Before freezing any policy, this
instrumentation collects the missing distribution on **real tapes**.

## What it records

One JSON line per recall, in `admission_shadow.jsonl` inside the session root
(or `MEMORY_MACHINE_ADMISSION_SHADOW_PATH`). Enable with
`MEMORY_MACHINE_ADMISSION_SHADOW=1`; disabled by default.

Envelope: schema version, timestamp, session id, `cached` flag (cache hits are
logged too), the counterfactual policy label, question **hash**/length/token
count, corpus size, payload item count and characters.

Per candidate (`active` = annotated memories offered to the payload;
`event_log` = BM25 hits from other sessions' tapes):

| field | meaning |
|---|---|
| `origin` | `active` or `event_log` |
| `memory_id` / `source_session` | internal IDs |
| `rank`, `score` | order and annotation relevance (active) or BM25 score (event log) |
| `type` | memory type (decision, lesson, …) |
| `lexical_overlap` | fraction of question tokens present in the candidate |
| `rare_term_coverage` | IDF-weighted fraction (smoothed IDF over the session tape corpus) |
| `entity_matches` | identifier/version/file tokens present in both (regex-derived) |
| `date_matches` | date tokens present in both |
| `chars_if_admitted` | exact `used_chars` when in the payload, else length proxy |
| `in_payload` | whether the current build actually admitted it |
| `counterfactual_admitted` | documented baseline: active = in-payload; event log = rank-1 with score >= 0.90 x best (the v2 primary rule, **recorded, never applied**) |

## Privacy and neutrality

- **No content leaves as text**: question text, summaries, `why` text, notes
  and payload evidence are never written - only IDs, hashes and derived
  metrics. This is asserted by tests.
- **No answer changes**: no LLM calls, no tape writes, no defaults touched.
  The recalled result is identical with the flag on and off (integration test
  compares counts and payload fields against a control machine).
- **Never breaks recall**: any instrumentation error is swallowed (one stderr
  warning per process).

## How to collect real data

Run any real consumer (e.g. the opencode integration) with:

```bash
export MEMORY_MACHINE_ADMISSION_SHADOW=1
# optional: export MEMORY_MACHINE_ADMISSION_SHADOW_PATH=/path/to/log.jsonl
```

Each session writes its own log next to its tape. Nothing needs to be shared
to be useful locally: the analysis runs on derived metrics, not content.

## Planned use (owner's order)

1. collect on real tapes;
2. measure which signals separate useful evidence from noise;
3. freeze a multissignal admission policy (rare-term coverage, exact
   entity/ID matches, temporal compatibility, type compatibility, retriever
   consensus, redundancy, character cost, negation/correction/supersedence,
   provenance - as *priority for context*, never as factual certainty);
4. compare against top-1 / top-5 / margin baselines;
5. integrate selection into the payload budget as `max coverage` subject to
   `chars <= 4000`;
6. promote only if it beats availability and precision **simultaneously**.

## Privacy model (threat model, retention, permissions)

- **What the log reveals.** Only derived signals, but they are not nothing:
  the deterministic, unsalted question hash is dictionary-attackable in
  low-entropy scenarios; matched entity/date tokens can expose identifiers
  (file names, versions, ids); memory ids link to tape records that stay
  local. Treat a log as personal data.
- **Retention.** Append-only, one file per session, no rotation in v1. The
  owner deletes the file (or the session) to delete the data; nothing is
  uploaded anywhere by this module.
- **Permissions.** The file is created with mode `0600`; a directory-level
  override via `MEMORY_MACHINE_ADMISSION_SHADOW_PATH` inherits the ambient
  umask.
- **Sharing.** Aggregate metrics (counts, coverage distributions) are safe to
  share; `entity_matches`, `date_matches` and the question hash should be
  treated as potentially identifying and redacted when sharing raw lines.
- **Planned hardening (v2).** Keyed HMAC for the question hash with a local
  key, plus optional exclusion of entity/date token lists. Not implemented in
  v1; no network or key management exists today.

## Phase status: admission-shadow-v1 — sampling freeze (2026-09-22)

Publication is closed (public repo, tag `v0.2.2`, branch protection on `main`).
This phase is exclusively shadow data collection. Rules for the duration:

- Collect on real sessions with `MEMORY_MACHINE_ADMISSION_SHADOW=1`; **do not
  change any policy, default, threshold, prompt or retrieval behavior while
  sampling** - the analysis requires uncontaminated data.
- No new experimental lines are opened during sampling.
- Logs stay local (`0600`), treated as personal data; aggregate before sharing.
- The pre-rewrite backup mirror is retained at least until the first sampling
  round is analyzed and the next release is published.
- The collection stop point is frozen in
  `docs/ADMISSION_SHADOW_STOPPING_RULE.md` (independent of results; checked
  by `scripts/shadow_stop_check.py`, which reports coverage criteria only).
  Until it is met, no admission-outcome aggregate may be computed; only then
  does the analysis get its own pre-registration (signals, metrics, gates),
  and promotion requires availability **and** precision passing together
  under the 4000-char budget.

## Non-goals

No admission policy is applied by this module; no thresholds are frozen; no
promotion; no product default changes. Any policy change will require its own
pre-registration and must run first in shadow mode on real tapes.
