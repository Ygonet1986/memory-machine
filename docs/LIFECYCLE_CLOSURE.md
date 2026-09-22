# Memory Lifecycle (v1–v4) — closure record

Closed 2026-09-22 by the pre-declared stop rule of
`docs/LIFECYCLE_V4_PREREG.md` §4.4 (a comparative miss exhausts the trigger
approach). The user accepted the closure. Everything below is measured on the
frozen fixture `e1021c20…` with the v1 projection; the tape, defaults,
classifier and retriever were never changed, and no promotion was applied at
any point.

## What was tested

| stage | mechanism added | gate result |
|---|---|---|
| v1 | admissions (4 classes) + promoted set + retroactive fallback with a zero-overlap trigger | H-L1 PASS (reduction 0.469), H-L3 PASS (precision 0.765 > 0.531), **H-L2 FAIL** (recall 0.765), **H-L5 FAIL** (recovery 0.250); arm C not executed (causal inapplicability) |
| v2 | coverage trigger: question-token fraction covered by the active top-k < 0.50, ORed with zero-overlap | 3/5 gates; trigger 0.75, recovery 0.75, precision 0.750, combined recall 0.952 |
| v3 | IDF-weighted coverage + candidacy margin (≥0.50 × best retro score) | **5/6 gates**; precision 1.000, fallback 0.210, recovery 0.75, combined 0.952 |
| v4 | comparative signal: event best ≥ 1.25 × active best, ORed with v3 | 5/6 gates; identical outcome (0 extra triggers); comparative-only (V4-C) fallback 0.158 |

## The residual failure, precisely

Four false discards are recoverable from the event log (the retriever ranks the
needed memory **first** in every one). Three were recovered by v2–v4. The
fourth (P20, needed M0029) survived four trigger designs because the wrong
active record forms a genuine **near-tie** with the required event-log record:
`A* = 2.734` vs `E* = 3.395` — ratio 1.242 against the frozen 1.25 factor. The
case is not a rarity problem (v3), not a plain-coverage problem (v2) and not a
score-dominance problem (v4); the thresholds were pre-declared and were not
re-fit after seeing this.

## What the line settles

1. **The classification layer is sound.** Reducing the consultable set by
   46.9% with precision rising from 0.531 to 0.765, `false_semantic` bounded
   (14 predicted / 3 wrong), and no regression on any guard.
2. **The retriever is not the bottleneck.** Product BM25 over the event log
   finds every recoverable false discard at rank 1 (capability 4/4 = 1.000).
3. **Coverage detection is the bottleneck — and trigger heuristics have a
   measured ceiling** on this substrate: 0.25 → 0.75 trigger quality, with the
   last case a near-tie that no pre-declared round threshold catches.
4. **The architecture reaches availability but not the recovery gate.**
   Combined availability (active ∪ retroactive) stands at **0.952 ≥ 0.93
   floor** with precision@k 1.000, but recovery is 0.75 < 0.80 because P20 is
   never searched.

## What is preserved

- Shadow-only code and artifacts: `src/memory_machine/lifecycle.py`,
  `eval/lifecycle_shadow.py`, `eval/lifecycle_retroactive*.py`, fixtures,
  reports and all pre-registrations (v1–v4 with execution records).
- `lifecycle_mode` does **not exist** in the product's configuration; nothing
  in the recall path imports the lifecycle projection.
- The `0.2.0` release (tag on `26f273f`) is untouched; `main` receives this
  record plus the shadow instrumentation only.

## Registered follow-ups (not executed; each needs a new pre-registration)

1. **Unconditional event-log retrieval with a bounded candidacy rule** —
   removes the trigger entirely; the open problem becomes cost (lexical index
   maintenance, latency) and candidacy noise, not coverage.
2. **Stronger near-tie discriminator** — e.g., entity/qualifier overlap rather
   than token scores, or a two-stage leave-one-out coverage test.
3. **Product-side shadow instrumentation** — measure the event-log retrieval
   cost (index size, latency, per-recall overhead) on real session tapes
   before any recall-path change.
