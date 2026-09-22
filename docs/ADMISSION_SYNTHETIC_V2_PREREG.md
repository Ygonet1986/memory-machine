# admission-synthetic-v2 — pre-registration (frozen before execution)

Status: **frozen before execution**. Date: 2026-09-22.

Second controlled round on the **same frozen sample** as v1
(`admission_synthetic_v1`, hash
`f61262d3bc3c8999ba41680792db18f17955021a9aa2f08277da87ea4506bb83`) so every
policy sees identical cases and the references stay comparable. v1's primary
(P3v1) is re-executed from its frozen code as a baseline, not re-implemented.

## 1. What v2 attacks (named v1 causes)

| v1 failure | declared cause | v2 change |
|---|---|---|
| `corrected` 0.00 everywhere | lexical ranking prefers the superseded record; no admission rule can fix a ranking miss | **supersession signal**: correction markers + demotion of older, same-type, overlapping records |
| `near_duplicate` 0.00 (P3) | entity pattern does not cover API paths; the tied correct record is dropped by redundancy | **entity coverage extended to paths/endpoints** (`/v2/orders`, `orders:v2`) |
| `multi_memory` 0.50 (P3) | the required second record falls under the absolute 0.50 gain floor (gain 0.469) | **relative gain floor** (`>= 0.60 x best gain` after demotion); the `rare >= 0.30` floor stays (it is what makes abstention work) |

## 2. P3v2 (primary) — exact declared rule

Per candidate (same inputs as v1):

- `base = score / best_score`
- `rare` = IDF-weighted question-token coverage over the case records
- `entity` = 1 if any entity **or path** token appears in both question and
  record text; patterns: identifiers/versions/file names (as v1) **plus**
  `/segment...` paths and `word:word` key prefixes
- `temporal` = 1 if the record is the newest among candidates with `rare > 0`
- `type_fit` = 1 match / 0.25 mismatch / 0.5 no hint (as v1)
- `correction` = 1 if the lowercased record text contains any marker:
  `correction`, `corrects`, `corrected`, `supersedes`, `superseded`,
  `replaces`, `replaced`, `deprecated`, `obsolete`, `no longer`, `moved to`
- `gain = 0.30*base + 0.20*rare + 0.15*entity + 0.15*temporal
  + 0.10*type_fit + 0.10*correction`

Selection:

1. **Supersession demotion** (before ordering): if any candidate has
   `correction == 1`, then every candidate with `correction == 0`, the same
   record type, an older `created_at`, and at least 2 shared tokens with that
   correction candidate gets `gain *= 0.25`.
2. Order by `gain` desc (ties: `base`, then candidate order).
3. **Redundancy**: token Jaccard > 0.60 against the selected union ->
   `gain *= (1 - jaccard)`.
4. Deliver while cumulative characters (`len(summary)+len(why)+8`) <= 4000
   **and** `rare >= 0.30` **and** `gain >= 0.60 x best_gain` (best_gain =
   maximum gain after demotion, before redundancy).

## 3. Policies compared (same candidates, same cases)

P0 top-1, P1 margin 0.50, P2 margin 0.90 (as v1); **P3v1** re-executed from
the frozen v1 module; **P3v2** primary.

## 4. Metrics

As v1: availability, precision, delivered, mean characters, abstention rate
(S7), per-scenario availability.

## 5. Gates (P3v2; all required)

- **G1** availability >= 0.90.
- **G2** precision >= 0.70.
- **G3** dual frontier: availability(P3v2) > availability(P2) **and**
  precision(P3v2) > precision(P1).
- **G4** abstention rate (S7) >= 0.80.
- **G5** every deliver scenario availability >= 0.70.
- **G6** determinism (two runs byte-identical outside timing).
- **G7** strictly better than P3v1: availability(P3v2) > availability(P3v1)
  **and** precision(P3v2) >= precision(P3v1).

## 6. Expected readings (declared, not gates)

`corrected`, `near_duplicate`, `multi_memory` reach 1.00; `multi_memory` is
the riskiest (a relative floor must keep the second record while `no_answer`
still abstains through `rare`); overall availability ~0.95-1.00; precision
0.55-0.75 (volume and near-duplicate handling improve it, distractors keep it
below 1.00). Recorded so the execution record cannot tell a post-hoc story.

## 7. Stop rules

- Any gate fail: report, change nothing, re-fit nothing. If G1/G5 fail again,
  the residual causes are ranked (ranking misses vs declared-signal gaps) and
  the next hypothesis must name which; if G4 fails, the relative floor must
  not have replaced the `rare` floor as the abstention mechanism.
- All gates pass: authorizes a **product-side shadow pre-registration**
  (real tapes, cost/latency) - never promotion; promotion still requires
  availability and precision together under the 4000-char budget on real
  data. Synthetic results remain non-evidence for real-world performance.

## 8. Threats and limits

Same as v1 (templates, BM25-only, arbitrary but pre-declared constants,
single fixture). Added: v2 constants (marker list, demotion factor 0.25,
relative floor 0.60) were chosen after v1's aggregate findings - that is
allowed (new pre-registration, new hypotheses on old data), but they may
overfit this fixture; the report must state that explicitly.

## 9. Execution protocol

Harness `eval/admission_synthetic_v2.py` (imports the frozen v1 module),
outputs `eval/results/admission_synthetic_v2/report.json` and `report.md`,
structural test `tests/test_admission_synthetic_v2.py`, proof regenerated,
one primary run plus the determinism rerun, execution record appended, all
committed together.


## Execution record (2026-09-22)

Recorded run on the frozen v1 sample (hash `f61262d3...`), report at
`eval/results/admission_synthetic_v2/report.json`; determinism rerun
identical.

| policy | availability | precision | delivered | mean chars | abstention (S7) |
|---|---:|---:|---:|---:|---:|
| P0 top1 | 0.500 | 0.500 | 100 | 80 | 0.000 |
| P1 margin50 | 0.900 | 0.310 | 290 | 204 | 0.000 |
| P2 margin90 | 0.600 | 0.429 | 140 | 107 | 0.000 |
| P3v1 (frozen) | 0.700 | 0.500 | 140 | 108 | 1.000 |
| **P3v2** | **1.000** | **0.455** | 220 | 169 | **1.000** |

Gates: G1 **true**; G2 **false** (0.455 < 0.70); G3 **true** (1.000 > 0.600
and 0.455 > 0.310); G4 **true**; G5 **true**; G6 true; G7 **false**
(precision 0.455 < P3v1 0.500); `all_pass` **false**.

Findings:

- **Every availability gap closed**: `corrected` 0.00 -> 1.00,
  `near_duplicate` 0.00 -> 1.00, `multi_memory` 0.50 -> 1.00. The three v2
  mechanisms worked exactly where designed.
- **The relative floor traded precision for availability**: +80 deliveries
  vs P3v1 (220 vs 140) and precision 0.455, below both the 0.70 gate and the
  v1 level, so G7 fails. Named contributors: `short_ambiguous` admits the
  commodity-token tail (5 deliveries/case, precision 0.200); demoted
  superseded records still pass the relative floor in `corrected`/`long_
  specific`/`shared_subject` (3/case, precision 0.333); `multi_memory` also
  admits extras (precision 0.500). The v1 absolute floor was the precision
  mechanism; v2 replaced it - one failure mode for another, and the joint
  gates are still unmet.
- Declared expectations matched on the three targeted scenarios; precision
  was predicted 0.55-0.75, actual 0.455 - recorded as a miss (the tail was
  underestimated).

Stop rules applied: G2/G7 failed, nothing promoted, nothing re-fitted. The
next pre-registered hypothesis must **bound the delivery tail** while keeping
v2's availability mechanisms: a cap on candidates per case and full removal
(not demotion) of superseded records are the named directions, together with
the standing finding that admission cannot compensate for ranking. Synthetic
results remain non-evidence for real-world performance, and v2's constants
(marker list, demotion 0.25, relative floor 0.60) were chosen after v1 and
may overfit this fixture.
