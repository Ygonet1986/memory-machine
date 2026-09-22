# Memory Lifecycle v4 — pre-registration (comparative coverage signal)

Frozen before execution, 2026-09-22, branch `memory-lifecycle-v1` (PR #1).
Baselines: v3 (5/6 gates, shadow-only) and its execution record.

## 0. Motivation (measured)

v3 eliminated noise (precision@k 1.000) but left one failure: **P20 coverage
false-confidence**. `coverage_idf = 0.562` — in the small probe corpus the
wrong active records still cover a majority of the weighted question, because
even generic words carry high IDF when they appear in few documents. The IDF
weighting of *question coverage* is therefore not the right discriminator.

v4 adds a **comparative** signal that does not depend on token rarity: if the
event log contains a materially better lexical match than the active set, the
active coverage is likely insufficient. This is gold-free, deterministic, and
uses only the frozen product BM25 (no LLM). It requires ranking the event log
for every probe in shadow mode; productization would need a cheap lexical
index over the event log (out of scope here, noted for v5).

## 1. Frozen definitions

- Active best score `A*` = top positive active score for the probe (0 if none).
- Event best score `E*` = top positive event-log score for the probe (0 if none).
- **Comparative trigger**: `E* >= 1.25 × A*` (when `A* = 0`, any `E* > 0`
  qualifies; when `E* = 0` it never fires). The 1.25 factor is a round,
  pre-declared relative margin, not fitted.
- IDF coverage, zero-overlap OR, event-only searchable set, temporal guard,
  top_k=5 product BM25, candidacy margin 0.50 × best retro score,
  retrieval-then-gold order: **identical to v3** (all frozen).

## 2. Variants (one deterministic run)

| id | trigger | candidates |
|---|---|---|
| V4-A | v3 trigger (IDF OR zero-overlap) — reference | v3 margin |
| V4-B (primary) | v3 trigger **OR** comparative | v3 margin |
| V4-C | comparative only | v3 margin |

## 3. Hypotheses and gates (applied to V4-B)

| # | Hypothesis | Gate |
|---|---|---|
| H4-1 | Coverage detection reaches the target | trigger quality ≥ **0.75** (v3: 0.75) |
| H4-2 | The architecture repairs all false discards | recovery ≥ **0.80** (v3: 0.75; target: 1.00) |
| H4-3 | The comparative signal does not break noise control | precision@k ≥ **0.80** |
| H4-4 | Combined availability holds the floor | combined recall ≥ **0.93** |
| H4-5 | The trigger stays selective | fallback rate ≤ **0.50** |
| H4-6 | No regression vs v3 | trigger quality, precision@k and combined recall ≥ v3 values |
| H4-7 | Nothing else moved | projection rebuild byte-identical; classifier, fixture and retriever unchanged |

New comparative diagnostics (not gates): times the comparative rule fires,
extra triggers vs v3, extra recoveries, extra irrelevant deliveries.

## 4. Protocol and stop rules

1. Verify fixture hash (`e1021c20…`) and v1 projection rebuild.
2. Run V4-A/B/C once, deterministic, no LLM; report every counter, per-probe
   rankings and the comparative diagnostics.
3. Apply §3 gates to V4-B; commit results and decision together.
4. **Stop rules:** any failed gate keeps the line shadow-only. If recovery
   reaches 1.00 but precision falls below 0.80, candidacy bounding is the v5
   problem; if the comparative rule still misses a false discard, the trigger
   approach itself is exhausted for v1-style signals and the line closes.
5. Promotion to the main path stays out of scope; a full pass only justifies a
   v5 (shadow instrumentation in the real recall path, including the lexical
   index cost) under a new pre-registration.

## 5. Pre-declared expected readings

- P20 should fire via the comparative rule if `E*(M0029) ≥ 1.25 × A*` for that
  probe; this is the designed test of the signal.
- Extra triggers are expected on probes whose event log holds a strong
  non-promoted match that is **not** required; each such trigger can add an
  irrelevant candidate (precision cost) — the gates bound the acceptable noise.

## Execution record (2026-09-22) — stop rule applied: trigger approach closed

Run `eval/results/lifecycle_v1_retroactive_v4/report_v4.json` (fixture
`e1021c20…`, v1 projection, one deterministic run).

| variant | trigger quality | fallback rate | recovery | precision@k | combined recall |
|---|---:|---:|---:|---:|---:|
| V4-A (v3 reference) | 0.750 | 0.210 | 0.750 | 1.000 | 0.952 |
| V4-B (primary) | 0.750 | 0.210 | 0.750 | 1.000 | 0.952 |
| V4-C (comparative only) | 0.750 | 0.158 | 0.750 | 1.000 | 0.952 |
| v3 B (reference) | 0.750 | 0.210 | 0.750 | 1.000 | 0.952 |

Comparative diagnostics: fired 3 times, **0 extra triggers** vs v3, 0 extra
recoveries, 0 extra irrelevant deliveries.

**The knife edge.** P20 is still missed: `A* = 2.734`, `E* = 3.395`, ratio
**1.242 < 1.25** — the frozen comparative factor misses the case by 0.8%. The
active best belonged to a *wrong* active record that nearly matches the event
log's required record. Lowering the factor to ≤ 1.24 would fire it, but
changing a pre-declared threshold after seeing the result is forbidden.

**Stop rule (pre-registered §4.4) applies:** the comparative rule still misses
a false discard ⇒ **the trigger approach is exhausted** for v1-style signals
(four designs: zero-overlap, plain coverage, IDF coverage, comparative ratio —
each failing to catch P20 while holding the other gates). The line closes at
the trigger approach; `all_pass` is false and lifecycle-v1-v4 remains
**shadow-only**, with the tape, defaults, classifier and retriever untouched.

**What is settled by the sequence.** Trigger quality 0.25 → 0.75, precision
0.75 → 1.000, fallback 0.263 → 0.210/0.158, combined availability 0.857 →
0.952 (above the 0.93 floor) — but the residual case is a genuine
near-tie between a wrong active match and the event-log match, not a rarity,
coverage or score-dominance problem. Any further progress requires a different
mechanism class (e.g., retrieving from the event log unconditionally with a
bounded candidacy rule — a cost problem, not a coverage problem), which needs
its own pre-registration and cost instrumentation.
