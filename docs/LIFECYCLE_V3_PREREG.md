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
