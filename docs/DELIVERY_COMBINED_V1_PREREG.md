# delivery-combined-v1 — pre-registration (combined policy, two evaluations)

Status: **frozen before execution**. Date: 2026-09-22. Track: synthetic lab
(delivery + answer boundary). Follows `delivery-anchors-v1`
(`docs/DELIVERY_ANCHORS_V1_PREREG.md` execution record) and the owner's
instruction: the combined policy evaluated with **two separate readings** -
fact presence in the payload and answer accuracy with the same answerer -
so a delivery gain is never confused with a reasoning gain.

## 1. Policy W3 (combined, declared)

For every truncated payload item, bounded by its frozen body length
(header + summary preserved; `room >= 120` as in the product truncation):

- **non-numeric questions**: the product factual window (`fact_window`) -
  byte-identical to W1;
- **numeric/temporal questions** (digit, comparison or quantity cue, as in
  Amendment 1 of v1): the anchors window (best segment, immediate neighbors,
  date segments, first/last data-number segments excluding list markers,
  then coverage fill), under the same allocation.

So W3 = W1 everywhere + anchors where arithmetic/time is at stake. W0 is the
frozen delivered context; W1 the v1 factual window.

## 2. Evaluation A - delivery presence (deterministic, no LLM)

Same fixture and metric as v1 (gold atoms present in the required spans).
Gates: **A1** mean presence(W3) >= mean presence(W1); **A2** numeric mean
(W3) >= numeric mean (W1); **A3** non-numeric W3 equals W1 by construction;
**A4** per-case context length(W3) <= length(W0); **A5** determinism.

## 3. Evaluation B - answer accuracy (same answerer, blind judge)

- Answerer: `run_main_chatbot` (the product chatbot, frozen prompt),
  temperature 0, `memory_aware=False`, `temporal_instruction=False`; the
  case context is passed as `extra_context`. **The same answerer is used for
  every arm.**
- Judge: the frozen `e2e_bench` judge prompt (v1), temperature 0, blind to
  the arm; reference = the fixture gold string.
- N = 1 per case per arm; 30 cases x 3 arms = 90 answers + 90 judgments
  (<= 180 calls). Model: product default for both answerer and judge.
  Infrastructure failures are recorded; > 20% failures makes evaluation B
  **INCONCLUSIVE_INFRASTRUCTURE** (not a scientific result).
- Score: correct=1, partial=0.5, incorrect=0 (primary); strict (correct
  only) reported as secondary. Gates: **B1** score(W3) > score(W0);
  **B2** score(W3) >= score(W1) - 0.05; **B3** numeric subset:
  score(W3) >= score(W1); **B4** case-level downgrades W3 vs W1 <= 2.

## 4. Verdicts

Evaluation A and B are reported separately; promotion to a future
product-side pre-registration requires **both** to pass. `all_pass` = A and
B. Any failure: report, change nothing, re-fit nothing; windows remain OFF
in production regardless.

## 5. Expected readings (declared)

A: numeric mean(W3) > mean(W1), overall >= W1, non-numeric identical.
B: the honest expectation is **small or no answer-level movement** even
where delivery improves - the separation exists precisely to show this.
Recorded so the execution record cannot tell a post-hoc story.

## 6. Threats

N = 1 per cell: answer noise is real; a 1-2 case difference is not
interpretable (hence B4's bounded-regression form). Judge noise measured in
earlier audits (0.75-1.00 agreement); no second pass here (cost). Delivery
presence is a proxy, not correctness.

## 7. Execution protocol

Harness `eval/delivery_combined_v1.py` (`--eval a|b|both`), outputs
`eval/results/delivery_combined_v1/report.json` and `report.md`,
`tests/test_delivery_combined_v1.py`, proof regenerated, one run per
evaluation (A deterministic; B with the key from the environment, never
printed), execution record appended, all committed.

## Execution record (2026-09-22)

### Evaluation A — delivery presence (deterministic)

| arm | mean | numeric | non-numeric |
|---|---:|---:|---:|
| W0 | 0.515 | 0.486 | 0.583 |
| W1 | 0.643 | 0.538 | 0.889 |
| **W3** | **0.727** | **0.657** | 0.889 |

Gates A1-A5 **all true**: the combined policy keeps W1's non-numeric gains
(identical by construction), adds the anchors gain on numeric questions
(0.538 -> 0.657), and stays within the frozen contexts' length.

### Evaluation B — answer accuracy (same answerer, blind judge, N=1)

| arm | score | strict | numeric | counts (c/p/i) |
|---|---:|---:|---:|---|
| W0 | 0.383 | 0.367 | 0.405 | 11/1/18 |
| W1 | 0.583 | 0.533 | 0.500 | 16/3/11 |
| **W3** | **0.617** | **0.567** | **0.595** | 17/3/10 |

180 LLM calls (90 answers + 90 judgments), 0 infrastructure failures, judge
prompt v1, temperature 0.

Gates: B1 **true** (0.617 > 0.383); B2 **true** (>= 0.583 - 0.05); B3
**true** (numeric 0.595 >= 0.500); B4 **false** (3 downgrades vs W1, bound
was <= 2); `all_pass` **false** (A all true, B4 fails).

Case-level flips W3 vs W1: **5 upgrades, 3 downgrades, 22 identical**
(net +2). Disclosed noise: case u3b-27 is **non-numeric, and its W1 and W3
contexts are byte-identical**, yet the judge flipped correct -> incorrect -
this downgrade is pure N=1 evaluation noise, not a policy effect. The other
two downgrades (u3a-19, u3a-22) are numeric with genuinely different
contexts; the upgrades include u3b-30/35/41 and u3a-15.

Findings:

- **The combined policy dominates on both axes in the lab**: delivery mean
  0.727 (best of all arms) and answer score 0.617 (best), with numeric
  answer score 0.595 vs 0.500 (W1) and 0.405 (W0).
- **Declared expectation missed**: B was expected to show small or no
  movement; instead the delivery repairs moved answers substantially on
  this fixture (0.383 -> 0.617). Recorded as a miss; the separation of the
  two readings still did its job (A and B are reported independently).
- **B4 fails as pre-registered** (3 > 2); with the disclosed noise cell, the
  real policy downgrades are 2. No re-fit: the gate stays failed.
- N=1 was the declared threat and it materialized; the next accuracy round
  should use N>=3 per cell (or judge two passes) to separate policy effects
  from answer noise.

Stop rules applied: nothing promoted; windows remain OFF in production.
Lab-only evidence; the dual-track rule still requires a future real window
from zero for any product change.
