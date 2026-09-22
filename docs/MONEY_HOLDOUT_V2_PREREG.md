# money-holdout-v2 — corrected W4 holdout (one-shot)

Status: **frozen before execution**. Date: 2026-09-22. Track: synthetic lab.

Corrects the two flaws of `money-holdout-v1` (M0332): its records were
shorter than the allocation (no truncation happened) and its external check
looked for a literal phrase on a derived-sum gold. This fixture has long
records, and the external check is **component-based**.

## 1. Fixture (new; discriminating design verified at generation)

`eval/fixtures/money_holdout_v2/` (`gen_money_holdout_v2.py`, 12 cases,
hash `319ff6e831c7f8fef2e79a8efde59af75c3dc70b29b42a9ecaf7fcc4ca4f8d28`).
Records are longer than the 3,600-char allocation (truncation happens); the
target sentence carries **no question tokens**; a question-rich anchor
cluster sits at the head; positions declared 4 early / 4 middle / 4 late.
Verified with the product code: the frozen W4 window contains the target in
**12/12**, the product fact window W1 in **4/12** (the early group only;
middle/late asserted as W1 misses).

## 2. Arms

- **W1** = product `fact_window(text, question, 3600)` (reference).
- **W4** = frozen money rule (imported unchanged from `numeral_inclusion_v1`,
  source hash pinned): money-cue questions include every currency-bearing
  segment in distance order, budget-bounded.

Delivery metric: the target currency phrase present in the arm's window
(`phrase_delivery_v1`).

## 3. Gates (one-shot; no re-fit)

- **Y1** W4 delivers the target in 12/12 cases.
- **Y2** W4 > W1, with the advantage in **all 8 middle/late cases** (where W1
  misses by design).
- **Y3** external component check (u3a-24, derived total `$1,300`): the
  **component amounts** executed ($1,000 and $300 in M0012) are present in
  the W4 spans (W1 reported) - the literal total is never written.
- **Y4** context length(W4) <= length(W1) per case; determinism.
- **Y5** repeated-answer gate: first three case ids, N=3, same answerer and
  blind judge (36 calls): score(W4) >= score(W1) - 0.05, reported separately.
- **Y6** infrastructure failures <= 20%.

`all_pass` = Y1-Y6. Pass = W4 validated on this holdout (lab-only; nothing
promoted; windows stay OFF; a product claim still needs the real window).
Fail = report, no re-fit.

## 4. Execution protocol

Harness `eval/money_holdout_v2.py` (`--skip-llm` for Y1-Y4), outputs
`eval/results/money_holdout_v2/{report.json,report.md}`,
`tests/test_money_holdout_v2.py`, proof regenerated, execution record
appended, committed.

## Execution record (2026-09-22) — one-shot holdout

Delivery deterministic; answer gate N=3 on G01-G03 (36 calls, 0 failures).

| reading | result |
|---|---|
| W1 hits / W4 hits (12 cases) | **4 / 12** (W1 only the early group) |
| middle/late (8 cases) | W1 0/8, **W4 8/8** |
| answers G01 / G02 / G03 (W1 -> W4) | correct x3 both / **incorrect x3 -> correct x3** / **incorrect x3 -> correct x3** |
| external u3a-24 components | W1 {1000: no, 300: no}; **W4 {1000: yes, 300: no}** |

Gates: Y1 **true**; Y2 **true**; **Y3 false**; Y4 true (budget/determinism);
Y5 **true**; Y6 true; `all_pass` false.

Findings:

- **The money rule generalizes on the corrected holdout**: with long records
  that actually truncate, W4 delivers the target in 12/12 (W1: 4/12), fixing
  **all 8 middle/late cases**, and the repeated-answer gate confirms two of
  the three sampled cases move from 0/3 to 3/3 (the third was already
  correct).
- **Y3 fails on the external derived-total case, cause named**: u3a-24's
  item M0012 has room 1,616 characters; the W4 window delivers the
  `$1,000` component but the `$300` segment does not fit under the frozen
  item bound (the total `$1,300` is never written in the source). This is a
  **contract/allocation limitation**, not a rule failure - the same class as
  the u3a-17 lesson: the item budget bounds what any window can deliver.
- Named next step (no change made): a component-aware allocation for
  derived-total items would need its own pre-registration; alternatively the
  case closes as contract-limited. W4 stays exploratory-unvalidated **only**
  on this external gate; the holdout delivery/answer evidence is positive.
  Nothing promoted; windows OFF; admission-shadow-v2 untouched.
