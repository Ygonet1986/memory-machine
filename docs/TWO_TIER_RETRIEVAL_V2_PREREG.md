# Two-tier retrieval v2 - pre-registration (bounded candidacy)

Status: **frozen before execution**. Date: 2026-09-22.

v1 closed with availability 1.000 and precision@k 0.512 (floor 0.80 failed).
Its own stop rule applies: the next hypothesis bounds **candidacy/delivery**,
without reintroducing a trigger. v1's descriptive precision@1 was 0.947 and
precision@2 0.200 - the evidence is strong at rank 1 and the tail is the cost.

## 1. Hypothesis

A high-confidence candidacy rule over the same unconditional combined index
keeps availability at or above the 0.952 trigger reference while lifting
precision@k to at least 0.80: deliver rank 1 always, then only candidates
whose score is at least 0.90 x the best (round margin, declared here, chosen
after v1 but before v2 - a new pre-registration, not a re-fit of v1's 0.50).

## 2. Frozen substrate

Same as v1: fixture `e1021c20...` (19 scored probes, 21 required occurrences),
v1 projection, product BM25/tokenizer, `top_k=5`, records with
`seq < after_seq`, zero LLM calls. Reference from the recorded v1 run:
T2-B trigger arm 0.952 / 0.476 (not re-run).

## 3. Arms

| arm | index | candidacy rule | role |
|---|---|---|---|
| **T2v2-P `primary`** | combined (29 non-rejected) | rank-1 + score >= 0.90 x best | **PRIMARY** |
| T2v2-B2 `budget2` | combined | exactly the top 2 by score | variant |
| T2v2-M70 `margin70` | combined | rank-1 + score >= 0.70 x best | variant |
| T2v2-U90 `unfiltered90` | all 32 records | same rule as primary | reference |
| T2v2-A90 `promote90` | promoted (17) | same rule as primary | budget reference |

The 0.50 margin is not the primary rule anywhere; a descriptive sensitivity
table reports margins 0.50/0.70/0.90/1.00 and budgets 1/2/3 **without gating**.

## 4. Metrics

Identical definitions to v1: availability over the 21 required occurrences,
precision@k over deliveries, delivered count, mean delivered characters, and
informational latency (10 warmups + 100 repetitions per probe) and
determinism (two byte-identical collection passes excluding timing).

## 5. Gates (primary T2v2-P; all required)

- **H6-1 availability >= 0.952** (20/21; at least the trigger reference).
- **H6-2 precision@k >= 0.80** (the v1 miss).
- **H6-3 budget**: mean chars <= 1.25 x T2v2-A90 mean chars.
- **H6-4 no regression vs unfiltered**: precision >= precision(T2v2-U90) - 0.05.
- **H6-5 determinism**.

`all_pass` requires all five.

## 6. Expected readings (declared, not gates)

Precision 0.75-0.95 and availability 0.905-1.000 for the primary; if the two
required second occurrences (P15/M0006, P18/M0017) score below 0.90 x best,
availability lands at 0.905 and H6-1 fails - a clean negative is possible.
B2 and M70 are expected to sit between v1 and the primary on both axes.

## 7. Stop rules

- Any gate fail: line stays shadow-only, nothing promoted, no threshold
  re-fit. If H6-2 still fails, score margins do not separate the tail and
  candidacy bounding is exhausted; stop and report.
- If all gates pass: next step is the previously registered product-side
  shadow instrumentation pre-registration (real tapes, growth, latency,
  candidate quality); still no promotion or default change.

## 8. Threats and limits

One synthetic fixture, 19 scored probes, 21 occurrences; one case moves
availability by ~5%. The 0.90 margin is a round, pre-declared value chosen
after v1's aggregate diagnostics (not per-case inspection); the sensitivity
table exists so readers can see the whole margin curve rather than one point.
Variant outcomes never change the primary verdict.

## 9. Execution protocol

Harness `eval/two_tier_retrieval_v2.py`, outputs
`eval/results/two_tier_v2/report.json` and `report.md`, structural test
`tests/test_two_tier_retrieval_v2.py`, proof regenerated, one primary run plus
the determinism rerun, execution record appended to this document, all
committed on the `two-tier-v1` branch (PR #4 continues as the line record).

## Execution record (2026-09-22)

Recorded run: `eval/results/two_tier_v2/report.json` (one primary pass plus
the in-harness determinism rerun; timing informational). No pre-run
corrections; the first harness pass is the recorded one.

| arm | availability | precision@k | delivered | found | mean chars | p50 ms | p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|
| **T2v2-P primary (0.90)** | **0.905** | **0.826** | 23 | 19 | 86 | 0.051 | 0.080 |
| T2v2-B2 exact top-2 | 0.952 | 0.556 | 36 | 20 | 122 | 0.051 | 0.080 |
| T2v2-M70 margin 0.70 | 0.905 | 0.679 | 28 | 19 | 104 | 0.051 | 0.080 |
| T2v2-U90 unfiltered 0.90 | 0.905 | 0.760 | 25 | 19 | 92 | 0.057 | 0.089 |
| T2v2-A90 promote-only 0.90 | 0.714 | 0.652 | 23 | 15 | 87 | 0.036 | 0.059 |

Gates: H6-1 **false** (0.905 < 0.952); H6-2 **true** (0.826 >= 0.80);
H6-3 true; H6-4 true; H6-5 true; `all_pass` **false**.

Sensitivity over the combined index (descriptive, not gating):

| margin | availability | precision@k | | budget | availability | precision@k |
|---|---:|---:|---|---:|---:|---:|
| 0.50 | 1.000 | 0.512 | | top-1 | 0.857 | 0.947 |
| 0.70 | 0.905 | 0.679 | | top-2 | 0.952 | 0.556 |
| 0.90 | 0.905 | 0.826 | | top-3 | 1.000 | 0.420 |
| 1.00 | 0.857 | 0.947 | | | | |

Findings:

- **H6-2 fixed the v1 miss**: a 0.90 score margin lifts precision from 0.512
  to 0.826, above the 0.80 floor, with only 23 deliveries.
- **H6-1 failed structurally**: the same margin drops availability to 0.905
  (19/21), below the 0.952 reference. The two lost occurrences explain why:
  P15/M0006 sits at rank 2 with a score ratio in (0.50, 0.70) - delivered at
  0.50, dropped at 0.90; P09/M0017 sits at rank 3 (M0003 and M0019 rank
  above the required memory), so **no margin value catches it** (the margin
  curve is flat over it; only a top-3 budget reaches it, at precision 0.420).
- **No point of the declared family satisfies both gates**: highest precision
  with availability >= 0.952 is 0.556 (top-2); highest availability with
  precision >= 0.80 is 0.905 (margin 0.90). The noise shares the same
  mid-range score band as the required second occurrences, so score margins
  cannot separate them on this fixture.
- Declared expectations held: precision 0.826 inside the predicted
  0.75-0.95 band, and the pre-declared clean negative (0.905 -> H6-1 fail)
  materialized exactly.

Stop rule applied: any gate fail keeps the line **shadow-only**; nothing
promoted, no threshold re-fit. The H6-2-fail branch of section 7 did not
trigger (precision passed), so candidacy bounding is not formally exhausted -
but the measured frontier shows score-margin/budget families trade
availability for precision with no point meeting both declared gates. An
orthogonal candidacy signal would require a new pre-registration; the
default recommendation after this record is closure with the frontier
finding.
