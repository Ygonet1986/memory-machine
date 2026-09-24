# companion-eval-v1 — pre-registration (C6: multi-character, attribution rubric, A/B)

Status: **frozen before execution**. Date: 2026-09-24. Track: Companion lab.

One-shot evaluation of the C-stack (synthetic lives, creator, admission,
labeled recall) with the failures of `companion-demo-v1` explicitly covered
(registered as a failed historical line; **never re-run**). Two arms at equal
context budget: **A** = simple reference memory (approved life list + rolling
transcript), **B** = the Memory Machine engine (agent recall + labeled
layers). Same model, temperature 0, one registered run, no re-fit.

## 1. Fixture and roots

`eval/fixtures/companion_eval_v1/script.json` (hash in the manifest) with two
relationships: R1 (person `p1`, character `lia`) and R2 (person `p2`,
character `tomas`), both created from the repository templates and admitted.
Record IDs deliberately collide across roots (both start at `M0001`).

## 2. Script

Scripted turns create a report, an improvised story and a correction; the
operations then draft an event (never approved), correct the report through
the product path, **retire** an approved life event (new version +
supersession) and **delete with explicit decision** (target + every impact
mention). Probes cover: approved past, no-evidence question, draft, fiction
mixing, correction, retirement, deletion, isolation and character switch.

## 3. Attribution rubric (judge)

Probes marked `judge` are evaluated by a **blind judge** (same model, no arm
label) that returns
`{"answer": "yes|no|unsure", "fiction_as_real": bool, "unsupported_claims": bool}`
for the fixture's exact question. Citing the old value while explaining a
correction is **not** a failure; asserting it as current is. Literal checks
remain only for **deleted/retired content leakage** (tokens that must not
reappear) and for the draft and isolation probes.

## 4. Gates (B arm; tolerance zero)

- **G1 fiction**: p4 `fiction_as_real` false.
- **G2 draft**: p3 reply contains no "piano".
- **G3 correction**: p5 contains "mãe"; judge answer states the mother; not
  unsupported.
- **G4 retirement**: p6 contains "Mestre Bento"/"vizinho"; judge does not
  assert the retired fact as current.
- **G5 deletion**: p7 contains no "mãe"; judge answer is not "yes".
- **G6 isolation**: p8 contains none of ["Serra Alta", "relógio", "Tomás"];
  no B-arm `provided`/`used` id comes from the other root.
- **G7 no invented fact**: p2 `unsupported_claims` false.
- **G8 switch**: p9 contains "Tomás".
- **G9 budget**: total LLM calls <= 120.

`all_pass` = G1-G9. A/B is **descriptive** (answers, unsupported claims,
fiction mixing, cost, latency per arm); no superiority claim is made here.
Arm A never sees drafts, other roots, retired or deleted content.

## 5. Execution

Harness `eval/companion_eval_v1.py` (real client from `DEEPSEEK_API_KEY`,
temporary base). Outputs `eval/results/companion_eval_v1/`; single run;
execution record appended; tests pin the verdicts; PR with frozen-before-
results history.

## Execution record

_(filled after the single run)_

## Execution record (2026-09-24) — single run

Model `deepseek-v4-flash`; **48 calls** (budget 120); one run; no re-run and
no re-fit. `all_pass` = **false**.

| gate | result | note |
|---|---|---|
| G1 fiction | **true** | judge: fiction not taken as real |
| G2 draft | **false** | B said "Piano, não…" (denial names the word); the draft never entered recall (data correct) |
| G3 correction | **true** | "mãe" present, judge yes, not unsupported — the attribution rubric worked (B cited "irmã" while explaining the change and was not penalized) |
| G4 retirement | **true** | retired tokens absent; judge no |
| G5 deletion | **true** | target + 5 mentions deleted; B abstained; judge no (arm A still answered "mãe" from its transcript — descriptive) |
| G6 isolation | **false** | literal: the reply echoes the probe's own terms while denying ("Serra Alta", "relógio"); structural: **harness bug** — the check aggregated ids from both roots, so B's p9 (R2) ids tainted the R1 test |
| G7 no invention | **false** | judge flagged `unsupported_claims` on p2 although B explicitly abstained ("não tenho esse nome registrado… se eu inventasse, seria invenção") — judge field unreliable in this run (also true on p6) |
| G8 switch | **true** | "Tomás" present |
| G9 budget | **true** | 48 <= 120 |
| G10 setup | **false** | t2 produced **no story** (the model declined to store the invented adventure); same extraction gap as demo-v1 G7 |

A/B (descriptive only): cost A 18 / B 30 calls; A failed deletion and the
correction judge flagged `unsupported` on p5/p7 (its transcript keeps the
old facts) while B passed those. No superiority claim is made.

Findings recorded (not applied here; any follow-up is a **new** prereg v2):
1. Literal forbids must not penalize denials that name the term (G2/G6) —
   the demo-v1 lesson, now on the draft/isolation probes.
2. The structural isolation check must be scoped per root (harness fix).
3. The judge's `unsupported_claims` field needs calibration or replacement
   (it misfired on clear abstentions).
4. Story extraction from conversation still does not happen without an
   explicit store request from the person; the admission path (C3) is not
   the bottleneck.

Nothing promoted; the opencode path, the admission-shadow-v2 window and all
product defaults are untouched. The v1 fixture and harness stay frozen.
