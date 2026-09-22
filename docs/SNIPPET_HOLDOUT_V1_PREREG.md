# snippet-holdout-v1 — pre-registration (one-shot holdout for union + query window)

Status: **frozen before execution**. Date: 2026-09-22. Track: synthetic lab.

The combined design (candidate union + question-windowed snippets) passed on
the cases where it was developed (`snippet-window-v3`, M0349) and is
**exploratory**. This experiment evaluates it **once** on a new fixture with
buried facts, per the stated holdout requirement. The W4 money holdout stays
independent; windows stay OFF.

## 1. Holdout fixture (new, verified at generation)

`eval/fixtures/snippet_holdout_v1/` (`gen_snippet_holdout_v1.py`, 12 cases,
sample hash `e352a6f25391a4b738963bb53f2d2952218b2e92c608c8cfbf8971ab53e3932d`).
Design properties verified with the product code before freezing (12/12):
the answering fact is **beyond the first 400 characters**, the product
`fact_window(text, question, 400)` **contains it**, and the required record
is in the lexical **top-5**. Simulated annotations list three decoy records
only, reproducing the annotation-miss pattern the design addresses.

## 2. Arms (same union list for both; frozen v2 prompt, N=3)

- **S-head**: first 400 characters per candidate.
- **S-query**: `fact_window(text, question, 400)` per candidate.

Union list = simulated annotations ∪ lexical top-5 (deterministic, declared
in the fixture and recomputed with the product BM25).

## 3. Metrics and gates (one-shot; no re-fit)

- **X1** mean coverage(S-query) > mean coverage(S-head).
- **X2** generalization: the required record is annotated under S-query in
  >= 2/3 runs on **at least 10 of 12 cases** (>= 80%).
- **X3** undue(S-query) <= undue(S-head) + 6/12 per case (mean over runs).
- **X4** infrastructure failures <= 20%.

`all_pass` = X1-X4. 12 cases x 2 arms x 3 runs = 72 calls. A pass validates
the design on a holdout (lab-only; still no promotion, windows OFF). A fail:
report and no re-fit.

## 4. Execution protocol

Harness `eval/snippet_holdout_v1.py`, outputs
`eval/results/snippet_holdout_v1/{report.json,report.md}`,
`tests/test_snippet_holdout_v1.py` (fixture regeneration, burial invariants,
recorded verdicts), proof regenerated, execution record appended, committed.

## Execution record (2026-09-22) — one-shot holdout

72 calls (12 cases x 2 arms x 3 runs), 0 infrastructure failures.

| arm | mean coverage | undue/case |
|---|---:|---:|
| S-head | 0.028 | 1.500 |
| **S-query** | **1.000** | **0.000** |

- **recovered cases (S-query, required annotated in >= 2/3 runs): 12/12**.
- Gates **X1-X4 all true**; `all_pass` true.

Findings:

- **The combined design generalizes on the holdout**: with facts buried
  beyond the head 400 characters, head snippets recover almost nothing
  (0.028 coverage) and the agents annotate decoys (1.5 undue per case),
  while question-windowed snippets recover **every** required record with
  **zero** undue annotations.
- The fixture's design properties held (12/12 verified at generation): fact
  beyond 400 chars, query window contains it, required record in lexical
  top-5.
- This is the strongest lab result of the annotation line and closes the
  stated holdout requirement for the snippet component. It remains
  **lab-only evidence**: no promotion, windows OFF; a product-side claim
  would need the real window (dual-track rule). The W4 money holdout remains
  independent and pending.
