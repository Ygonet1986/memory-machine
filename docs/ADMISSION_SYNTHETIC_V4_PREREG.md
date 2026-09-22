# admission-synthetic-v4 — pre-registration (frozen before execution)

Status: **frozen before execution**. Date: 2026-09-22.

Fourth and **final** round on the frozen sample (`admission_synthetic_v1`,
hash `f61262d3bc3c8999ba41680792db18f17955021a9aa2f08277da87ea4506bb83`).
After this round the synthetic line closes regardless of outcome (owner
decision): pass -> product-side shadow pre-registration; fail -> the trilemma
stands as the finding.

## 1. What v4 attacks (named v3 cause)

v3 removed superseded records (30) and capped deliveries at 2, lifting
precision to 0.643, but the cap truncated the correction: in `corrected`, the
survivor order is build (0.412), preference (0.344), correction (0.321) and
only two slots exist. **The declared mechanism lacked a priority slot for
corrections** - supersession was a score bonus, not a privileged position.

## 2. P3v4 (primary) — one structural change over P3v3

Scoring, supersession removal, floors (`rare >= 0.30`, relative
`gain >= 0.60 x best_gain`), redundancy (> 0.60 Jaccard) and the 2-candidate
cap are exactly P3v3. The only change is the **selection order**:

1. Compute the eligible set (floors satisfied) among survivors.
2. If any eligible candidate has `correction == 1`, the highest-gain one
   (ties: earliest candidate order) is selected **first as slot 1** and is
   exempt from the redundancy penalty; it is the primary answer.
3. The remaining slot(s), up to the cap of 2, are filled in gain order under
   exactly the v3 rules (redundancy penalty, floors, budget).

This is a priority rule, not a new constant: it uses the existing floors and
markers. Rationale (declared): a correction supersedes the records it
corrects; relevance order alone cannot express that.

## 3. Policies compared

P0, P1, P2 (as v1); P3v1, P3v2, P3v3 (frozen modules); **P3v4** (primary).

## 4. Metrics

As v2/v3, plus per-scenario precision (reported, not gated).

## 5. Gates (P3v4; all required)

- **G1** availability >= 0.90.
- **G2** precision >= 0.70.
- **G3** dual frontier: availability(P3v4) > availability(P2) **and**
  precision(P3v4) > precision(P1).
- **G4** abstention rate (S7) >= 0.80.
- **G5** every deliver scenario availability >= 0.70.
- **G6** determinism.
- **G7** beats v3: availability(P3v4) >= availability(P3v3) **and**
  precision(P3v4) > precision(P3v3).
- **G8** cap verified: no case delivers more than 2 candidates.

## 6. Expected readings (declared, not gates)

Availability 1.000 (`corrected` restored by the slot; every other scenario
already at or above v3). Deliveries stay around 140, precision ~0.71 (the
corrected case swaps two wrong deliveries for the correction plus one).
Risk declared: a false-positive correction marker elsewhere would take slot 1
and could reduce precision; in that case G2 may fail and the line closes with
the trilemma.

## 7. Stop rules and line closure

- Any gate fail: report, change nothing, re-fit nothing; **the synthetic line
  closes** with the trilemma (availability x precision x ordering)
  documented in `docs/ADMISSION_SYNTHETIC_CLOSURE.md`.
- All gates pass: the line closes with a **pass**; the authorized next step
  is a product-side shadow pre-registration (real tapes, cost/latency) -
  never promotion. Synthetic results remain non-evidence for real-world
  performance.
- No further synthetic round on this fixture (owner decision); the closure
  record must state the overfitting risk of four rounds on one sample.

## 8. Execution protocol

Harness `eval/admission_synthetic_v4.py` (imports frozen v1-v3 modules),
outputs `eval/results/admission_synthetic_v4/report.json` and `report.md`,
closure record, structural test `tests/test_admission_synthetic_v4.py` (with
a v4 == v3 invariant where no eligible correction exists), proof regenerated,
one primary run plus the determinism rerun, execution record appended, all
committed together.

