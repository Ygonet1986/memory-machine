# agent-index-v1 — pre-registration (metadata routing vs all vs union)

Status: **frozen before execution**. Date: 2026-09-23. Track: synthetic lab.
Approved plan (owner): reuse the 30 frozen cases, **K=2 artificial partitions
per case**, metadata-only arm consults **top-1**, and the post-routing
pipeline has **no LLM annotator agents** (window + budget selection +
answerer only).

Owner rules frozen here: (1) every digest entry points to its source records
with dates and confidence; (2) direct lexical search on the tape remains an
independent path; (3) the index chooses **who to consult** - the pipeline
still chooses the passage per question under the budget.

**Declared scope limit (must appear in the report)**: K=2 artificial
partitions per case test the **routing mechanism**, not call savings on a
real tape.

## 1. Substrate

- 30 frozen cases (u3a/u3b; fixture `composition_u4`; snapshots
  `eval/graph_out/u_diag_longmemeval_*.jsonl`, not versioned - skip if
  absent).
- Per case: the fixture records are split into **K=2 partitions** by
  `created_at` (first half / second half; ties by id).
- **Digest** per partition: up to 12 top terms by TF-IDF across the case's
  partitions, plus capitalized entities and date tokens; every entry carries
  provenance: source record ids, dates, confidence (idf rounded to 4).
- **Planted omissions verified at generation**: for each case compute
  whether the digest top-1 partition misses required records (`A1_miss`) and
  whether the union recovers them (`A2_recover`). Counts recorded; at least
  3 miss cases are required for the answer gate (else report and stop).

## 2. Arms (routing)

- **A0** all partitions (baseline).
- **A1** digest top-1 (score = sum of the question tokens' confidences in
  the digest; ties by partition index).
- **A2** A1 ∪ the partition holding the lexical top-1 record (product BM25
  over the case's records).

Routing coverage = required records hosted by the consulted partitions.

## 3. Post-routing pipeline (frozen, no annotator LLM)

Candidates = records of the consulted partitions, BM25-ranked by the
question, top-5; each rendered as its **question-windowed 400-char snippet**
(`fact_window`); the answerer receives the concatenated snippets (budget
respected by construction) with the same answerer/judge as the line.

## 4. Metrics and gates

- **G1** no case lost: routing coverage(A2) == coverage(A0).
- **G2** advantage: coverage(A2) > coverage(A1) (the planted miss cases).
- **G3** calls: consulted partitions total(A2) < total(A0).
- **G4** answers: 4 declared cases (first 3 `A1_miss` cases by (block,case)
  + first case where A1 hits as control) x 3 arms x N=3 x 2 calls = **72
  calls cap**: score(A2) >= score(A0) - 0.05; A1 reported.
- **G5** routing determinism; **G6** infra failures <= 20%.

`all_pass` = G1-G6. Lab-only: nothing promoted; windows OFF;
`admission-shadow-v2` untouched. K=2-partition scope limit restated in the
execution record.

## 5. Execution protocol

Harness `eval/agent_index_v1.py` (`--skip-llm` for routing only); fixture
`eval/fixtures/agent_index_v1/` from `eval/gen_agent_partitions_v1.py`;
outputs `eval/results/agent_index_v1/{report.json,report.md}`;
`tests/test_agent_index_v1.py`; proof regenerated; execution record
appended; committed.

## Amendment 1 (2026-09-23, pre-execution; disclosed)

The approved plan defines A2 as the union with the partitions hosting the
**lexical top-k** records (rule 2); this pre-registration had narrowed it to
top-1 by mistake. Generator design check (no outcomes recorded yet): with
top-1, the single lexical pick coincides with the digest pick in most cases
and the union recovers required records in only **8/27** cases. Amendment:
A2 = digest top-1 ∪ **partitions hosting the lexical top-3 records**
(positive BM25 scores, deterministic order). Everything else unchanged.

## Execution record (2026-09-23)

Pre-recorded pass disclosed: the first harness pass failed all answer calls
with a swallowed `KeyError` (the partitions fixture has no `gold` field);
fixed to read the gold from the source fixture before the recorded run. No
outcomes were recorded from that pass.

Routing (deterministic, 27 cases):

| arm | routing coverage | consulted partitions |
|---|---:|---:|
| A0 all | 1.0000 | 54 |
| A1 digest top-1 | **0.5321** | 27 |
| A2 union (top-3 lexical) | 1.0000 | **54** |

Answers (4 declared cases x 3 arms x N=3, 72 calls, 0 failures):
A0 **0.0**, A1 **0.0**, A2 **0.125**.

Gates: G1 **true** (no case lost); G2 **true** (A2 1.0000 > A1 0.5321);
**G3 false** (A2 consults 54 partitions, same as A0); G4 true (A2 >= A0 -
0.05, trivially); G5 true; G6 true; `all_pass` false.

Findings:

- **The union mechanism preserves routing coverage** where the metadata-only
  arm loses over half of it (A1 0.5321 -> A2 1.0000), confirming rule 2: the
  direct lexical path must remain an independent entry.
- **No call savings are demonstrated with K=2**: with two partitions per
  case, the union (digest top-1 + top-3 lexical partitions) covers both
  partitions in practice, so A2 = A0 in consulted partitions. This is the
  declared scope limit: **K=2 artificial partitions test the routing
  mechanism, not call savings on a real tape.**
- **The answer gate is uninformative at this floor**: all arms answer near
  zero on the four sampled cases with 400-char snippets (derived/computed
  answers need more context than this pipeline provides); G4 passes only
  because A2 >= A0. No answer-level claim is made.
- Nothing is promoted; windows OFF; `admission-shadow-v2` untouched. A
  real-tape call-savings claim would need partitions matching real agent
  groups and the dual-track evaluation.
