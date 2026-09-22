# snippet-window-v3 — pre-registration (question-windowed candidate snippets)

Status: **frozen before execution**. Date: 2026-09-22. Track: synthetic lab.

Hypothesis 3 (owner direction after `annotation-union-v2`, M0347): the
candidate text window shown to the agents determines annotation; select each
candidate's snippet **based on the question** instead of the head 400 chars,
repeat N=3 on the same cases, and check whether M0043 is recovered. If it is,
**union + window** becomes a design candidate (still subject to evaluation).

## 1. Arms (same union list U = A ∪ L5 for both; same frozen prompt)

- **S-head** (control): first 400 characters of `summary + " " + why` -
  reproduces the v2 U arm.
- **S-query** (candidate): the product's deterministic question window
  (`fact_window(text, question, 400)`) - best matching segment plus
  left/right expansion within the same 400 characters.

## 2. Deterministic dry check (disclosed, design justification)

With 400 characters, `fact_window` on M0043 **contains "over a year"** (the
head 400 does not; it sits at char 6,927). The same check is reported as an
input-snippet coverage column for all cases (informational, not a gate).

## 3. Metrics and gates

Same metrics as v2 (coverage, undue, recovered; N=3, 30 cases, 180 calls).

- **H3-1** mean coverage(S-query) > mean coverage(S-head).
- **H3-2** undue(S-query) <= undue(S-head) + 10/30 per case (mean over runs).
- **H3-3** u3a-17: M0043 annotated in >= 2/3 runs under S-query.
- **H3-4** infrastructure failures <= 20%.

`all_pass` = H3-1..H3-4. Any failure: report, no re-fit. This is
**exploratory** (the snippet choice follows v2's results); a pass prepares an
off-by-default design and still needs a holdout; nothing is promoted and
windows remain OFF. The W4 money holdout stays independent.

## 4. Execution protocol

Harness `eval/snippet_window_v3.py`, outputs
`eval/results/snippet_window_v3/{report.json,report.md}`,
`tests/test_snippet_window_v3.py` (recorded report + the deterministic dry
check), proof regenerated, execution record appended, committed.

## Execution record (2026-09-22)

180 calls (30 cases x 2 arms x 3 runs), 0 infrastructure failures.

| arm | mean coverage | undue/case |
|---|---:|---:|
| S-head | 0.534 | 0.067 |
| **S-query** | **0.705** | **0.033** |

- **u3a-17 M0043 hits: S-head 0/3, S-query 3/3** - the target is fully
  recovered.
- Input-snippet precheck (deterministic, informational): for u3a-17 the
  S-head snippet contains 0 of the required gold phrases, S-query contains 1;
  20 phrase-gold rows reported overall.

Gates **H3-1..H3-4 all true**; `all_pass` true. Findings:

- **Both axes improved together**: question-windowed snippets raised mean
  annotation coverage 0.534 -> 0.705 while **halving** undue annotations
  (0.067 -> 0.033 per case). Offering candidates AND showing the
  question-relevant text window is what the annotation step needed.
- The u3a-17 class is now mechanically explained end to end: candidate rank 1
  (M0043) -> not annotated with head snippets -> annotated 3/3 once its
  question-relevant window (containing "over a year") is shown.
- This is **exploratory** (the snippet strategy follows v2's findings): a
  holdout with new cases is required before any design claim. The combined
  **union + query-window** design is now the lab's best candidate for the
  annotation interface; promotion to product remains out of scope and
  windows stay OFF. The W4 money holdout remains independent.
