# gap-recall-v1 — pre-registration (bounded gap-directed second search)

Status: **frozen before execution**. Date: 2026-09-23. Track: synthetic lab.

New hypothesis proposed by the user (M0372): the first answer may be a
provisional hypothesis followed by a second search **directed by what is
still uncertain** - a missing value, a missing date, a missing second
component - with a bounded number of passes and an audit log so that, if the
answer changes, one can see exactly **which new evidence changed it**. The
second search must be gap-directed, not "think again".

## 1. Fixture (new; one-shot; design verified at generation)

`eval/fixtures/gap_recall_v1/` (`gen_gap_recall_v1.py`, 15 cases, hash
`4c2d915ec5bb258ef649c639d5f3ccdc91693c217b0da05a9161fd1e2506e33c`).

- **12 gap cases** (4 numeral, 4 date, 4 two-component): the demanded fact
  lives in a **distinct record** that pass 1 never consults; six
  numeral-free distractors outrank it lexically.
- **3 easy controls** whose fact is already in the head record.
- Design checks (product functions): pass1 incomplete **12/12**; gap-recall
  complete **12/12** with exactly one directed query; equal-budget breadth
  control (k=4) incomplete **12/12**; oracle complete **12/12**; controls
  complete at pass 1 with **zero** directed queries.
- Scope: v1 covers gaps **in distinct records** (the "another memory exists"
  class). Gaps hidden *inside* the same record by the window are prior work
  (snippet-window/union) and stay out.

## 2. Mechanism (deterministic, no LLM)

- **Pass 1** (G0): lexical top-3 records of the question (frozen BM25
  `memory_machine.retrieval.rank`), each delivered as summary +
  `fact_window(why, question, room)`, room = 3600 - len(summary) - 1.
- **Gap detector** (declared): question cues demand expected facts - "how
  much/amount/cost/spend/total/price" -> one numeral ($ pattern), plus "and
  the" -> **two** numerals; "when/date" -> one ISO date. A gap is an
  expectation not satisfied by the delivered text.
- **Directed queries** (<=2, one per demanded type): numeral ->
  `entity_terms + " invoice amount"`; date -> `entity_terms + " payment
  date"`. `entity_terms` = tokenized question minus stopwords and cue words.
- **Pass 2**: for the first gap, the best-scoring record not yet consulted
  (BM25 over full record text) is delivered with the same window, bounded by
  the same allocation. Stop when no gaps remain or when 2 queries are used.
  No fallback into already-consulted records in v1.
- **Audit log**: per directed query - gap descriptor, query, newly consulted
  record ids, complete-before/after.

## 3. Arms

- **G0** pass 1 only. **G1** gap-recall (candidate). **G2** equal-budget
  breadth control: pass 1 with k=4 (exactly one extra record, next-ranked by
  the *same* question - the "look more without direction" control). **G3**
  oracle: head + the fixture's missing record (diagnostic upper bound; not
  promotable).

## 4. Gates

- **R1 no-loss**: every case complete under G0 stays complete under G1.
- **R2 recovery**: complete(G1) > complete(G0).
- **R3 direction**: complete(G1) > complete(G2) (direction beats equal-budget
  breadth).
- **R4 budget**: zero directed queries on the 3 controls; <=2 queries per
  case; total directed queries <= number of cases (mean extra <= 1.0).
- **R5 determinism**: two runs identical.
- **R6 audit**: every recovered case has an audit entry crossing
  incomplete->complete with the new record id; recovered > 0.

`all_pass` = R1-R6. A failure is recorded as is; no rule re-adjustment after
seeing results (no re-fit), consistent with M0150/M0049.

## 5. Reporting

The record must separate **delivery of the missing facts** (complete/partial
per arm) from **answer correctness** - the latter is **not** tested here (no
LLM in v1). If R1-R6 pass, a separate pre-execution addendum (N=3, same
answerer + blind judge, calls counted) may test whether the delivery gain
reaches the answers; that addendum is presented and approved **before**
running.

## 6. Exploratory (declared, not gated)

The **segment search** variant of the directed query is read on the two
frozen money fixtures (`money_holdout_v2`, `multi_component_holdout_v1`):
W1 window both-components vs W1 + best numeral-bearing sentence matching the
directed query. This exercises the *same-record, window-hid-the-fact* class
that the main test excludes; it is exploratory only and cannot promote
anything.

## 7. Scope and non-negotiables

Lab-only; nothing promoted; **windows OFF**; admission-shadow-v2, the paused
shadow-v1 and the pre-registered track S are **untouched**; no product
defaults, schema, candidate or thresholds are modified; dual-track holds
(real claims need a new real window from zero). Execution protocol: harness
`eval/gap_recall_v1.py`, outputs `eval/results/gap_recall_v1/`, tests
`tests/test_gap_recall_v1.py`, proof regenerated, execution record appended,
committed via PR with frozen-before-results history.
