# Admission-synthetic-v1..v4 — closure record

Closed 2026-09-22 by owner decision after the v4 execution record; four
rounds on one frozen synthetic sample (`admission_synthetic_v1`, hash
`f61262d3...`). The line closes with a **pass**, and this record states what
that does and does not mean.

## The measured curve (same 100 cases, 100 gold occurrences)

| policy | availability | precision | delivered | abstention |
|---|---:|---:|---:|---:|
| P0 top-1 | 0.500 | 0.500 | 100 | 0.000 |
| P1 margin 0.50 | 0.900 | 0.310 | 290 | 0.000 |
| P2 margin 0.90 | 0.600 | 0.429 | 140 | 0.000 |
| P3v1 multisignal | 0.700 | 0.500 | 140 | 1.000 |
| P3v2 + supersession/entities/relative floor | 1.000 | 0.455 | 220 | 1.000 |
| P3v3 + removal/cap | 0.900 | 0.643 | 140 | 1.000 |
| **P3v4 + correction slot** | **1.000** | **0.714** | 140 | **1.000** |

## What was established (controlled settings only)

1. **The multisignal direction dominates the score-margin family**: v4 beats
   P2 on availability and P1 on precision simultaneously - the dual frontier
   that the real-tape two-tier line could not reach.
2. **The trilemma was real**: availability, precision and ordering traded
   across v1-v3; constants moved points along the frontier, never past it.
   The crossing came from a **structural priority rule** (a correction
   supersedes relevance and takes slot 1), not from another threshold.
3. **Mechanisms that carried their weight**: correction detection + full
   removal of superseded records; path/key entity coverage; a relative gain
   floor for availability with an IDF floor for abstention; a 2-candidate cap
   for the tail.
4. **Admission cannot compensate for ranking**: the corrected scenario was
   0.00 in v1/v3 because ranking or ordering put the superseded record
   first; no admission score fixed it until the correction was given a slot.
   Ranking quality remains a separate boundary.

## What this does NOT mean

- **Synthetic success is not real-world performance.** The fixture is
  templated; the results measure mechanism behavior under controlled
  distributions. They must never be cited as product accuracy.
- **Four rounds on one sample carry overfitting risk.** The v2-v4 constants
  and rules were chosen after prior aggregates; the closure accepts that risk
  explicitly and stops iterating on this fixture.
- **Nothing is promoted.** No product default changed; the admission policy
  remains research code under `eval/`.

## Authorized next step

A **product-side shadow pre-registration** (real tapes: cost, latency,
candidate quality) is the only path toward any promotion, and promotion still
requires availability **and** precision together under the 4000-character
budget on real data. The paused `admission-shadow-v1` phase stays paused;
resuming it (or opening a new shadow phase) restarts the collection window
from zero under its own pre-registration.
