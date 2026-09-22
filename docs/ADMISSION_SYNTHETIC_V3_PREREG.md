# admission-synthetic-v3 — pre-registration (frozen before execution)

Status: **frozen before execution**. Date: 2026-09-22.

Third controlled round on the **same frozen sample** (`admission_synthetic_v1`,
hash `f61262d3bc3c8999ba41680792db18f17955021a9aa2f08277da87ea4506bb83`).
P0/P1/P2, P3v1 and P3v2 are re-executed from their frozen modules as
references; nothing is re-implemented.

## 1. What v3 attacks (named v2 causes)

| v2 failure | declared cause | v3 change |
|---|---|---|
| precision 0.4545 (G2, G7) | relative floor admits the tail: commodity-token extras (5/case in `short_ambiguous`), demoted superseded records still passing (`corrected`/`long_specific`/`shared_subject`), `multi_memory` extras | **tail cap (2 per case)** + **full removal of superseded records** |

Everything else is exactly P3v2: weights (0.30 base + 0.20 rare + 0.15
entity + 0.15 temporal + 0.10 type_fit + 0.10 correction), extended entity
patterns (paths, prefixes), temporal = newest with `rare > 0`, correction
markers, redundancy (Jaccard > 0.60), `rare >= 0.30`, relative floor
`0.60 x best_gain`, budget 4000 chars.

## 2. P3v3 (primary) — exact declared rule

1. Score every candidate exactly as P3v2.
2. **Supersession removal** (replaces v2's demotion): if any candidate has
   `correction == 1`, remove every candidate with `correction == 0`, the same
   record type, an older `created_at` than that correction candidate, and at
   least 2 shared tokens with it.
3. Order the survivors by `gain` desc (ties: `base`, then candidate order).
4. Redundancy: token Jaccard > 0.60 against the selected union -> the
   candidate's gain is multiplied by `(1 - jaccard)`; it is skipped when the
   result falls under the floor.
5. Deliver while cumulative characters <= 4000 **and** `rare >= 0.30` **and**
   `gain >= 0.60 x best_gain` (best gain among survivors) **and at most 2
   candidates are delivered per case**.

## 3. Policies compared

P0, P1, P2 (as v1); P3v1 (frozen v1 module); P3v2 (frozen v2 module);
**P3v3** (primary).

## 4. Metrics

As v1/v2: availability, precision, delivered, mean characters, abstention
rate (S7), per-scenario availability; plus max deliveries per case (the cap
check) and the number of removed superseded records.

## 5. Gates (P3v3; all required)

- **G1** availability >= 0.90.
- **G2** precision >= 0.70.
- **G3** dual frontier: availability(P3v3) > availability(P2) **and**
  precision(P3v3) > precision(P1).
- **G4** abstention rate (S7) >= 0.80.
- **G5** every deliver scenario availability >= 0.70.
- **G6** determinism (two runs byte-identical outside timing).
- **G7** beats v2: availability(P3v3) >= availability(P3v2) **and**
  precision(P3v3) > precision(P3v2).
- **G8** cap verified: no case delivers more than 2 candidates.

## 6. Expected readings (declared, not gates)

Availability 1.000 (the cap 2 leaves every gold set intact - the only
two-record scenario keeps both); delivered around 140-160, precision ~0.65-
0.75; `short_ambiguous` precision 0.50 (gold + one capped extra);
`corrected` precision 0.50-0.70 after full removal. Recorded so the execution
record cannot tell a post-hoc story.

## 7. Stop rules

- Any gate fail: report, change nothing, re-fit nothing. If G2 still fails,
  the residual is not tail size but candidate quality on commodity-token
  questions, and the next hypothesis must target that, not another cap. If
  G7 fails only on availability, the cap is the cause and must be revisited.
- All gates pass: authorizes a **product-side shadow pre-registration**
  (real tapes, cost/latency) - never promotion; promotion still requires
  availability and precision together under the 4000-char budget on real
  data. Synthetic results remain non-evidence for real-world performance.
- **Iteration warning**: v3 is the third round on the same fixture; its
  constants (cap 2, removal rule) were chosen after v1/v2 aggregates and may
  overfit. Any further synthetic round requires stating why the fixture is
  not being fitted.

## 8. Threats and limits

As v1/v2. Added: with three rounds on one sample, precision gains may partly
reflect fixture-specific regularities (especially caps interacting with the
gold-set sizes). The execution record must quantify how much of the gain
comes from the two declared changes alone (the removal count and the capped
extras), so the mechanism claim stays honest.

## 9. Execution protocol

Harness `eval/admission_synthetic_v3.py` (imports the frozen v1 and v2
modules), outputs `eval/results/admission_synthetic_v3/report.json` and
`report.md`, structural test `tests/test_admission_synthetic_v3.py`, proof
regenerated, one primary run plus the determinism rerun, execution record
appended, all committed together.

