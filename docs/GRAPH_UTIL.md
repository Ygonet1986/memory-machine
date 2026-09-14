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

## Decision

- **No core/delivery change from this round.** I1 (600-char floor) is neutral at
  best (0.750/0.500) because a blunt floor does not localize the fact; it is
  rejected as a default.
- **Concrete next micro-test (U2b): fact-window truncation.** Instead of a
  larger floor, keep the sentence window inside each session that matches the
  question (the facts are mid-session), capped by the existing 4,000-char
  budget. Evaluate exactly on the truncation-repair cases (9, 88, 89, 131) and
  control against the overload regressions (7, 8, 86, 119, 126).
- **I4 stays a diagnostic instrument** (gold-only untruncated), not a product
  mode: it violates the budget discipline and regresses 5 cases.
- Retrieval/admission stay frozen (`graph-v3`); composition (case 71) and
  overload are answerer-side limits, not memory failures.

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
