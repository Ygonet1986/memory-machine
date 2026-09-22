# temporal-breadth-v1 — pre-registration (step 3: is the u3a-22 class recurring?)

Status: **frozen before execution**. Date: 2026-09-22. Track: synthetic lab.

Step 3 of the owner's order: apply the phrase metric to the temporal set and
count how many cases have **origin and ingestion correct but the phrase
absent from delivery**, comparing W1, W3 and W5. This decides whether W5
fixes a recurring class or only u3a-22. Delivery stage only (no LLM); windows
stay OFF.

## 1. Scope (metadata selection, no outcome peeking)

All cases whose question matches the temporal cue
(`TEMPORAL_CUE_RE` from `temporal_phrase_v1`): **13 of 30**. Phrase checks
apply to the subset whose gold contains a temporal phrase (6 cases:
u3a-14, u3a-17, u3a-21, **u3a-22 (DEV - the rule was developed here)**,
u3b-30, u3b-40); the others are reported through the atom fallback and
counted separately.

## 2. Frozen rules (pinned)

W1 = product `fact_window`; W3 = `anchors_window` on numeric-cue questions;
**W5 imported unchanged** from `temporal_phrase_v1` (source hash pinned in
the harness). No rule changes.

## 3. Stages and classification (deterministic)

Per case, phrase basis when the gold has a phrase, else the atom fallback:

- **ingestion**: phrase/atom present in the required records' full text;
- **delivery**: present in the arm context (W1/W3/W5), contexts rebuilt with
  the frozen functions;
- flags per case: `ingestion_ok`, `w1_ok`, `w3_ok`, `w5_ok`,
  **`delivery_loss_w1`** = ingestion_ok and not w1_ok,
  **`fixed_by_w5`** = delivery_loss_w1 and w5_ok,
  **`w3_regression`** = w1_ok and not w3_ok,
  **`w5_recovers_w3`** = w3_regression and w5_ok,
  `w5_regression` = w1_ok and not w5_ok.

## 4. Verdict rule (declared)

- **Recurring class** if `fixed_by_w5` among non-DEV cases >= 1 (lab
  evidence that W5 repairs a class, not only its development case).
- Otherwise **singleton**: u3a-22 was an isolated repair at the W1 level,
  and the report states what the temporal set actually shows (e.g., W1
  already delivered the phrase elsewhere; W3 regressions recovered by W5).

## 5. Gates

- **V1** counts are complete and consistent (no impossible row: a case
  cannot be `fixed_by_w5` without `delivery_loss_w1`).
- **V2** determinism (two runs identical).
- **V3** W5 has no regression vs W1 on any temporal case (`w5_regression`
  count 0).
- **V4** budgets per case <= W0 length.

`all_pass` = V1-V4; the class verdict is the experiment's answer, not a gate.
No promotion in any case; windows remain OFF.

## 6. Execution protocol

Harness `eval/temporal_breadth_v1.py`, outputs
`eval/results/temporal_breadth_v1/{report.json,report.md}`,
`tests/test_temporal_breadth_v1.py`, proof regenerated, one run, execution
record appended, committed.

## Execution record (2026-09-22)

Delivery stage only (no LLM); W5 source hash pinned; determinism verified.

| case | dev | basis | ingestion | W1 | W3 | W5 | flags |
|---|---|---|---|---|---|---|---|
| u3a-14 | | phrase | MISS | MISS | MISS | MISS | - |
| u3a-17 | | phrase | ok | MISS | MISS | MISS | delivery_loss_w1 |
| u3a-21 | | phrase | MISS | MISS | MISS | MISS | - |
| u3a-22 | DEV | phrase | ok | ok | MISS | ok | w3_regression, w5_recovers |
| u3b-30 | | phrase | MISS | MISS | MISS | MISS | - |
| u3b-31 | | atom | ok | MISS | ok | ok | delivery_loss_w1, fixed_by_w5 |
| u3b-40 | | phrase | MISS | MISS | MISS | MISS | - |
| u3b-41 | | atom | ok | MISS | MISS | MISS | delivery_loss_w1 |
| (5 non-phrase controls) | | atom | ok | ok | ok | ok | - |

Counts: `delivery_loss_w1 = 3` (all non-DEV), `fixed_by_w5 = 1`
(u3b-31, non-DEV), `w3_regressions = 1` (u3a-22 DEV, recovered by W5),
`w5_regressions = 0`. Gates V1-V4 **all true**; declared verdict rule gives
**recurring_class**.

Honest reading (not re-fitted):

- **Class evidence is narrow**: exactly one independent W1 delivery loss
  (u3b-31) is repaired - and it is repaired by **W3**, not by W5's temporal
  addition (W5 inherits it). W5's specific contribution remains the DEV case
  u3a-22 (W3 regression recovered, 0 W5 regressions).
- **The dominant temporal classes are upstream of delivery**: four cases
  (u3a-14, u3a-21, u3b-30, u3b-40) have **ingestion misses** - the gold
  phrase is not in the required records' texts (derived/composed quantities:
  weeks between dates, total years, 4y9m, days-ago). These belong to
  composition/ingestion (item 1 territory), not to windowing.
- **u3b-41 is an unanswerable-gold case** ("The information provided is not
  enough..."): the atom check misclassifies it as a delivery loss; it is
  excluded from the class interpretation and recorded as a metric limitation
  for abstention golds.
- **One residual delivery loss remains unfixed by any arm** (u3a-17,
  `over a year`): worth a dedicated look before any further rule.

Nothing promoted; windows OFF. This closes step 3. Open next work: corrected
money holdout (W4), the u3a-17 residual, and abstention-gold handling in the
phrase metric.
