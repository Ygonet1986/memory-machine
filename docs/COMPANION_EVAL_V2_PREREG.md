# companion-eval-v2 — pre-registration (calibrated judge, per-root isolation, fault step)

Status: **frozen before execution**. Date: 2026-09-24. Track: Companion lab.

Follow-up to `COMPANION_EVAL_V1_PREREG.md` (single run, `all_pass=false`,
recorded and never re-run). v2 fixes the four registered findings **before**
running: denial-aware attribution, per-root structural scope, a calibrated
judge, and a publication-fault case; the deterministic story trigger (merged
separately) closes the setup gap. One registered run, no re-fit afterwards.

## 1. Fixture

`eval/fixtures/companion_eval_v2/script.json`, sha256
`d7bfb68833101a267caf9c4d3f11d061d047651323bc586ad123a9ad4a5d1c27`
(17 steps: the v1 script plus a `publish_fault` step and a calibration block;
new hash, the v1 fixture stays frozen). Two roots (Lia/Tomás), deliberate ID
collisions.

## 2. Judge protocol (schema v2)

Blind judge returns
`{"answer": "yes|no|unsure", "asserts_as_current": bool, "fiction_as_real": bool}`.
**Negating, or citing the old value to explain a change, does not count as
asserting** (explicit in the prompt). Before the probes, the judge must pass a
**calibration block of four fixed pairs** (denial naming the term, assertion,
fiction-as-real, abstention). `G0` records calibration; a failed calibration
makes the run non-interpretable by contract.

## 3. Gates (B arm; tolerance zero)

- **G0 judge**: all four calibration pairs match.
- **G1 fiction**: p4 `fiction_as_real` false.
- **G2 draft**: p3 `asserts_as_current` false (literal mentions are reported,
  not gated).
- **G3 correction**: p5 contains "mãe" and the judge answers "yes".
- **G4 retirement**: p6 `asserts_as_current` false.
- **G5 deletion**: p7 `asserts_as_current` false and answer != "yes".
- **G6 isolation**: p8 `asserts_as_current` false **and** per-root structural
  scope: every r1/r2 `provided` id belongs to that root's final tape and no
  r1 `used` summary matches an active r2 life summary.
- **G7 no invention**: p2 `asserts_as_current` false and answer != "yes".
- **G8 switch**: p9 contains "Tomás".
- **G9 budget**: total calls <= 130.
- **G10 setup**: t1 wrote a `person_report` and t2 wrote a `story` (the
  deterministic store-request trigger fires on "Guarde isso como nossa
  história").
- **G11 publication fault**: the injected failure between approval and
  admission leaves a journal, and `recover_publication` completes it with no
  journal left.

`all_pass` = G0-G11. A/B stays descriptive. Failure is recorded as-is; any
further iteration requires a new prereg.

## 4. Execution

Harness `eval/companion_eval_v2.py` (real client, temporary base, one run);
outputs `eval/results/companion_eval_v2/`; execution record appended; tests
pin the verdicts; PR with frozen-before-results history.

## Execution record

_(filled after the single run)_

## Execution record (2026-09-24) — single run

Model `deepseek-v4-flash`; **56 calls** (budget 130); one run; no re-run and
no re-fit. `all_pass` = **false** (G0 and G6 only).

| gate | result | note |
|---|---|---|
| G0 judge | **false** | calibration pair **cal3 was mislabeled in the fixture**: a reply that frames the caverna as "nossa história" was expected to be `fiction_as_real`, but refusing to treat it as real is the *correct* behaviour; the judge scored cal1/cal2/cal4 exactly. Contract says a failed calibration makes the run non-interpretable. |
| G1 fiction | **true** | judge: fiction not taken as real |
| G2 draft | **true** | denial-aware: "não tenho piano" passes now |
| G3 correction | **true** | "mãe" + judge yes (asserts_current true is correct for the mother question) |
| G4 retirement | **true** | judge `asserts_as_current` false |
| G5 deletion | **true** | judge false; target + 5 mentions removed |
| G6 isolation | **false** | judge clean (`asserts_as_current` false) but the **structural check is mis-designed**: it compares `provided` ids against the *final* tape, so records deleted later (p7) fail membership; membership must be per-step, and deleted-after-use is legitimate |
| G7 no invention | **true** | judge false on p2 |
| G8 switch | **true** | "Tomás" present |
| G9 budget | **true** | 56 <= 130 |
| G10 setup | **true** | t1 report + t2 story (the deterministic store-request trigger fired) |
| G11 publication fault | **true** | injected failure left a journal; recovery completed it |

A/B (descriptive): cost A 20 / B 32 calls. All data-level gates pass; both
failures are harness check-design defects, recorded without re-fit.

Recorded consequences (not applied here; a v3 prereg would be a new round):
1. cal3 must be a true fiction-mixing reply ("No fim de semana fomos à
   caverna…"), not a story-framed one.
2. Structural membership must be evaluated per step (or with a snapshot at
   use time); using the final tape falsely penalises legitimately deleted
   records.

Nothing promoted; the opencode path, the admission-shadow-v2 window and all
product defaults are untouched. v1 and v2 fixtures/harnesses stay frozen.
