# Memory Lifecycle v3 — pre-registration (IDF coverage + candidacy margin)

Frozen before execution, 2026-09-22, branch `memory-lifecycle-v1` (PR #1).
Baselines: v1 (A/B/D + retro) and v2 (coverage trigger), both shadow-only.

## 0. Motivation (measured)

v2 improved the trigger (0.25 → 0.75) and the combined availability reached the
recall floor (0.952 ≥ 0.93), but failed two gates at 0.75:

1. **false-confidence coverage (P20)**: the plain token fraction was covered at
   0.60 by *wrong* active records sharing generic words, so T2 stayed silent;
2. **candidate noise (P04)**: one unnecessary trigger delivered an irrelevant
   retro candidate, precision@k 0.75.

v3 changes two things **only inside the retroactive path**: the coverage signal
becomes **rarity-weighted (IDF)**, and retroactive candidates must clear a
**margin relative to the best retroactive score**. Promotion, the classifier,
the retriever, the fixture and the projection stay frozen.

## 1. Frozen definitions (all gold-free, round thresholds, no per-case fitting)

**Probe corpus** for IDF: the temporal-filtered searchable set of the probe —
active records **plus** `event_only` records with `seq < after_seq`
(`reject`/invalid/secret excluded). `N` = number of documents in that corpus,
`df(t)` = number of documents containing token `t` (product tokenizer).

```
idf(t)        = ln((N + 1) / (df(t) + 1)) + 1
Q             = content tokens of the question (len >= 4)
U             = content tokens (len >= 4) of the active top-k records
coverage_idf  = sum(idf(t) for t in Q ∩ U) / sum(idf(t) for t in Q)   (1.0 if Q empty)
```

**Trigger (primary):** `coverage_idf < 0.50` **or** zero positive overlap in
the active top-k (the v1 condition kept as the OR component).

**Candidacy margin:** retroactive candidates are the positive-score top-k
retro records with `score >= 0.50 × best_retro_score` (no candidates when the
retro list is empty).

Retriever, temporal guard, searchable-class restriction, no-promotion rule and
retrieval-then-gold order: identical to v2 (product BM25 k1=1.5/b=0.75,
top_k=5, tie-break score/seq/memory_id).

## 2. Variants (one deterministic run)

| id | trigger | margin | purpose |
|---|---|---|---|
| V3-A | IDF coverage OR zero-overlap | none | isolate the signal |
| V3-B (primary) | IDF coverage OR zero-overlap | 0.50 × best | full v3 proposal |
| V3-C | v2's plain coverage OR zero-overlap | 0.50 × best | isolate the margin effect |

## 3. Hypotheses and gates (applied to V3-B)

| # | Hypothesis | Gate |
|---|---|---|
| H3-1 | Coverage detection improves | trigger quality ≥ **0.75** (v2 was 0.75) |
| H3-2 | The architecture repairs false discards | recovery ≥ **0.80** |
| H3-3 | The repair is not noisy | precision@k ≥ **0.80** |
| H3-4 | Combined availability reaches the floor | combined recall ≥ **0.93** |
| H3-5 | The trigger stays selective | fallback rate ≤ **0.50** |
| H3-6 | No regression vs v2 | trigger quality and combined recall ≥ v2's values; active-set reduction ≥ 0.40; promotion precision > arm A |
| H3-7 | Nothing else moved | projection rebuild byte-identical; classifier and fixture unchanged |

## 4. Protocol and stop rules

1. Verify fixture hash (`e1021c20…`) and v1 projection rebuild.
2. Run V3-A/B/C once, deterministic, no LLM.
3. Apply §3 gates to V3-B; report every counter, per-probe tables and full
   rankings; commit results and the decision together.
4. **Stop rules:** any failed gate keeps the line shadow-only. If H3-1/H3-4
   hold but H3-2/H3-3 fail, the remaining problem is candidate selection and is
   recorded for v4; if coverage still fails, the IDF signal is insufficient.
5. Promotion to the main path remains out of scope; a full pass only justifies
   a v4 (shadow instrumentation in the real recall path) under a new
   pre-registration.

## 5. Expected readings (pre-declared, not gates)

- IDF should stop P20-type false confidence if the wrongly-covered tokens are
  generic in the probe corpus.
- The margin should remove single-irrelevant deliveries when a clearly better
  candidate exists; it cannot help when the irrelevant record *is* the best
  retro candidate (that requires a candidacy floor, a v4 hypothesis).

## Execution record (2026-09-22)

Run `eval/results/lifecycle_v1_retroactive_v3/report_v3.json` (fixture
`e1021c20…`, v1 projection, one deterministic run).

| variant | trigger quality | fallback rate | recovery | precision@k | combined recall |
|---|---:|---:|---:|---:|---:|
| V3-A (IDF, no margin) | 0.750 | 0.210 | 0.750 | 1.000 | 0.952 |
| V3-B (primary) | 0.750 | 0.210 | 0.750 | 1.000 | 0.952 |
| V3-C (v2 signal + margin) | 0.750 | 0.263 | 0.750 | 0.750 | 0.952 |
| v2 T3 (reference) | 0.750 | 0.263 | 0.750 | 0.750 | 0.952 |

**Gates (V3-B):** H3-1 PASS · H3-2 **FAIL** (recovery 0.75 < 0.80) · H3-3
**PASS** (precision@k 1.000) · H3-4 PASS (0.952 ≥ 0.93) · H3-5 PASS (0.210) ·
H3-6 PASS (no regression) ⇒ `all_pass = false`.

**What the change did, measured:**

1. **Noise eliminated.** The IDF signal removed the unnecessary P04 trigger
   (fallback 0.263 → 0.210) and, with the margin, every delivered candidate was
   relevant: precision@k 0.750 → **1.000**, `irrelevant_retroactive_hits` 1 → 0.
2. **Recovery unchanged.** The single remaining miss is P20 (needed M0029):
   `coverage_idf = 0.562` — IDF only reduced it from 0.600 to 0.562, because in
   this small probe corpus even generic words ("combinado", "sexta") carry high
   IDF when they appear in few documents. The wrong active records still cover
   a majority of the weighted question.

**Verdict.** Shadow-only per the stop rules (one gate fails). The architecture
now passes **5 of 6** gates; the only open failure is coverage false-confidence
on a generic-word question. Recorded v4 hypothesis space (new pre-registration
required): a comparative coverage signal (event-log best score vs active best
score, which requires maintaining a cheap lexical index over the event log) or
a mandatory-coverage rule over the question's highest-IDF tokens.
