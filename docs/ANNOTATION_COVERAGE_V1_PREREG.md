# annotation-coverage-v1 — pre-registration (annotation vs lexical top-k)

Status: **frozen before execution**. Date: 2026-09-22. Track: synthetic lab.

Hypothesis 1 as a **measurement** (owner direction after `selection-probe-v1`,
M0343): across the 30 frozen cases, compare the annotated records with a
deterministic lexical top-k and measure how many **required** records each
list covers. This quantifies the candidate for hypothesis 2 (offering the
lexical top-k alongside the views in repeated runs) without running any LLM
yet. The W4 money holdout stays separate.

## 1. Data and lists (deterministic)

- Snapshots `eval/graph_out/u_diag_longmemeval_{u3a,u3b}.jsonl` (frozen
  `agent_ids`; not versioned - the probe skips when absent).
- Fixture `eval/fixtures/composition_u4` (record texts; question per case).
- Lists per case, over the case's fixture records, product BM25:
  - **A** = annotated (`agent_ids`);
  - **Lk** = lexical top-k, k in {3, 5, 8, 10} (positive scores);
  - **U5** = A union L5 (hypothesis-2 candidate).

## 2. Metrics (declared)

- **coverage(list)** = |required ∩ list| / |required| (restricted to required
  records present in the fixture; absent ones reported).
- **miss coverage**: of the `selection-probe` missing records, how many each
  Lk covers.
- **undue proxy**: `|(L5 \\ A) \\ required|` - candidates added by the union
  that are not required (per case and total), so hypothesis 2 can be judged
  against an expected noise cost.

## 3. Gates

- **A1** all snapshot cases processed; counts consistent (no double counts);
- **A2** determinism;
- **A3** the u3a-17 row is visible (M0043 covered by L5 at rank 1).

`all_pass` = A1-A3. Measurement only: no policy, no LLM, windows OFF. The
result is the decision input for hypothesis 2 (repeated-run experiment with
the union list), which needs its own pre-registration.

## 4. Execution protocol

Harness `eval/annotation_coverage_v1.py`, outputs
`eval/results/annotation_coverage_v1/{report.json,report.md}`,
`tests/test_annotation_coverage_v1.py`, proof regenerated, execution record
appended, committed.

## Execution record (2026-09-22)

Deterministic; gates A1-A3 **all true**; `all_pass` true.

- 30 cases, **62 required records**; annotated coverage **A = 0.8226**;
  lexical coverage: **L3 = 0.7419, L5 = 0.9355, L8 = 0.9839, L10 = 0.9839**;
  **union U5 = A ∪ L5 = 0.9839**.
- Of the 11 records missed by the annotations, **10 are covered by L5**; the
  single remaining miss is the true lexical gap (u3a-18/M0018).
- **Undue proxy**: the union adds **14 non-required candidates** across the
  30 cases (~0.47 per case).
- Reference row: **u3a-17** - A 0.00, L5 1.00, U5 1.00; missing M0043 covered
  by L5.

Reading (measurement, not policy):

1. **The cheap lexical top-5 already beats the annotations** on required
   coverage (0.9355 vs 0.8226) - the annotation step is where required
   records are lost, and the loss is recoverable deterministically.
2. **The union is the hypothesis-2 candidate**: 0.9839 coverage with a small,
   measurable noise cost (14 slots). Whether the agents, when offered the
   union, annotate the missing records **without** adding undue annotations
   is the open question and needs repeated runs (hypothesis 2, separate
   pre-registration).
3. No policy, no LLM, no change: windows OFF; the W4 money holdout remains
   independent.
