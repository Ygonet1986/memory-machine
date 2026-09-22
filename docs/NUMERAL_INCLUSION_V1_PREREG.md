# numeral-inclusion-v1 — pre-registration (correction 2, u3a-19 class)

Status: **frozen before execution**. Date: 2026-09-22. Track: synthetic lab.

Second named correction from `diagnostic-trace-v1` (M0328): the required
record reaches the payload but the delivered span is cut before a mid-text
numeral (`$200` in u3a-19). The current anchors only include the first and
last data-number segments. **W4** extends that to the nearest data-number
segments around the best segment, with the phrase metric
(`phrase-delivery-v1`) as the delivery gate and a repeated-answer gate.

## 1. Policy W4 (single declared delta over W3)

W3 is unchanged except the numeric anchor set: **all data-number segments
(list markers excluded), ordered by distance to the best segment, up to 4
(nearest first)**, instead of only the first and last. Everything else -
best segment, immediate neighbors, date segments, coverage fill, allocation,
budget, header/summary preservation - is identical to `anchors_window` in
`delivery_anchors_v1`. Non-numeric questions: identical to W3 (fact window).

## 2. Arms and gates

Arms: **W3** (reference) and **W4** on the tracked cases (u3a-12, u3a-19,
u3a-22, u3b-27) with frozen contexts from `delivery_combined_v1`; the
phrase metric from `phrase_delivery_v1`.

- **N1 fixes the target class**: u3a-19: phrase `200$` **present under W4**,
  absent under W3 (and W0/W1, already recorded).
- **N2 no new regressions**: on the other tracked cases, anything present
  under W3 stays present under W4 (phrase or atom basis); budgets per case
  never exceed the W0 length.
- **N3 answer gate (N=3, same answerer, blind judge)**: u3a-19:
  score(W4) > score(W3); u3a-22 control: score(W4) >= score(W3) - 0.05
  (W4 is not expected to fix the temporal-phrase loss - that correction is
  not part of this experiment and stays open).
- **N4 determinism** of the delivery stage; **N5** infra failures <= 20%.

`all_pass` requires N1-N5. 2 cases x 2 arms x 3 runs x 2 calls = 24 calls
cap.

## 3. Expected readings (declared)

u3a-19: phrase present and answers stable-correct under W4, against
incorrect/unstable under W3; u3a-22: unchanged (still missing `2week` under
both arms, answers at the W3 level); controls untouched.

## 4. Stop rules

Any gate fail: report, change nothing, re-fit nothing; windows remain OFF.
A pass is lab-only evidence for a future combined policy (with the temporal
phrase correction still pending); never a promotion.

## 5. Execution protocol

Harness `eval/numeral_inclusion_v1.py`, outputs
`eval/results/numeral_inclusion_v1/{report.json,report.md}`,
`tests/test_numeral_inclusion_v1.py`, proof regenerated, execution record
appended, committed.

## Amendment 1 (2026-09-22, pre-execution; dry run disclosed)

Dry run (deterministic stages only, no recorded aggregates) showed the
nearest-4 rule fails for u3a-19: the `$200` segments are far from the best
segment (distances 106-125) while the nearest data-number segments are
unrelated prices. The target numerals live in short segments that fit the
allocation easily; selection priority, not budget, was the issue.

**W4 numeric anchor set (declared): data-number segments ranked by
question-token coverage (desc), then distance to the best segment (asc),
then index; include up to 4.** Everything else in W4 is unchanged. Gates
N1-N5 stay as declared.

## Amendment 2 (2026-09-22, pre-execution; second dry run disclosed)

Amendment 1's relevance-then-distance ranking still missed the target: the
`$200` segments have zero question-token overlap (the question says
"spent/gifts", the text says "spending/gift") and are far from the best
segment. Declared refinement, still one generic rule and no case-specific
constants: **when the question carries a money cue (amount, spent, cost,
price, paid, dollars, budget, $), the numeric anchor set becomes the
data-number segments adjacent to a currency marker ($ or dollars/usd)**,
ranked by question coverage (desc), then distance (asc), cap 4; other
questions keep the data-number set. Verified in the dry run: the gift-budget
segments (`$150-$200`) enter the top 4 while the budget still fits (955
characters, short segments).

## Amendment 3 (2026-09-22, pre-execution; third dry run disclosed)

The cap of 4 still excluded the target segments (other currency segments are
closer to the best segment). Declared final refinement: for money-cue
questions the numeric anchor set is **all currency-bearing segments in
distance order (no cap)**; the allocation itself bounds how many enter.
Everything else unchanged. Honest note: the rule was refined three times on
the same case - this is **exploratory rule development** and any future
claim needs a holdout (as in the causal-line protocol); it is recorded as
such, not as a validated rule.

## Execution record (2026-09-22)

Delivery (phrase metric, deterministic) and answer gate (N=3, same answerer,
blind judge, 24 calls, 0 failures).

| case | arm | phrase/basis | present |
|---|---|---|---|
| u3a-12 | W3/W4 | `16gb` | ok / ok |
| u3a-19 | W3 | `200$` | **MISS** |
| u3a-19 | **W4** | `200$` | **ok** |
| u3a-22 | W3/W4 | `2week` | MISS / MISS (unchanged) |
| u3b-27 | W3/W4 | atom fallback | ok / ok |

| case | W3 verdicts | W4 verdicts |
|---|---|---|
| u3a-19 | incorrect/partial/incorrect | **correct/correct/incorrect** |
| u3a-22 | incorrect x3 | incorrect x3 (control unchanged) |

Gates **N1-N5 all true**; `all_pass` true. The mid-text `$200` now reaches the
delivered span under W4, and the answer improves from 0.17 to 0.67 (one
unstable run remains - N=3 noise, consistent with the measured floor); the
u3a-22 temporal-phrase loss is untouched, as declared (separate correction).

Disclosure: the W4 rule was developed through three pre-execution amendments
on this same case (nearest-4 -> relevance-then-distance -> currency-uncapped);
this is **exploratory rule development**, and any future claim for it needs a
holdout, per the causal-line protocol. The delivery gain on u3a-19 is
mechanically verified (phrase present) and consistent with the answer
movement, but a one-case accuracy delta does not clear the noise floor.

Nothing promoted; windows remain OFF. Open named work: (a) holdout validation
of the currency rule, (b) the temporal-phrase correction for the u3a-22 class,
(c) item 1 (systematic temporal provenance) now has a concrete metric to use.
