# component-allocation-v1 — pre-registration (stratified currency coverage)

Status: **frozen before execution**. Date: 2026-09-22. Track: synthetic lab.

Owner direction after `money-holdout-v2` (M0354): either test a way to
reserve space for **all values needed by a calculation**, with criteria
defined before execution, or close the case as space-limited. This
experiment tests the first option.

## 1. Motivation (dev case, recorded before the rule)

u3a-24 needs `$1,000` + `$300` (the `$1,300` total is never written). In
M0012 (room 1,616 chars) the W4 window delivers `$1,000` but not `$300`:
currency segments chosen in distance order cluster near the best segment,
while the components live at different depths (segments 92/101/131/152 and
131/137/144/150; segment **131 contains both**). The limit is positional
allocation, not localization.

## 2. Rule W6c (stratified currency coverage; single declared delta over W4)

For **money-cue questions** (same trigger as W4), the item's window budget
is split into **4 equal positional strata** of the record text; within each
stratum, currency-bearing segments are included **in text order** until the
stratum's share is spent; unused share carries over to the next stratum (the
last absorbs the remainder). Non-money questions: identical to W1. The item
bound stays the frozen body length (contract unchanged).

## 3. Arms and gates (one-shot; exploratory)

Arms: **W4** (reference, imported frozen) and **W6c**.

- **Z1** dev case: u3a-24's M0012 span under W6c contains **both** `1000`
  and `300` (W4 contains only `1000`, recorded).
- **Z2** no regression on the money holdout: W6c delivers the target in
  **12/12** of `money_holdout_v2` cases (W4 reference 12/12).
- **Z3** budget/determinism: per-case context length <= W1; two runs equal.
- **Z4** answer gate (N=3, same answerer, blind judge, u3a-24, W4 vs W6c,
  12 calls): score(W6c) >= score(W4) - 0.05, reported separately.
- **Z5** infrastructure failures <= 20%.

`all_pass` = Z1-Z5. This is **exploratory** (rule designed on the dev case);
a multi-component holdout would be required before any general claim; nothing
is promoted and windows stay OFF.

## 4. Execution protocol

Harness `eval/component_allocation_v1.py` (`--skip-llm` for Z1-Z3), outputs
`eval/results/component_allocation_v1/{report.json,report.md}`,
`tests/test_component_allocation_v1.py`, proof regenerated, execution record
appended, committed.

## Execution record (2026-09-22)

Deterministic delivery stage plus the 12-call answer gate; no failures.

| reading | result |
|---|---|
| u3a-24 components under W4 | 1000 yes, **300 no** |
| u3a-24 components under **W6c** | **1000 yes, 300 yes** |
| money holdout hits (W4 / W6c) | 12/12 / **12/12** (no regression) |
| u3a-24 answers (W4 / W6c) | correct x3 / correct x3 |

Gates **Z1-Z5 all true**; `all_pass` true.

Findings:

- **The stratified rule fixes the delivery-level component loss**: with the
  item's frozen budget (room 1,616) W6c delivers **both** `$1,000` and
  `$300` (segment 131 carries both amounts) where W4 delivered only the
  first; no regression on the 12 single-value holdout cases.
- **No answer-level gain was observed on this dev case**: both arms answered
  correctly 3/3 (the answerer reached the right conclusion with W4's window
  too), so the fix's value is at the delivery stage here - recorded, not
  overclaimed.
- **Exploratory**: W6c was designed on u3a-24; a **multi-component holdout**
  (records needing two or more distant values) is required before any general
  claim. Named next step if pursued. Nothing promoted; windows OFF.
