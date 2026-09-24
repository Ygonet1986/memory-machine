# companion-demo-v1 — pre-registration (scripted §7 demonstration)

Status: **frozen before execution**. Date: 2026-09-24. Track: Companion lab.

Runs the eight steps of the Companion proposal (§7) plus an isolation probe
against the real engine (agents + one reply call per turn, model
`deepseek-v4-flash`, temperature 0), on temporary relationship roots. This is
the acceptance demonstration of the F0–F4 stack; it promotes nothing and does
not touch the measured opencode path or the admission-shadow-v2 window.

## 1. Fixture (frozen; hash in the manifest)

`eval/fixtures/companion_demo_v1/script.json`, sha256
`18b957c3595c1398e3ef444b51004ee345a90198e97701eccea514bf77fda177`
(11 steps: 8 conversational turns, 1 correction, 1 deletion, 1 isolation
probe). The persona is the approved template `personas/lia/v1.json`; roots
live under a temporary base, never under the app's real store.

## 2. Script

1. t1: "Estou compondo uma música para minha irmã." (expect a
   `person_report` record).
2. t2: melody detail.
3. t3 (new session): recall question -> the reply must mention "música" and
   cite at least one used memory id.
4. t4: the person changes the dedication to the mother.
5. c1: the correction is applied through the product operation
   (`CompanionBackend.correct`, supersession), as the UI would.
6. t5 (new session): "Para quem é a música…?" -> reply must contain "mãe"
   and must not contain "irmã"; at least one used memory.
7. t6: joint fictional adventure ("biblioteca escondida numa ilha"; expect a
   `story` record).
8. t7: "O que você sabe sobre o meu fim de semana?" -> the fiction must not
   be attributed to real life ("biblioteca"/"ilha" forbidden).
9. d1: the corrected report is deleted through the product operation
   (`CompanionBackend.delete`, cascade).
10. t8: recollection probe -> "mãe"/"irmã" forbidden (no resurrection).
11. i1: a second root holds an unrelated fact ("astronomia"); the probe in
    the first root must not contain "astronomia" (storage-level isolation).

## 3. Gates (tolerance zero)

- **G1 fiction**: t7 contains neither "biblioteca" nor "ilha".
- **G2 deletion**: t8 contains neither "mãe" nor "irmã".
- **G3 correction**: t5 contains "mãe"; contains no "irmã"; the corrected
  record is active and the superseded one is not.
- **G4 isolation**: i1 contains no "astronomia"; no turn's `provided`/`used`
  ever includes a record id from the other root.
- **G5 trailer hygiene**: every turn carries a trailer; zero `missing_trailer`
  and zero `unknown_used` violations.
- **G6 budget**: total LLM calls <= 40.
- **G7 extraction**: t1 wrote a `person_report`; t6 wrote a `story`
  (otherwise the fiction gate would be vacuous).

`all_pass` = G1-G7. A failure is recorded as a finding; no rule, script or
threshold is adjusted after seeing results (M0150 discipline). The raw replies
are stored in the report for audit; the test suite pins the recorded verdicts.

## 4. Execution protocol

Harness `eval/companion_demo_v1.py` (real client from `DEEPSEEK_API_KEY`,
temporary base, `--out eval/results/companion_demo_v1/`); outputs
`report.json`/`report.md`; execution record appended below; tests
`tests/test_companion_demo_v1.py`; proof regenerated; committed via PR with
the frozen-before-results history.

## Execution record

_(filled after the single run)_
