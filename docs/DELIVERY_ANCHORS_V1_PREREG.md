# delivery-anchors-v1 — lab pre-registration (item 2: evidence delivery)

Status: **frozen before execution**. Date: 2026-09-22. Track: synthetic lab
(delivery mechanics, deterministic; no LLM, no agents re-run).

The owner's priority item 2: improve the delivered passage. Compare the
current delivery, the factual window (product `fact_window`) and a new window
with **neighboring sentences and temporal/numeric anchors**. Evaluate per
question type and verify the known arithmetic-anchor regression (case
`u3a-12`, "How much RAM...?" gold `16GB`) does not return.

## 1. Substrate (frozen, no re-runs)

`eval/fixtures/composition_u4` (30 cases, blocks u3a/u3b), the frozen
`graph_augment_precise` payload as `case["context"]` (sha1 in the fixture),
records with full texts. The frozen context is the baseline and is parsed
into per-item spans with `fact_presence.item_span`; the baseline is verified
by the fixture `context_sha1` before any transformation.

## 2. Policies (same items, same per-item lengths; 4000 preserved)

Only **truncated** items are re-filled, each bounded by its frozen delivered
body length (the U4.3 contract). Header + summary are preserved (room >= 120
for the window, as in the product `_truncate(window=True)`); otherwise the
frozen body is kept.

- **W0 current** = the frozen context (head truncation as delivered).
- **W1 factual window** = product `fact_window(why, question, room)`.
- **W2 anchors window** = new deterministic `anchors_window(why, question,
  room)`: the best question-matching segment, then its immediate neighbors
  (1 each side), then every segment containing an explicit date (ISO, year,
  month name), then - when the question carries a numeric or comparison cue
  (a digit, or before/after/increase/decrease/difference/more/less/compare/
  change) - the first and last segments containing a number, then remaining
  segments by question coverage. Segments are added while the allocation
  fits and printed in original order, joined by " … ".

## 3. Metrics

Per case and arm, atoms from the case gold (`item_fact_atoms`), presence in
the union of the required items' spans (`atom_present` after `norm`):
fraction of atoms present and all-present flag. Per question type: numeric/
comparison flagged as above vs the rest. Anchor check for `u3a-12` (`16GB`).

## 4. Gates

- **D1** W2 has no regression vs W0: no case with presence strictly lower.
- **D2** W2 repairs at least as many cases as W1 (repair = presence higher
  than W0).
- **D3** `u3a-12`: W1 loses the `16GB` anchor (presence lower than W0) and
  W2 restores it (presence equal to W0); if W1 does not lose it on this
  frozen context, the gate reports the fact and D3 is re-interpreted as
  "no anchor loss on the delivered arm" (recorded, not re-fitted).
- **D4** numeric/comparison cases: mean presence W2 >= W1 and >= W0.
- **D5** non-numeric cases: W2 >= W0 (no collateral loss).
- **D6** budget: every re-filled item <= its frozen body length; context
  rebuild of W0 matches the fixture sha1; deterministic (two runs equal).

## 5. Expected readings (declared, not gates)

W1 recovers window-selected facts but drops numeric anchors (the known
regression); W2 keeps W1's repairs and restores the start/end values, so D3
passes and D4 improves. Non-numeric cases should be unchanged.

## 6. Stop rules

Any gate fail: report, change nothing, re-fit nothing. A pass is lab-only
evidence for a future product-side pre-registration (window variants remain
off by default; production untouched); it never promotes. Delivery-level
metrics (fact presence) are proxies for correctness, not answer accuracy.

## 7. Execution protocol

Harness `eval/delivery_anchors_v1.py`, outputs
`eval/results/delivery_anchors_v1/report.json` and `report.md`,
`tests/test_delivery_anchors_v1.py`, proof regenerated, one primary run plus
determinism rerun, execution record appended, all committed.

## Amendment 1 (2026-09-22, pre-execution; dry run disclosed)

A dry run on the frozen fixture found three implementation/design issues
before any recorded run; no recorded aggregates existed. Corrections:

1. **Numeric cue completed**: the cue missed quantity words, so "How much
   RAM...?" (case u3a-12) was not treated as numeric and the anchor was not
   attempted. Cue now: a digit, the comparison words listed, or the quantity
   words much/many/long/old/total/number/percent/years/days/weeks/times.
2. **W2 made selective** (the dry run confirmed the known non-universality of
   windows, M0149/E5): W2 applies the anchors window **only to numeric/
   comparison questions**; all other cases keep the frozen body (W0). This
   is the declared hypothesis for item 2: anchors where arithmetic is at
   stake, no collateral change elsewhere.
3. **Budget gate corrected**: the frozen W0 contexts themselves are 4000-4018
   characters (they include separators), so D6 now requires per case
   `len(W1) <= len(W0)` and `len(W2) <= len(W0)`, plus every refilled body
   bounded by its frozen body length.

Gates re-declared for the recorded run: **D1** no per-case regression vs W0;
**D2** numeric mean presence(W2) >= mean presence(W1); **D3** case u3a-12:
W1 loses the `16GB` anchor and W2 restores it; **D4** W2 repairs at least one
numeric case beyond W1; **D5** non-numeric W2 equals W0 by construction;
**D6** budget as above; **D7** determinism.

## Execution record (2026-09-22)

Two dry runs disclosed (implementation defects only, no recorded aggregates
existed): (1) the numeric cue missed quantity words and the budget gate
compared against 4000 instead of against W0 (Amendment 1); (2) the record
lookup keyed by memory id alone, but ids repeat across cases (122 records /
30 cases), so case 12 was re-filled from another case's text - fixed to key
by (case, memory id) before the recorded run.

Recorded run; determinism rerun identical.

| arm | all-present | mean presence | numeric | non-numeric | repairs |
|---|---:|---:|---:|---:|---:|
| W0 current | 14/30 | 0.515 | 0.486 | 0.583 | - |
| W1 factual window | 17/30 | 0.643 | 0.538 | **0.889** | 6 |
| W2 anchors (selective) | 17/30 | 0.635 | **0.657** | 0.583 | 5 |

Gates: D1 **true**; D2 **true** (0.657 >= 0.538); D3 **false as literally
specified** (case u3a-12: W1 presence 1.000, i.e. **the anchor loss does not
reproduce at delivery level** on the frozen fixture); D4 **true**; D5
**true**; D6 **true**; D7 **true**; `all_pass` false.

Findings:

- **The factual window is a delivery-level win across the board once the
  correct records are used**: mean presence 0.515 -> 0.643 and all-present
  cases 14 -> 17/30, including non-numeric questions (0.583 -> 0.889). The
  earlier "not universal" reading (M0149/E5) is not contradicted at the
  answer level, but at this layer the window repairs more than it breaks.
- **Anchors help numeric questions specifically**: numeric mean 0.538 (W1)
  -> 0.657 (W2). Because W2 is selective by design, it forfeits W1's
  non-numeric gains; the natural next hypothesis is the combined policy
  (factual window everywhere + temporal/numeric anchors on numeric
  questions), to be pre-registered separately.
- **D3 re-interpreted per its own clause**: the recorded arithmetic-anchor
  regression (case 0, `16GB`) was an answer-level phenomenon; on the frozen
  delivery it does not manifest (the anchor is present in W1). Reported, not
  re-fitted. The 16GB value is present in all three arms.
- Per-case D1: zero regressions vs W0; D5: non-numeric arms are unchanged
  by construction.

Stop rules applied: `all_pass` false, nothing promoted, nothing re-fitted.
Delivery-level presence is a proxy for correctness, not answer accuracy.
Lab-only evidence; production defaults (windows OFF) untouched.
