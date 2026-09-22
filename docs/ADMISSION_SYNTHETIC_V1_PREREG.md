# admission-synthetic-v1 — pre-registration (frozen before execution)

Status: **frozen before execution**. Date: 2026-09-22.

Controlled evaluation of the **evidence admission** step with relevance known
by construction. It replaces the paused real-tape collection
(`docs/ADMISSION_SHADOW_PAUSE.md`) for development speed; synthetic success is
**not** evidence of real-world performance and must never be cited as such.

## 1. Substrate (frozen)

- Fixture `eval/fixtures/admission_synthetic_v1/` — 100 cases (10 scenarios x
  10), 1,020 records, 100 gold occurrences, 10 abstain cases.
- **Sample hash (sha256 of `cases.jsonl`):
  `f61262d3bc3c8999ba41680792db18f17955021a9aa2f08277da87ea4506bb83`**
- Generator `eval/gen_admission_synthetic_v1.py` (version 2, no seed, no LLM,
  templates only) is frozen; `eval/validate_admission_synthetic_v1.py` proves
  the committed sample is byte-identical to a fresh regeneration and checks
  the schema (gold present in records, abstain/deliver consistency, unique
  ids, 10 cases per scenario).
- Retrieval per case: product BM25 (`memory_machine.retrieval.bm25`, k1=1.5,
  b=0.75) over the record texts (`summary + " " + why`), top-5 positive
  scores, ties broken by record order. No LLM, no agents, no graph. The case
  is an isolated mini-tape; every policy sees exactly the same candidates.

## 2. Scenarios and expectation

| # | scenario | situation | gold |
|---|---|---|---|
| 1 | `easy_single` | one clearly correct memory among unrelated distractors | the one |
| 2 | `near_duplicate` | similar memories, only one matches the endpoint | the exact match |
| 3 | `corrected` | an old decision later corrected | the correction only |
| 4 | `shared_subject` | same topic across two projects | the requested project's record |
| 5 | `short_ambiguous` | question "And the cache?" | the most recent cache decision |
| 6 | `long_specific` | long question with several constraints | the fully matching record |
| 7 | `no_answer` | topic absent from the mini-tape | **abstain** (deliver nothing) |
| 8 | `old_vs_recent` | old recommendation vs a newer one | the newer one |
| 9 | `multi_memory` | answer needs two records (pool + timeout) | both |
| 10 | `distractor_volume` | 41 distractors sharing generic vocabulary | the unique match |

Memory types in the sample: `decision`, `lesson`, `preference`, `bugfix` (none
generated), `build`, plus event-like records; question type hints are textual
(decided/decision, lesson/learned, preference/prefers, shipped/version).

## 3. Policies (all deterministic, same candidates, no LLM)

- **P0 `top1`** — deliver candidate 1.
- **P1 `top5_margin50`** — deliver candidates with score >= 0.50 x best.
- **P2 `margin90`** — deliver candidates with score >= 0.90 x best.
- **P3 `multisignal`** *(primary)* — per candidate:
  - `base = score / best_score`
  - `rare` = IDF-weighted question-token coverage (smoothed IDF over the case
    records; 0 when the question has no tokens)
  - `entity` = 1 if a version/file/id token appears in both question and
    record text, else 0
  - `temporal` = 1 if the record is the newest among candidates with
    `rare > 0`, else 0
  - `type_fit` = 1 when the question's type hint matches the record type,
    0.25 when a hint is present and differs, 0.5 when there is no hint
  - `gain = 0.35*base + 0.25*rare + 0.15*entity + 0.15*temporal + 0.10*type_fit`
  - selection in `gain` order (ties: `base`, then candidate order); a
    candidate with token Jaccard > 0.60 against the already-selected union
    gets `gain *= (1 - jaccard)`; it is delivered when cumulative characters
    (`len(summary)+len(why)+8`) stay <= 4000 **and** `gain >= 0.50` **and**
    `rare >= 0.30`.

P3's floors are the declared answer to the absence-of-answer scenario: relative
ranking alone cannot abstain.

## 4. Metrics

Per policy: **availability** (delivered gold / 100), **precision** (delivered
gold / delivered), **mean delivered characters**, **abstention rate** on
scenario 7, and per-scenario availability. Deliveries are compared against the
gold ids; an abstain case is scored only through the abstention metric.

## 5. Gates (P3; all required)

- **G1** availability >= 0.90.
- **G2** precision >= 0.70.
- **G3** dual frontier: availability(P3) > availability(P2) **and**
  precision(P3) > precision(P1).
- **G4** abstention: scenario 7 no-delivery rate >= 0.80.
- **G5** every deliver scenario availability >= 0.70.
- **G6** determinism: two runs byte-identical outside timing.

## 6. Expected readings (declared, not gates)

P1 high availability / low precision (near-duplicates and volume); P2 high
precision / low availability (rare seconds and corrections dropped); P3 wins
on scenarios 2, 3, 5, 8, 9, 10 and abstains on 7; absolute levels uncertain.
These expectations are recorded so the execution record cannot tell a
post-hoc story.

## 7. Stop rules

- Any gate fail: report, change nothing, re-fit nothing. If G1/G5 fail, P3's
  floors are the suspect and the next hypothesis must target detection, not
  thresholds. If G4 fails, the absolute floor is the failure and the next
  hypothesis must make abstention a first-class decision.
- All gates pass: the phase authorizes a **product-side shadow
  pre-registration** (real tapes, cost/latency) - never promotion; promotion
  still requires availability and precision together under the 4000-char
  budget on real data.
- No threshold, weight or scenario may be changed after this document is
  frozen.

## 8. Threats and limits

- Templates create shared tokens by design; results measure mechanism
  behavior on controlled distributions, not natural language variety.
- BM25-only retrieval is a simplification of the full product recall (agents,
  views, graph); synthetic results cannot be transferred to the product
  without the shadow phase.
- P3's weights and floors are round, pre-declared and arbitrary; the phase
  tests whether the multisignal direction beats the score-margin family, not
  whether these exact constants are optimal.
- Single fixture; no seed variance by construction.

## 9. Execution protocol

Harness `eval/admission_synthetic_v1.py`, outputs
`eval/results/admission_synthetic_v1/report.json` and `report.md`, structural
test `tests/test_admission_synthetic_v1.py`, proof regenerated, one primary
run plus the determinism rerun, execution record appended to this document,
all committed together.


## Execution record (2026-09-22)

Pre-run correction, before any committed run: generator v1 mapped scenario-1
gold to a stale record id (ids are assigned by renumbering after the builders
run). A dry run detected it; generator v2 resolves gold from the renumbered
records. No policy, weight, threshold or scenario changed; the defective
sample hash `9d321d6a...` was discarded and its aggregates are not part of the
record.

Recorded run: sample hash `f61262d3...`, report at
`eval/results/admission_synthetic_v1/report.json` (determinism rerun
identical).

| policy | availability | precision | delivered | mean chars | abstention (S7) |
|---|---:|---:|---:|---:|---:|
| P0 top1 | 0.500 | 0.500 | 100 | 80 | 0.000 |
| P1 margin50 | 0.900 | 0.310 | 290 | 204 | 0.000 |
| P2 margin90 | 0.600 | 0.429 | 140 | 107 | 0.000 |
| **P3 multisignal** | **0.700** | **0.500** | 140 | 108 | **1.000** |

Gates: G1 **false** (0.70 < 0.90); G2 **false** (0.50 < 0.70); G3 **true**
(0.70 > 0.60 and 0.50 > 0.31); G4 **true**; G5 **false**; G6 true;
`all_pass` **false**.

Findings:

- **Direction confirmed (G3).** P3 beats both references on both axes at once
  - the result the two-tier closure could not reach with score margins.
- **Absolute failure is decomposed, and mostly ranking, not admission.**
  1. `corrected` is 0.00 for every policy: lexical ranking prefers the
     superseded record (it matches more query tokens); no admission rule can
     fix a ranking miss. Supersession needs the correction signal family
     (lifecycle classification) or semantics - admission alone cannot do it.
  2. `near_duplicate`: the two endpoint records tie at rank 1-2; P2 keeps the
     pair, P3's declared redundancy penalty (> 0.60 Jaccard) drops the tied
     correct one, and the entity pattern does not cover API paths, so the tie
     is unresolvable by declared signals.
  3. `multi_memory`: the required second record has `gain = 0.469` < the
     declared 0.50 floor (`rare = 0.487` passes), so P3 keeps only one of the
     two while P1 keeps both. The gain floor - not redundancy - costs it.
  4. P3 wins wherever the declared signals apply: recency (`old_vs_recent`,
     `short_ambiguous` 1.00 vs 0.00 for P2), volume/easy/long/shared perfect,
     and abstention 1.000 (G4).
- Declared expectations missed: predicted P3 wins on scenarios 2, 3 and 9
  (2 lost to the redundancy rule, 3 to ranking, 9 to the gain floor) -
  recorded as misses.

Stop rules applied: G1/G5 failed, so nothing is promoted and nothing is
re-fitted. The named gaps (supersession detection, entity coverage for paths,
gain floor vs multi-memory) plus the standing finding that **admission cannot
compensate for ranking** define the next pre-registered hypothesis. Synthetic
results are not evidence of real-world performance.
