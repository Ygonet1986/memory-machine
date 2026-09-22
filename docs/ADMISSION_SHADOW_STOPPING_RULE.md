# Admission-shadow-v1 — frozen collection stopping rule (2026-09-22)

Frozen **before any aggregate is examined**. Until every criterion below is
met, no admission-outcome metric (precision, availability, score
distributions, signal separation) may be computed or inspected; only the
criteria checker may run. This prevents optional stopping and protects the
analysis from being tuned by preliminary trends.

## Criteria (all required; round, pre-declared, result-independent)

| # | Criterion | Threshold | Why this number |
|---|---|---|---|
| 1 | Unique scored recalls | `>= 300` | Worst-case 95% CI on a proportion is ~+/-5.7% at n=300 — enough for the planned per-signal comparisons without pretending to precision the sample cannot support. |
| 2 | Sessions with at least one valid record | `>= 20` | Spread across tasks/contexts, not one long session. |
| 3 | Collection window (first to last record) | `>= 21 days` | Three calendar weeks so query/topic drift is represented. |
| 4 | Scored recalls with at least one event-log candidate | `>= 50` | The two-tier surface must be present, not incidental. |
| 5 | Scored recalls with both active and event-log candidates | `>= 30` | The core comparison cell for any admission policy. |
| 6 | Scored recalls with no candidates at all | `>= 10` | Cold-query stratum, so "abstain" behavior is measured too. |
| 7 | Short queries (question >= 1 and <= 5 tokens) | `>= 50` | Guards against a sample of only long, keyword-rich questions. |
| 8 | Long queries (question >= 12 tokens) | `>= 50` | Same, from the other side. |
| 9 | Malformed-line ratio | `<= 1%` | Data-integrity gate; above it, stop and investigate before using the sample. |

`scored` means `cached == false`. Cache hits are logged but reported
separately and excluded from the primary sample.

## Record treatment (frozen)

- **Valid record**: parses as JSON, `v == 1`, non-empty `session_id`,
  non-empty `question.sha256`, boolean `cached`, both candidate lists present,
  parseable `ts`.
- **Malformed**: anything else. Counted; never silently dropped.
- **Duplicates**: same `session_id` + same `question.sha256` in the scored
  set — the first by `ts` is kept, the rest counted as duplicates (the recall
  cache makes these rare; they indicate a cache miss, not new information).
  The same question hash in *different* sessions is kept — different context
  is a different observation.
- **Incomplete sessions**: a session counts toward criterion 2 if it has at
  least one valid record; it is not otherwise weighted. There is no minimum
  per-session size.
- **Instrumentation errors**: the module swallows write failures (one stderr
  warning per process), so invisible losses are possible; the checker can
  only report malformed lines it can see. This limitation is accepted and
  must be disclosed in the analysis.

## Stop, snapshot, then analyze

1. Run `scripts/shadow_stop_check.py` over every log path. It reports only
   the criteria above — deliberately no outcome metrics.
2. The first check where **all** criteria are met is the stop point. There is
   no earlier stopping for convenience and no stopping later to add data.
3. At the stop point, freeze the snapshot: copy the logs, record the checker
   output plus the sha256 of every file; logs are never edited afterwards.
4. Only then write the analysis pre-registration (signals, metrics, gates)
   and aggregate the frozen snapshot.

## Amendments

Typo/format corrections to this document are allowed as dated addenda without
consequence. **Any change to a threshold value restarts the collection
window** (criterion 3 is measured from the first record after the change).
Amendments may never be informed by outcome data, because none may be
inspected before the stop point.
