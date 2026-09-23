# multi-component-holdout-v1 — pre-registration (W6c generality, one-shot)

Status: **frozen before execution**. Date: 2026-09-22. Track: synthetic lab.

Required by `component-allocation-v1` (M0356): W6c was designed on the dev
case, so a **new holdout with questions that require two or more distant
values** must evaluate whether the stratified rule generalizes. This is that
one-shot evaluation.

## 1. Fixture (new; discriminating design verified at generation)

`eval/fixtures/multi_component_holdout_v1/`
(`gen_multi_component_holdout_v1.py`, 12 cases, hash
`93f16dcb64d3180792cc2844690c8744293a74171bc863df032724830460d9c4`). Each
record is long (110 segments), holds two component values in **different
positional strata** (slots 18 and 88) plus distractor amounts, and the
combined total is **never written**. Design checks (product code): both
components present; **W6c delivers both in 12/12**; W4 in **0/12**; W1 in
0/12.

## 2. Arms and gates (one-shot; no re-fit)

Arms **W4** (reference, frozen by hash) and **W6c** (candidate, source hash
pinned), both bounded by the item's frozen body length.

- **M1** W6c delivers **both** components in >= 10/12 cases.
- **M2** strict advantage: both-components cases(W6c) > both-components
  cases(W4).
- **M3** answer gate: first three cases (L01-L03), N=3, same answerer and
  blind judge, W4 vs W6c (36 calls): gold = the computed total; gate
  score(W6c) > score(W4) (the missing component should hurt the reference).
- **M4** budget/determinism: per-case arm length <= W1 context; two runs
  equal.
- **M5** infrastructure failures <= 20%.

`all_pass` = M1-M5. A pass validates W6c in the lab on multi-component
questions (still lab-only; nothing promoted; windows OFF; a product claim
still needs the real window). A fail: report, no re-fit.

## 3. Execution protocol

Harness `eval/multi_component_holdout_v1.py` (`--skip-llm` for M1-M2, M4),
outputs `eval/results/multi_component_holdout_v1/{report.json,report.md}`,
`tests/test_multi_component_holdout_v1.py`, proof regenerated, execution
record appended, committed.

## Execution record (2026-09-22) — one-shot holdout

Delivery deterministic; answer gate N=3 on L01-L03 (36 calls, 0 failures).

| reading | result |
|---|---|
| both components delivered (12 cases) | W4 **0/12** vs **W6c 12/12** |
| answers L01 / L02 / L03 | W4 **incorrect x3** each; **W6c correct x3** each |
| answer scores (three cases) | W4 **0.0** vs W6c **3.0** |

Gates **M1-M5 all true**; `all_pass` true.

Findings:

- **W6c generalizes on the multi-component holdout**: with two distant values
  (slots 18 and 88, different strata) and the total never written, the
  distance-order rule delivers both components in **0/12** cases while the
  stratified rule delivers both in **12/12**.
- **The gain reaches the answers**: all three sampled cases move from
  `incorrect` in every run under W4 to `correct` in every run under W6c -
  the missing component was decisive, closing the "delivery gain without
  answer gain" caveat observed on the dev case.
- This validates the stratified component allocation in the lab (dev case +
  single-value holdout + multi-component holdout). It remains **lab-only
  evidence**: nothing promoted, windows OFF; a product-side claim still
  requires the real window under the dual-track rule. The W4 lineage stays
  exploratory-unvalidated only where explicitly recorded (the earlier Y3
  contract limit is superseded at the delivery level by W6c).
