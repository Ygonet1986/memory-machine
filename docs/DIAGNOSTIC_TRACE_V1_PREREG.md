# diagnostic-trace-v1 — item 3 pre-registration (four-stage per-case trace)

Status: **frozen before execution**. Date: 2026-09-22. Track: synthetic lab.
Follows `delivery-combined-v1` (M0326): W3 won delivery, failed B4, and
u3b-27 proved N=1 answer noise on byte-identical contexts. This experiment
localizes where each tracked case loses the needed fact, with **N=3 runs on
the same frozen payloads**, never inferring the stage from the judge alone.

## 1. Cases and arms

Cases: **u3a-12** (case 0, `16GB`, the historical arithmetic anchor),
**u3a-19** (`$200`) and **u3a-22** (`two weeks`) - the two real numeric
downgrades of W3 vs W1 - and **u3b-27** (non-numeric, W1/W3 contexts
byte-identical; noise control). Arms: **W0, W1, W3** (frozen contexts from
`delivery_combined_v1`).

## 2. Four independent checks (one row per case x arm x run)

| stage | verifiable question | method |
|---|---|---|
| **Origin** | does the needed fact exist in the material the memory came from? | the frozen record full text (`summary + why`) of the required ids, plus provenance (`id`, `created_at`, `source` non-empty). Raw LongMemEval sessions are not versioned in the repo; the record text is the highest available origin and this limitation is declared. |
| **Ingestion** | was the fact preserved with value and provenance? | gold atoms (`item_fact_atoms`) present in the required records' full text; provenance fields recorded. |
| **Delivery** | did it arrive whole in the payload the answerer received? | gold atoms present in the required ids' spans of the exact arm context; per-stage missing lists. |
| **Answer** | did the answerer use the fact and reach the correct conclusion? | N=3 runs per cell with the same answerer (frozen prompt, temperature 0) on the SAME frozen context; frozen blind judge v1; plus a deterministic usage flag: the gold's first numeric/entity value appears in the answer (norm). |

Rows are written to JSONL with the original excerpt, the ingested record
excerpt, the exact payload excerpt, the answer and the verdict per run.

## 3. Verification targets (diagnostic, not promotion gates)

- **T1** every row is complete and stage-consistent: no row claims the answer
  used a value that delivery did not contain (no impossible rows).
- **T2** for u3a-19 and u3a-22: the loss stage is named per arm (delivery
  missing vs delivered-but-unused/incorrect).
- **T3** case 0 (u3a-12): delivery present in all arms (recorded fact) and
  answer outcomes are stable or the instability is measured (N=3).
- **T4** u3b-27 control: W1 and W3 contexts identical; the verdict
  distribution across runs quantifies the answer noise floor on one context.
- **T5** determinism of the three deterministic stages; infrastructure
  failures disclosed; > 20% failures makes the answer stage
  INCONCLUSIVE_INFRASTRUCTURE.

## 4. Expected readings (declared)

The two numeric downgrades are expected to be **answer-level** (fact present
in delivery, but the computed conclusion wrong or unstable), consistent with
the case-0 reinterpretation; the control is expected to show verdict
variation across identical contexts (noise floor > 0).

## 5. Stop rules

Diagnostic only: nothing is promoted or re-fitted regardless of outcome. The
named stage decides the next item: ingestion/temporal delivery losses ->
item 1; delivered-but-unused -> answerer work; cross-turn retrieval ->
item 4; cost comparison waits for enough cases (item 5). Answer-stage rows
are N=3 with the cost cap (4 cases x 3 arms x 3 runs x 2 calls = 72 calls).

## 6. Execution protocol

Harness `eval/diagnostic_trace_v1.py` (`--skip-llm` for the deterministic
stages only), outputs `eval/results/diagnostic_trace_v1/{trace.jsonl,
report.json,report.md}`, `tests/test_diagnostic_trace_v1.py`, proof
regenerated, one run, execution record appended, all committed.

## Execution record (2026-09-22)

One run; deterministic stages plus the answer stage (72 LLM calls = 4 cases x
3 arms x 3 runs x 2 calls, 0 infra failures, judge v1, temperature 0).
`T1 stage consistency: true`.

| case | arm | origin | ingestion | delivery | verdicts (N=3) | value used |
|---|---|---|---|---|---|---|
| u3a-12 | W0/W1/W3 | ok | ok | ok | correct x3 in all arms | 3/3 |
| u3a-19 | W0 | ok | ok | **MISS number:200** | incorrect/partial/incorrect | 0/3 |
| u3a-19 | W1 | ok | ok | **MISS number:200** | incorrect x3 | 0/3 |
| u3a-19 | W3 | ok | ok | **MISS number:200** | incorrect/incorrect/partial | 0/3 |
| u3a-22 | W0/W1 | ok | ok | ok (vacuous, see below) | correct x3 | n/a |
| u3a-22 | W3 | ok | ok | ok (vacuous) | **incorrect x3** | n/a |
| u3b-27 | W1 | ok | ok | ok | correct/incorrect/correct | 2/3 |

Stage verdicts:

- **u3a-19 is a delivery/truncation loss, policy-independent**: the required
  record is in the payload in every arm, but the delivered span is cut
  before `$200` (the first/last numeric anchors do not reach it). Origin and
  ingestion are clean. -> item 1/2 boundary (numeric-fact delivery), not a
  policy regression.
- **u3a-22 is a real W3 regression at the answer level**: W0 and W1 answer
  `two weeks` correctly 3/3; W3 answers incorrectly 3/3 (stable, not noise).
  The deterministic delivery check is **vacuous** for this case: the gold
  `two weeks` yields no numeric/date/entity atoms, so the window can lose
  the qualitative temporal fact unobserved by the metric. -> the anchor
  policy can destroy short temporal facts; the delivery metric needs a
  phrase-level check for non-numeric temporal answers.
- **u3b-27 confirms the noise floor**: identical W1/W3 contexts flipped
  once in three runs - a single verdict difference is not attributable.
- **Case 0 (u3a-12) is stable**: 3/3 correct with the value used in every
  arm; the historical anchor regression does not reproduce at any stage.

T2-T4 satisfied as above; T5 determinism of the three deterministic stages
(the JSONL rows are regenerated byte-identically with `--skip-llm`).

Nothing promoted or re-fitted; windows remain OFF. Named next work: (a) a
phrase-level delivery metric for temporal answers (u3a-22 class), (b) a
numeric-fact inclusion rule that reaches mid-text values (u3a-19 class),
before any further W3 iteration.
