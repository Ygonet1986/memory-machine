# Memory Lifecycle v2 — pre-registration (coverage trigger)

Frozen before execution, 2026-09-22, on branch `memory-lifecycle-v1` (PR #1).
Baseline: Lifecycle v1 final placard (`docs/LIFECYCLE_V1_PREREG.md` addenda 1–2).

## 0. Motivation (measured, not assumed)

v1 official results: H-L1 PASS (active-set reduction 0.469), **H-L2 FAIL**
(promotion recall 0.765), H-L3 PASS (precision 0.765 > 0.531), **H-L5 FAIL**
(retroactive recovery 0.250). The decomposition is decisive:

```
trigger quality       1/4 = 0.25   (fired when needed once)
retriever capability  4/4 = 1.000  (BM25 ranked the needed memory #1 every time)
```

The bottleneck is **coverage detection**, not retrieval and not classification:
the four false discards (M0012, M0014, M0026, M0029) are correctly classified
`event_only` (they are not durable facts) and are fully recoverable from the
event log — but the v1 trigger ("no positive lexical score in the active
top-k") stays silent whenever the question overlaps some **wrong** active
record. v2 changes **only the trigger**; the promoted set, the classifier and
the retriever stay frozen.

## 1. Scope and non-goals

- Shadow only; no promotion to the main path; tape and defaults untouched.
- **No classifier change**: the rules arm B stays exactly as measured in v1
  (same fixture, same rebuild, byte-identical decisions required).
- **No arm C**: routing `no_durable_signal` to the LLM remains a v3+ hypothesis
  (v1 recorded C as not executed due to causal inapplicability).
- No new fixture: the frozen fixture `e1021c20…` is reused unchanged.
- No threshold tuned against the four misses: thresholds below are round,
  principled values frozen now.

## 2. Trigger variants (all gold-free)

Question content tokens: `retrieval.tokenize(question)` filtered to length ≥ 4;
let `Q` be that set, `U` the union of tokens of the **active top-k** records'
texts (temporal filter `seq < after_seq` applied first).

| id | rule | rationale |
|---|---|---|
| T1 | active top-k has no positive BM25 score (v1's trigger) | zero lexical overlap |
| T2 | coverage `|Q ∩ U| / |Q| < 0.50` (when `Q` is empty, coverage = 1.0) | a majority of the question's content words must appear in the active candidates |
| T3 (primary) | T1 **or** T2 | conservative OR; the two components are also reported separately |

Retriever unchanged: product BM25 (k1=1.5, b=0.75), product tokenizer, `top_k=5`
= `view_top_k` default, positive scores only, tie-break score desc → seq asc →
memory_id asc; event-log search restricted to `event_only` records; no
promotion applied; a retroactive hit never alters later probes; gold is read
only after retrieval.

## 3. Hypotheses and frozen gates (v2)

| # | Hypothesis | Gate |
|---|---|---|
| H2-1 | Coverage detection improves | T3 trigger quality (fired when needed) ≥ **0.75** |
| H2-2 | The architecture repairs false discards | T3 `retroactive_recovery_rate` ≥ **0.80** |
| H2-3 | The repair does not add noise | T3 `retroactive_precision@k` ≥ **0.80** |
| H2-4 | Combined availability reaches the recall floor | per-probe occurrence recall **after fallback** (active OR retro-found) ≥ **0.93** (= 1 − 7% floor) |
| H2-5 | The trigger stays selective | T3 fallback rate over probes ≤ **0.50** |
| H2-6 | No regression vs v1 | active-set reduction ≥ 0.40, promotion precision > arm A, decisions rebuild-identical (byte-identical projection) |

H2-2/H2-4 are complementary readings of the same repair path (found count and
end-to-end availability); both are required.

## 4. Metrics and counters

Same counters as v1 (`recoverable_false_negative`, `retroactively_found`,
`retroactively_missed`, `unrecoverable_due_to_ingestion`, `fallback_triggered`,
`fallback_not_triggered`, `irrelevant_retroactive_hits`), computed **per
trigger variant**, plus:

- `trigger_quality` = fired-when-needed / probes-needing-fallback;
- `fallback_rate` = fired / probes;
- `retroactive_precision@k`;
- `combined_recall_occurrences` = occurrences available via active ∪ retro;
- per-probe tables per variant with the full rankings preserved.

## 5. Protocol and stop rules

1. Verify the fixture hash (`e1021c20…`) and the projection rebuild is
   byte-identical (v1 decisions unchanged).
2. Evaluate T1, T2 and T3 in one deterministic run (no LLM, no provider).
3. Apply the gates of §3; commit results and the decision together.
4. **Stop rules**: if T3 trigger quality < 0.75 → coverage detection remains
   open and the line stays shadow-only; if recovery ≥ 0.80 but precision@k <
   0.80 → the repair is noisy and is rejected; if recall after fallback < 0.93
   → the architecture does not reach the floor; in every outcome the tape,
   defaults and classification stay unchanged.
5. Promotion to the main path is explicitly **out of scope** for v2; even a
   full pass only justifies v3 (shadow instrumentation of the real recall
   path) under a new pre-registration.

## 6. What a pass/fail would mean

- **Pass (all gates)**: the architecture "promoted set + retroactive fallback"
  is viable at fixture scale; next step is v3 instrumentation in the product's
  recall path, still opt-in and shadow-first.
- **Fail on coverage only**: the trigger needs a stronger gold-free signal
  (e.g., candidate-view coverage à la M3b, or a query-decomposition signal);
  the retriever and classifier are exonerated by the decomposition.
- **Fail on noise**: the event log needs candidacy limits (score floor,
  per-session caps) before the repair is usable.

## Execution record (2026-09-22)

Run `eval/results/lifecycle_v1_retroactive_v2/report_v2.json` (fixture
`e1021c20…`, v1 projection, three variants in one deterministic run).

| variant | trigger quality | fallback rate | recovery | precision@k | combined recall |
|---|---:|---:|---:|---:|---:|
| T1 (v1 trigger) | 0.250 | 0.053 | 0.250 | 1.000 | 0.857 |
| T2 (coverage < 0.50) | 0.750 | 0.263 | 0.750 | 0.750 | 0.952 |
| T3 (OR, primary) | 0.750 | 0.263 | 0.750 | 0.750 | 0.952 |

**Gates:** H2-1 trigger quality PASS (0.75) · H2-2 recovery **FAIL** (0.75 <
0.80) · H2-3 precision **FAIL** (0.75 < 0.80) · H2-4 combined recall **PASS**
(0.952 ≥ 0.93) · H2-5 selective PASS (0.263 ≤ 0.50) ⇒ `all_pass = false`.

**Two remaining failure modes, precisely characterized:**

1. **False-confidence coverage (P20).** The needed record is M0029; the
   question's content tokens are covered at 0.60 by *wrong* active records that
   share generic words ("combinado", "sexta", "para"), so T2 stays silent. The
   plain token-fraction signal cannot separate this case.
2. **Candidate noise (P04).** An unnecessary trigger delivered one irrelevant
   retro candidate (M0002), dropping precision@k to 0.75 — with only four
   delivered candidates, one irrelevant hit is expensive.

**Verdict.** Lifecycle v2 stays **shadow-only** per the stop rules. The
architecture moved substantially closer: trigger quality 0.25 → 0.75, recovery
0.25 → 0.75, and the combined availability (active ∪ retroactive) reaches the
recall floor (0.952 ≥ 0.93) — the "promoted set + retroactive fallback" path is
now within one signal of the target, but does not pass. The tape, defaults,
classifier and retriever remain unchanged; no promotion is applied.

**Hypotheses for v3 (require a new pre-registration):** rare-token (IDF)
weighting for the coverage signal so generic words do not create false
confidence; a candidacy margin/floor for retroactive candidates (accept only
candidates scoring ≥ α × best retro score) to bound noise; optionally a
single-record confidence component.
