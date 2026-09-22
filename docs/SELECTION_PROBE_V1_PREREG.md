# selection-probe-v1 — pre-registration (why required records are not annotated)

Status: **frozen before execution**. Date: 2026-09-22. Track: synthetic lab.

After the u3a-17 correction (M0341): M0043 was never annotated by the frozen
agents; the case is a recall/selection miss. This deterministic probe
characterizes that class across the frozen blocks: for every case where a
required record was not annotated, is the record **lexically retrievable**
from the question, and does it share views with the annotated records?

## 1. Scope and data (frozen, no LLM)

- Snapshots: `eval/graph_out/u_diag_longmemeval_{u3a,u3b}.jsonl` (frozen
  agent ids per case; not versioned - the probe skips if absent).
- Fixture: `eval/fixtures/composition_u4` records (full texts, views).
- Prevalence already observed (metadata, before freezing): 8/30 cases have
  at least one required record missing from `agent_ids` (2 u3a, 6 u3b).

## 2. Per missing record

- **lexical rank**: product BM25 rank of the record among the case's records
  for the question (`bm25` over `summary + " " + why`), 1-based; 0 = unranked
  (score 0).
- **lexical overlap**: fraction of question tokens (product tokenizer) in
  the record text.
- **view overlap**: does the record share at least one view with any
  annotated record of the case (`views` lists in the fixture)?

Classification (declared):

- **`lexically_retrievable_miss`**: rank in 1..5 - the record was within the
  product's lexical top-5 and the miss is **selection/annotation**, not
  lexical reach;
- **`lexical_gap`**: rank > 5 or unranked - the record was not within the
  lexical top-5 (candidate-generation boundary, item-1 territory);
- plus flag **`view_disjoint`** when view overlap is false.

## 3. Gates

- **S1** every missing record is classified; counts sum consistently.
- **S2** determinism; **S3** the report lists every affected case with the
  u3a-17 row visible as the reference instance.

`all_pass` = S1-S3. Diagnostic only: no rule, no policy change, windows OFF.

## 4. Execution protocol

Harness `eval/selection_probe_v1.py`, outputs
`eval/results/selection_probe_v1/{report.json,report.md}`,
`tests/test_selection_probe_v1.py`, proof regenerated, execution record
appended, committed.

## Execution record (2026-09-22)

Deterministic; gates S1-S3 **all true**; `all_pass` true.

- snapshots: 30 cases; **affected: 8** (u3a-17/18; u3b-29/32/33/34/38/41);
- **missing records: 11**; classes: **10 `lexically_retrievable_miss`**, 1
  `lexical_gap`; **`view_disjoint`: 0**.

| case | missing | lexical rank | q-token overlap |
|---|---|---:|---:|
| **u3a-17** | **M0043** | **1** | **0.80** |
| u3a-18 | M0022 | 2 | 0.33 |
| u3a-18 | M0018 | unranked | 0.00 |
| u3b-29 | M0005 | 3 | 0.44 |
| u3b-32 | M0048 | 1 | 0.75 |
| u3b-33 | M0031 / M0046 | 2 / 3 | 0.29 |
| u3b-34 | M0010 / M0036 | 5 / 4 | 0.29 / 0.14 |
| u3b-38 | M0044 | 2 | 0.40 |
| u3b-41 | M0010 | 1 | 0.67 |

Findings:

- **The selection misses are not lexical-reach problems**: 10 of the 11
  missing required records sit in the product's lexical **top-5** for the
  question (M0043 is **rank 1** with 0.80 question-token overlap). Candidate
  generation was not the bottleneck.
- **They are not view-routing problems either**: every missing record shares
  at least one view with the annotated records (`view_disjoint = 0`).
- **The failure localizes to the agent annotation step**: candidates that
  are lexically obvious and view-aligned were not annotated. This is the
  first diagnostic class ("the ranking did not present the memory") occurring
  *inside* the recall stage, with a recurring pattern - 8/30 cases, 10/11
  records retrievable.
- The single true lexical gap (u3a-18/M0018, unranked, no overlap) remains
  candidate-generation territory (item-1) and is recorded separately.

Named next hypotheses (no changes made; windows OFF):

1. **Annotation reliability**: measure agent annotation recall against a
   deterministic lexical-top-k reference on these 30 cases (does a cheap
   candidate list need to be offered alongside the views?).
2. **Recall-time candidate augmentation** (the two-tier idea re-surfacing at
   the agent boundary): always offer the lexical top-k to the annotation
   stage; test on the frozen cases with repeated runs.
   The money holdout (W4) remains independent and pending.
