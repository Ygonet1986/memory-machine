# Utilization diagnostics — U-phase results

**Scope.** With retrieval, admission and the graph frozen (`graph-v3`), measure
what happens *after* evidence is selected: was the gold delivered, was its fact
intact, and did the answerer use it? Harness: `eval/graph_util_diag.py`
(snapshots `eval/graph_out/u_diag_*.jsonl`, gitignored; checksummed). No
graph/admission/default change; `PAPER.md`/`RESULTS.md` untouched.

## Method

- Frozen agent annotations from the shared-agent replays (relevances recovered
  from each case's `case_XX_agent/whiteboard.json`), so rebuilt payloads match
  the answered ones: `payload_matches_snapshot = True` in every arm (ids +
  chars), which validates reusing the snapshot answers.
- Per gold memory: delivered?, position, allocated/used chars, truncated?,
  citation `M####` and answer↔gold token overlap, plus an LLM probe
  (`used/partial/ignored/contradicted`).
- **AUR-gold-delivered**: correct among cases where every required gold item was
  delivered.
- Interventions: **I1** = same admission, payload floor of 600 chars/item
  (fact preservation by allocation); **I4** = gold sessions only, untruncated
  (diagnostic ceiling, not a competitor).

## Aggregate

| arm | easy slice (12) | hard slice (12) | AUR-gold-delivered easy / hard |
|---|---|---|---|
| graph_off | 0.750 | 0.583 | 9/9 · 5/6 |
| graph_augment_precise (current) | **0.833** | 0.500 | 10/11 · 5/7 |
| i1_fact_floor | 0.750 | 0.500 | — |
| i4_gold_full (ceiling) | **0.833** | **0.667** | gold by design |

Gold delivered / truncated: easy **18 of 19**, hard **29 of 29**. In the guarded
payload the fact-bearing part of a session is almost always cut away.

## Mechanism taxonomy (per case, from the diagnostics)

1. **Truncation hides the fact — and I4 repairs it.** Cases 9, 88, 89, 131
   (plus 6/78/162 where gold was not delivered at all). Case 9 is the clean
   example: M0032 *was* in the payload (1,290 chars, truncated) but the "2
   hours" statement sat beyond the cut; the answerer said "no screen-time
   measurement anywhere". With the untruncated gold (I4) it answers 2 hours.
   Our earlier reading of case 9 as "present but ignored" was wrong in
   mechanism: the fact had been cut away.
2. **The untruncated ceiling also hurts.** In 5 cases where the truncated
   payload was correct (7, 8, 86, 119, 126) I4 regresses. Full sessions
   (up to ~39k chars for a gold set) distract as much as they inform — the
   protective budget is doing real work; "deliver everything" is not the fix.
3. **Composition limit (answerer-side).** Case 71 (how many projects led): all
   4 gold delivered, probes mixed, I4 also wrong (3 vs 11 counts across arms) —
   even gold-only untruncated fails. No delivery change can repair this;
   documented as an answerer limitation.
4. **Retrieval coverage gaps.** 78 and 162 delivered none of the required
   sessions while I4 (by construction) answers correctly. These are frozen
   retrieval-layer failures, out of scope for U.

**AUR-gold-delivered** quantifies utilization once evidence arrives: 10/11 on
the easy slice but only 5/7 on the hard multi-session slice — when the task
requires composing several sessions, having the evidence is not enough.

## Probe caveats

The per-item probe is a soft instrument: it is nondeterministic (M0038 flipped
ignored/partial between two runs of the same case) and in case 9 it said "used"
for an answer that explicitly denied the data. Use it as a hint; the verdicts
and the delivered-text accounting are the ground truth.

## U2b — fact-window truncation (the delivery candidate)

`i5_fact_window`: same admission and same 4,000-char budget as `precise`, but a
truncated memory delivers the **question-matched window** of the session (the
best-scoring segment expanded by score until the allocation fills) instead of
its head. The window is now implemented once in the core (`payload.fact_window`)
and imported by the harness; the earlier harness-local version truncated the
window tail and is superseded.

| arm | easy slice | hard slice | both |
|---|---|---|---|
| graph_augment_precise | 10/12 | 6/12 | 16/24 |
| i1_fact_floor | 9/12 | 6/12 | 15/24 |
| i4_gold_full | 10/12 | 8/12 | 18/24 |
| **i5_fact_window** | 10/12 | **7/12** | **17/24** |

Paired vs precise: **2 repaired (9, 88), 1 regressed (0)**; windows applied to
37 (easy) and 60 (hard) items; payloads stay within 4,000 chars.

- **Repair, case 9 (easy)**: the "2 hours" statement now survives inside
  M0032's window (the flagship truncation case).
- **Repair, case 88 (hard)**: partial → correct.
- **Regression, case 0 (easy)**: the question asks for an *increase*, which
  needs an arithmetic anchor (the starting figure) that is **not** the
  question-matched sentence. The window kept the later "≈350 total" span and
  dropped the baseline, so the answer went from ~100 (correct) to ~350
  (incorrect). When the task composes several spans, "keep only the matched
  span" is risky.
- **Not repaired, 89/131**: multi-session counting/composition; only the
  intrusive i4 ceiling fixes them.

**Reading:** fact-window truncation is the first delivery change that repairs
truncation damage **without the i4 overload regressions** and within budget —
net +1 over 24 cases, with one counter-case and one non-repair class. It stays
an **opt-in flag, default off** (`evidence_payload_window=false`), with the
head cut unchanged when off. If pursued: apply windowing only when the record
is single-fact-like, or keep a fraction of the original span for arithmetic
questions, then re-measure on a larger slice.

## Decision

- **No core/delivery change from this round.** I1 (600-char floor) is neutral at
  best (0.750/0.500) because a blunt floor does not localize the fact; it is
  rejected as a default.
- **U2b ran: fact-window truncation repairs cases 9 and 88 without the i4
  overload regressions, netting +1 over 24 cases with one counter-case (0,
  arithmetic anchor dropped).** It is implemented as an opt-in flag
  (`evidence_payload_window`, default false; flag-off is byte-equivalent to the
  previous payload) with tests; the default stays head truncation. Cases 89/131
  (and the case-0 regression) confirm that composition still dominates the
  remaining hard-slice failures.
- **I4 stays a diagnostic instrument** (gold-only untruncated), not a product
  mode: it violates the budget discipline and regresses 5 cases.
- Retrieval/admission stay frozen (`graph-v3`); composition (case 71) and
  overload are answerer-side limits, not memory failures.

## U3 — 30-case validation of the delivery policies (pre-registered)

Slice: indices 12–41 of the frozen seed-7 sample (untouched by earlier runs),
15+15 in two blocks; arms `off`, `precise`, `i5`, `i5_single` (window only for
single-fact question patterns) and `i5_mixed` (25% head + 75% window for
composition questions). Decision rule (pre-registered): zero overload
regressions, then max repairs−regressions, then fewest windowed items.

| arm | strict | lenient | windowed items | flips vs precise |
|---|---|---|---|---|
| graph_off | 20/30 | 23/30 | — | — |
| graph_augment_precise | 21/30 | 22/30 | 0 | baseline |
| i5 | 21/30 | 23/30 | all truncated | +3 / −3 |
| i5_single | **22/30** | 23/30 | 52 | +3 / −2 |
| i5_mixed | 21/30 | 22/30 | 99 | +3 / −3 |

**Variance audit (the decisive step).** Flips whose payload *and* context are
identical to `precise` cannot be policy effects. Case 20 under `i5_single` (not
windowed, context identical) flipped incorrect → correct: **answer variance**.
Case 39 under `i5_single` (not windowed, identical) stayed correct while
`i5`/`i5_mixed` (windowed) fell to incorrect. After removing the identical-
context flip, the real ledger is:

- **Repairs:** case 22 (single-fact, window applied).
- **Regressions:** case 26 and 41 (`i5_single` and `i5`/`mixed`), case 39
  (`i5`/`mixed` only; `i5_single`'s gating avoided it).
- **Net real effect: negative (−1 to −2)** despite the nominal strict advantage
  of `i5_single` (22/30 vs 21/30).

**Conclusion (negative/neutral, honestly reported).** The fact-window *mechanism*
repairs real truncation cases (9/88 in the 24-case round, 22 here), but
**deciding the truncation style from the question text with these simple
patterns does not generalize**: the single-fact detector avoided one regression
(39) and did not prevent the others (26, 41). `i5_mixed` windows almost
everything (99 items) with no additional benefit, and the joint strict
differences (±1 case) are inside answer/judge variance unless the context is
identical.

**Decision:** no promotion. `evidence_payload_window` stays opt-in, default
off; the detector arms stay harness-only. If this line is pursued, the next
step must (a) measure deterministic fact-presence in the delivered text
(not only verdicts), (b) repeat answers per arm to bound judge variance, and
(c) make composition questions keep their anchors rather than window them.
Graph, admission and all frozen artifacts are untouched.

## U4.1 — deterministic fact presence (instrument calibration)

`eval/fact_presence.py` reads the frozen snapshots (no LLM) and checks, per
case/arm/required memory, whether atoms survive in the delivered span. The
pre-registered calibration produced two instrument generations and one
substantive result:

1. **Global item-fact rate (generation 1, rejected as a predictor).** Counting
   every number/entity/date of a memory: payload arms deliver only **24–27%**
   of them (easy slice) and **~10%** (lexmiss) versus **99.9%** under the
   untruncated gold condition (i4). The i4 arm validates the extractor (span
   format bug fixed): truncation is quantified, but the rate does **not**
   predict verdicts (regressed cases even show *higher* rates).
2. **Question-conditioned atoms (generation 2).** Atoms restricted to the
   question/reference-matched sentence of each memory. Class split:
   - composition questions, hard slice: payload **0.33**, window **0.49**,
     gold-full **1.00**;
   - composition, easy slice: 0.88–0.94; other classes 0.56–0.89.
   The metric is sensitive and correctly flags the pure-variance flips:
   cases 20 and 38 show **presence delta 0.000** (identical context → no
   policy effect).
3. **The U3 flips are not fact-presence-driven.** Case 22 was "repaired" with
   presence saturated at 1.00 in both arms; cases 26 and 41 regressed while
   presence *rose* (+0.25, +0.08). Delivery-policy flips therefore trace to
   answerer variance / context arrangement, not to more facts arriving.

**Conclusion of U4.1.** The deterministic metric is valid for measuring
**delivery loss** (and shows multi-session composition questions lose two
thirds of their relevant facts under the budget), but it is **not** an outcome
predictor. Before any delivery-policy claim, the **replication instrument
(U4.2)** is mandatory: only effects that exceed the identical-context flip
floor can be attributed to a policy. FP/FN calibration lists are stored in
`eval/graph_out/fact_presence_*.jsonl` (metric-present-but-wrong = 0–5 per arm;
metric-absent-but-correct tracked separately), as pre-registered.

## Reproduce

```bash
PYTHONPATH=src:.:eval python3 eval/graph_util_diag.py --stage all --api-key ...
python3 - <<'PY'   # aggregate
import json
for s in ("longmemeval", "longmemeval_lexmiss"):
    rows = [json.loads(l) for l in open(f"eval/graph_out/u_diag_{s}.jsonl")]
    for arm in ("graph_off", "graph_augment_precise", "i1_fact_floor", "i4_gold_full"):
        n = sum(1 for r in rows if r["arms"][arm]["verdict"] == "correct")
        print(s, arm, f"{n}/{len(rows)}")
PY
```
