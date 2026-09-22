# Two-tier retrieval v1 - pre-registration

Status: **frozen before execution**. Date: 2026-09-22.

Everything in this document is fixed before the primary run; results are
appended afterwards as an execution record. No threshold, arm or metric may be
changed after the run, and no re-fit of the near-tie factor is allowed.

## 1. Motivation and hypothesis

The closed lifecycle line proved three things: (i) admissions shrink the
consultable set with better promotion precision; (ii) the event-log retriever
finds every reconstructable false discard at rank 1 (4/4); (iii) the bottleneck
is deciding **when** to search, and a rigid cross-corpus score threshold is
fragile (P20 missed at ratio 1.242 against the frozen 1.25).

Hypothesis: searching the promoted set **and** a cheap lexical index of the
full non-rejected record log on every recall, combined in one ranking scale
with one evidence budget, recovers all reconstructable occurrences without
materially degrading precision or exceeding the single-budget delivery cost.
The classification layer then only removes noise (rejects); it never decides
what is worth searching.

## 2. Frozen substrate

- Fixture `eval/fixtures/lifecycle_v1` (sha `e1021c20...`, 32 records, 20
  probes, 17 required sets, 21 required occurrences); gold read only after each
  probe's retrieval.
- Projection `eval/results/lifecycle_v1_report/projection` (classes: 14
  semantic + 3 episodic = 17 promoted; 12 event_only; 3 reject).
- Product BM25 (`memory_machine.retrieval.bm25`, k1=1.5, b=0.75) and product
  tokenizer; `top_k=5`; candidacy margin 0.50 x best (frozen in v3).
- Same cutoff discipline as v1-v4: only records with `seq < after_seq`.
- No LLM calls anywhere in this experiment.

## 3. Arms (one deterministic pass each over the 20 probes)

| arm | indexes searched | candidates | role |
|---|---|---|---|
| **T2-A `promote_only`** | promoted (17) | top-5 + margin | small-memory reference |
| **T2-B `trigger_v4b`** | promoted + event_only on trigger | v4-B delivered set | trigger reference |
| **T2-C `two_tier_combined`** | single index over promoted ∪ event_only (29) | top-5 + margin | **PRIMARY** |
| **T2-CRRF `two_tier_fusion`** | promoted (17) and event_only (12) separately | reciprocal-rank fusion (k=60), top-5 with fused margin 0.5 x best | fusion variant |
| **T2-U `unfiltered`** | all 32 records | top-5 + margin | current lexical reach (upper reference) |

T2-C is a single index with correct corpus statistics, so no cross-corpus score
comparison exists anywhere in the primary arm. T2-CRRF is the only arm that
fuses ranks from two indexes; its margin is applied to the fused score exactly
as declared. T2-B re-executes the frozen v4-B logic, not a re-implementation.

## 4. Metrics and cost instrumentation

Per arm:

- **availability**: combined recall over the 21 required occurrences (required
  memories available in delivered candidates), plus per-probe failure detail.
- **precision@k** over all delivered candidates.
- **delivery budget**: delivered candidates per probe, delivered characters per
  probe (mean and total).
- **index stats**: records indexed and total text bytes per index; cold build
  time (informational, one measurement).
- **latency**: per probe, after 10 warmup repetitions, 100 timed repetitions of
  the full retrieval (tokenize, score, sort, margin); report p50 and p95 in ms
  pooled over probes. Machine-local and indicative only - not a gate.
- **calls**: added LLM calls = 0 by construction (reported, not gated).
- **determinism**: two consecutive runs must produce byte-identical reports
  excluding the timing section.

## 5. Gates (primary T2-C; all required)

- **H2T-1 availability = 1.000 (21/21)** and strictly greater than T2-B
  (0.952). Fixing the P20-class miss is the point of the experiment.
- **H2T-2 precision@k >= 0.80**.
- **H2T-3 delivery budget**: mean delivered characters <= 1.25 x T2-A's mean.
- **H2T-4 no regression vs unfiltered**: precision(T2-C) >= precision(T2-U) -
  0.05 (rejecting 3 records must not hurt).
- **H2T-5 determinism**: the two runs are identical outside timing.

`all_pass` requires all five.

## 6. Expected readings (declared, not gates)

T2-A 0.952 / 1.000; T2-B 0.952 / 1.000; T2-C 1.000 availability with precision
~0.85-0.95; T2-U availability 1.000 with precision at or slightly below T2-C;
latency figures in the low milliseconds for 29-32 records. These expectations
are recorded here so the execution record cannot tell a post-hoc story.

## 7. Stop rules

- Any gate fail: line remains shadow-only; report the failure, change nothing,
  re-fit nothing. If H2T-1 fails, the trigger was not the whole bottleneck -
  stop and re-audit before any new arm.
- If H2T-1 passes but H2T-2 fails (<0.80), the noise of unconditional search is
  material at top-5; the next hypothesis must bound **candidacy/delivery**, not
  reintroduce a trigger.
- If all gates pass: the next step is a separate pre-registration for
  **product-side shadow instrumentation** of a cheap index on real tapes
  (growth, latency, candidate quality). No product default changes here.

## 8. Non-goals

No LLM or agent calls, no promotion, no changes to tape/defaults/classifier,
no persisted indexes, no cross-corpus score thresholds. T2-CRRF is explicitly
not the primary arm; if it disagrees with T2-C it does not change the verdict.

## 9. Execution protocol

Harness `eval/two_tier_retrieval_v1.py`, outputs
`eval/results/two_tier_v1/report.json` and `report.md`, structural test
`tests/test_two_tier_retrieval_v1.py`, conformance proof regenerated, one
primary run plus the determinism rerun, all committed together with this
document's execution record appended.
