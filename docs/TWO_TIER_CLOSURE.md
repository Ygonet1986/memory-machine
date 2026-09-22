# Two-tier retrieval (v1-v2) - closure record

Closed 2026-09-22 by owner decision after the v2 execution record measured a
structural frontier. Everything below was measured on the frozen fixture
`e1021c20...` with the v1 projection, product BM25/tokenizer, `top_k=5`, and
zero LLM calls. Nothing was promoted; the tape, classifier, retrieval path and
defaults were never touched.

## What was tested

Hypothesis (v1): search the promoted set **and** a cheap lexical index of the
full non-rejected record log on every recall, combined in one ranking scale
with one evidence budget - no trigger, no cross-corpus score comparison.
Hypothesis (v2): bound candidacy/delivery with a high-confidence score margin
to recover precision without losing availability.

| stage | rule | availability | precision@k | deliveries |
|---|---|---:|---:|---:|
| T2-B v4-B trigger (reference) | active + fallback on trigger | 0.952 | 0.476 | 42 |
| **T2-C v1 primary** | union index, top-5 + margin 0.50 | **1.000** | 0.512 | 41 |
| T2-U v1 unfiltered | all 32 records, same rule | 1.000 | 0.525 | 40 |
| **T2v2-P v2 primary** | union index, rank-1 + margin 0.90 | 0.905 | **0.826** | 23 |
| T2v2-B2 v2 variant | union index, exact top-2 | 0.952 | 0.556 | 36 |

## The measured frontier (combined index, descriptive)

| margin | availability | precision@k | | budget | availability | precision@k |
|---|---:|---:|---|---:|---:|---:|
| 0.50 | 1.000 | 0.512 | | top-1 | 0.857 | 0.947 |
| 0.70 | 0.905 | 0.679 | | top-2 | 0.952 | 0.556 |
| 0.90 | 0.905 | 0.826 | | top-3 | 1.000 | 0.420 |
| 1.00 | 0.857 | 0.947 | | | | |

**No point of the declared family meets both gates** (availability >= 0.952
and precision >= 0.80). The causes are mechanical: P15/M0006 sits at rank 2
with a score ratio in (0.50, 0.70) - any margin >= 0.90 drops it; P09/M0017
sits at rank 3, unreachable by any margin; and the noise shares the same
mid-range score band as the required second occurrences.

## What the two rounds settle

1. **The trigger was the availability bottleneck.** Unconditional search
   reaches 1.000 with all four former false discards (P05/M0012, P07/M0014,
   P13/M0026, P20/M0029) delivered at rank 1.
2. **Precision is the price, and it is structural.** Full delivery carries the
   tail (0.512); high-confidence margins recover precision (0.826) only by
   giving back exactly the rare second occurrences that made 1.000 valuable.
3. **Rank-1 is strong; the cost lives after it.** Descriptive precision@1 is
   18/19 = 0.947 in v1; every family member loses availability or precision in
   the second and third slots.
4. **The classification layer contributes noise removal only.** Filtering the
   three rejects (T2v2-U90 vs T2v2-P) changes precision by 0.066 and nothing
   else - consistent with the lifecycle finding that its value is precision of
   the promoted set, not availability.

## What is preserved

- Shadow-only code and artifacts: `eval/two_tier_retrieval_v1.py`,
  `eval/two_tier_retrieval_v2.py`, `eval/results/two_tier_v1`,
  `eval/results/two_tier_v2`, both pre-registrations with execution records.
- No product imports, no `lifecycle_mode`, no default changes; the `0.2.0`
  release tag is untouched.

## Registered follow-ups (each needs a new pre-registration)

1. **Orthogonal candidacy signal** - coverage-IDF per candidate, entity or
   qualifier overlap - explicitly outside the score-margin family that the
   frontier ruled out.
2. **Product-side shadow instrumentation** - cheap index over real session
   tapes: growth, latency, candidate quality at real scale; the only path
   toward any promotion decision.
3. **Cost framing for the write-up** - the frontier is an evidence-budget
   result: top-1 buys 0.947 precision at 0.857 availability; the second slot
   is where both metrics are decided.
