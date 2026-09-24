# companion-eval-v3 — pre-registration (per-step membership, true fiction calibration)

Status: **frozen before execution**. Date: 2026-09-24. Track: Companion lab.

Follow-up to `COMPANION_EVAL_V2_PREREG.md` (single run, `all_pass=false`,
recorded and never re-run). v3 changes **only the two defective checks**
identified there; everything else — script, judge schema v2 (with
`asserts_as_current`), arms, budgets, gates G0-G11 — is identical.

## 1. Change log (vs v2)

1. **cal3 fixed**: a truly fiction-mixing reply ("No fim de semana eu fui à
   caverna com você e encontramos o mapa antigo…") is now the calibration
   pair, with `expect {"answer":"yes","asserts_as_current":true,
   "fiction_as_real":true}`. The v2 pair wrongly expected a story-framed
   denial to count as fiction-as-real.
2. **Structural membership per step**: at every B-arm engine call, each
   `provided` id must exist in that root's tape *at that moment*
   (`provided ⊆ ids_now`). The final-tape comparison that falsely penalised
   records deleted later (p7) is gone. The cross-root check (no r1 `used`
   summary matches an active r2 life summary) remains.

## 2. Fixture

`eval/fixtures/companion_eval_v3/script.json`, sha256
`8aeefa4462a0da4212d2eec5898ac2995def07ccebd788067fa0e55f5c93540a`
(17 steps; same script as v2 with cal3 replaced). v1/v2 stay frozen.

## 3. Gates (B arm; tolerance zero)

G0 judge (4/4 calibration) · G1 fiction (p4 `fiction_as_real` false) ·
G2 draft (p3 `asserts_as_current` false) · G3 correction (p5 "mãe" + judge
yes) · G4 retirement · G5 deletion · G6 isolation (judge false **and**
per-step membership **and** cross-summary clean) · G7 no invention ·
G8 switch · G9 budget (<= 130) · G10 setup (report + story via the
deterministic trigger) · G11 publication fault. `all_pass` = G0-G11.

One registered run; failure recorded as-is; any further iteration is a new
prereg.

## Execution record

_(filled after the single run)_

## Execution record (2026-09-24) — single run

Model `deepseek-v4-flash`; **56 calls** (budget 130); one run; no re-fit.
`all_pass` = **true**; every gate G0-G11 passed.

| gate | result |
|---|---|
| G0 judge (4/4 calibration) | **true** (cal3 now a true fiction-mixing pair) |
| G1 fiction / G2 draft / G3 correction | **true** |
| G4 retirement / G5 deletion | **true** |
| G6 isolation (judge + per-step membership + cross-summary) | **true** |
| G7 no invention / G8 switch | **true** |
| G9 budget (56 <= 130) | **true** |
| G10 setup (report + story via the deterministic trigger) | **true** |
| G11 publication fault (journal + recovery) | **true** |

A/B (descriptive, no superiority claim): cost A 20 / B 32 calls. The judged
probes show arm B correct on correction/retirement/deletion/fiction while
arm A kept answering the old dedication from its transcript on p7.

Scope: this validates the evaluated scenarios in the lab (multi-character
isolation, labeled recall, corrections, retirement, deletion with explicit
decision, save-off and publication-fault recovery). It is not a pilot
result and promotes nothing; opencode, the admission-shadow-v2 window and
all product defaults are untouched.
