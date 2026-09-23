# teo-world-v2 — pre-registration (candidate / adopted / in-review under the same budget)

Status: **frozen before execution.** Date: 2026-09-23. Track: Trilepsia thesis
(owner axis; still decoupled from T3).

Round 1 (`docs/TEO_WORLD_V1_PREREG.md`, commits `94b679e` / `a12ae8b`, PR #49)
closed `advance = false`: the typed arm won M3 and M5, failed the M4 per-family
guard, and 100% of its false alarms occurred at or before convergence —
**consistent with, but not proof of,** the early-commitment explanation;
that explanation is what this round tests. Round-1 worlds now serve as
**development**; the confirmation below runs once on **reserved worlds** (§5).

## 1. Hypothesis

Separating **candidate** from **adopted** hypotheses reduces M4 false alarms
while preserving the M3 and M5 gains, under the same budget (7 observations,
same policies, same families).

- **Candidate** — "this rule may explain the observations"; a wrong prediction
  refines the candidate, never announces.
- **Adopted** — "this rule passed out-of-sample validation"; wrong predictions
  accumulate evidence of change.
- **In review** — "the adopted rule lost support"; alternatives are
  investigated and uncertainty is recorded. Entering review **is the
  announcement** (M4 on stable worlds; detection on broken worlds).

## 2. State machine (frozen)

- **Validation (caution 1).** A candidate is validated after consecutive
  **out-of-sample** observations predicted within `theta`, predictions made
  *before* each observation, using only the budgeted observations — no extra
  draws, no post-hoc holds. `V_local = 2` for the window candidate;
  `V_mem = 3` for ledger candidates (a remembered rule is prior information;
  its transfer to a new world must clear a stricter bar). The asymmetry was
  chosen during development on round-1 seeds, after diagnosing stale-ledger
  validations as the dominant residual alarm source; the confirmation below
  uses reserved worlds.
- **Candidate pool.** (a) the **window fit** (last `K_WIN` observations, from
  `n >= 4`; parameters refit only while its counter is 0), and (b) up to
  `L = 8` most recent **ledger** hypotheses. A remembered rule returns as a
  **candidate** and must pass the same validation.
- **Primary model** (drives M1/M2/M3 statistics and adopted-violation errors):
  the adopted rule when one exists and is not in review; otherwise the
  candidate with the highest validation counter (ties: window fit, then most
  recent ledger).
- **Adoption.** Counter `>= V_local` (window) or `>= V_mem` (ledger) ->
  adopted. First adoption is not an announcement; adopting a different rule
  after review is the revision.
- **Review (caution 2).** An adopted rule with `W = 3` consecutive normalized
  errors `> theta` enters review; counters reset; new adoption requires
  validation. M3's clock still starts at the real break
  (`max(k_x, k_y)`); delaying adoption cannot hide lateness. Episodes with no
  adoption or no detection remain in evaluation with the declared censoring.
- **Degenerate guard (caution 3).** Adoption count, first-adoption time and
  review entries are recorded (descriptive, never gates). A system that never
  adopts cannot gain M3/M5 by construction, so the M3/M5 guards already
  protect utility.

## 3. Metrics and orientation

Same M1–M6 as round 1, with two clarifications:

- **M4** = announced detection = first entry into review (V2) or the sustained
  trigger (A1 / B-); measured on stable episodes; per-family guard
  `B_f <= A_f + 0.05`.
- **M5 orientation (explicit).** `M5 = M2(novel) - M2(repeat)`; **positive =
  the repeated rule converged with fewer observations** (re-identification
  gain). Round-1 §6 wrote the inverse formula; Appendix B fixed the convention
  the harness used, and no round-1 number changes under this statement.

## 4. Design and gate

- Same four families, ranges, `T = H = 20`, `theta`, `W`, budget `B_obs = 7`,
  fixed policy, bootstrap (1000; equal weights; world-level pairing).
- Arms: **c1** flat, **c3** V2 typed, **c3-** matched ablation (B skeleton
  with A1's information set).
- **Gate (all required, as round 1):** M3 win (CI upper `< 0`), M5 win
  (CI lower `> 0`), M4 per-family guard, LOFO sign-stable, B- attribution
  positive.
- **Falsifier.** If M4 fails again or the M3/M5 wins vanish, the verdict is
  *adoption-confidence does not fix it in this regime*: simplify the mechanism
  and prioritize composition on the product side. If all pass, there is
  ground to scale the experiment.

## 5. Reserved worlds (caution 4)

- New seed base **`20260926`** (world seeds `20260926 * 10 + family_index`),
  frozen here; identical families, ranges and episode sequences. Round-1 seeds
  are development only; the recorded evaluation never uses them.
- Harness `sim/ab2.py` (stdlib only; imports `sim/ab.py`), outputs
  `sim/results/teo_world_v2/`; one recorded run plus a byte-identical
  determinism rerun. Harness debugging on round-1 seeds is disclosed and
  precedes the recorded run.

## Execution record (2026-09-23, reserved base 20260926)

Harness `sim/ab2.py`; one recorded run plus a byte-identical determinism rerun
(`episodes.jsonl` sha256 `f7e9381a...`, `summary.json` sha256 `3770d212...`).
Development happened on round-1 seeds only; the reserved base was used for the
first time by this run. Identifiability floor: all four families pass.

| family | M3 c1 -> c3 | M4 c1 -> c3 | M5 c1 -> c3 | adopt/rep (V2) | reid |
|---|---:|---:|---:|---:|---:|
| linear | 0.920 -> 0.774 | 0.000 -> 0.000 | 0.000 -> 1.828 | 0.64 | 0.641 |
| const_accel | 0.907 -> 0.723 | 0.016 -> 0.062 | 0.031 -> 2.438 | 0.91 | 0.906 |
| attract | 0.668 -> 0.748 | 0.203 -> 0.000 | 0.000 -> 2.188 | 0.80 | 0.797 |
| oscill | 0.774 -> 0.748 | 0.453 -> 0.000 | 0.031 -> 2.109 | 0.59 | 0.594 |

Pooled `c3 - c1`: M3 mean -0.0693 (95% CI [-0.1057, -0.0388]), M5 mean
+2.1224 (95% CI [+1.9219, +2.3126]).

**Verdict (frozen §4): `advance = true`** — M3 win, M5 win, M4 per-family
guard, LOFO sign-stable, B- attribution positive. Separating candidate from
adopted hypotheses reduced false alarms while preserving detection and
transfer, on reserved worlds. Caveats recorded: the `const_accel` M4 margin is
thin (0.0625 vs 0.015625 + 0.05); and V2's M1 regressed in `linear`/`attract`
— the adoption delay buys alarm discipline with early prediction accuracy, a
trade-off not gated in either round. Per §4 this is ground to scale the
experiment, not a product claim; T3 remains closed and decoupled.

## Errata 1 — M3 computation (2026-09-23)

**Finding (reviewer audit, verified against the published artifacts).** The
prereg defines detection on broken worlds as **entry into review** (§1) and
requires censoring when no adoption/detection occurs (§2, caution 2). The
harness instead computed M3 from the raw error sequence, independent of the
announcement: 26 worlds (linear 5, const_accel 3, attract 9, oscill 9)
received M3 < 1.0 with **zero adoptions and zero reviews** in the broken
episode (e.g. seed `202609260002`, M3 = 0.15).

**Fix (minimal, per the frozen text).** M3 for V2 = first review with
`t > k_max`; latency = observations from `k_max` to that announcement; no
announcement -> censored at 1.0. A1/B- keep §3's uniform sustained statistic.
Nothing else changed. The corrected harness reproduces the first errata
implementation byte-for-byte; the reference environment is recorded in the
summary (darwin, Python 3.14.6).

**Artifacts.** Original run preserved at `sim/results/teo_world_v2/`
(`episodes.jsonl` `f7e9381a...`, `summary.json` `3770d212...`). Corrected run
at `sim/results/teo_world_v2_errata1/` (`episodes.jsonl` `b3e87248...`,
`summary.json` `24858f46...`); determinism rerun byte-identical. No world now
receives M3 credit without an announcement.

**Corrected result (reserved base 20260926).**

| family | M3 c1 -> c3 | M4 c1 -> c3 | M5 c1 -> c3 |
|---|---:|---:|---:|
| linear | 0.920 -> 0.709 | 0.000 -> 0.000 | 0.000 -> 1.828 |
| const_accel | 0.907 -> 0.550 | 0.016 -> 0.062 | 0.031 -> 2.438 |
| attract | 0.668 -> 0.607 | 0.203 -> 0.000 | 0.000 -> 2.188 |
| oscill | 0.774 -> 0.677 | 0.453 -> 0.000 | 0.031 -> 2.109 |

Pooled `c3 - c1`: M3 mean -0.1814 (95% CI [-0.2451, -0.1211]), M5 mean +2.1224
([+1.9219, +2.3126]); M4 per-family guard passes; LOFO sign-stable; B-
attribution positive -> **`advance = true`**.

**Sensitivity disclosure (exploratory, not preregistered).** The M3 verdict
depends on how A1/B- detection is defined. Measuring A1/B- by their announced
event instead of §3's uniform scan gives pooled M3 +0.1737 ([+0.1185,
+0.2307], A1 earlier; advance=false); adding onset attribution (violation must
start after the break) gives -0.1053 ([-0.1424, -0.0723]; advance=true). The
recorded reading follows the frozen text (§1 review event for V2; §3 uniform
scan for A1/B-). **Unifying M3 definitions requires a round-3 prereg**; the
sensitivity is recorded here so it cannot be lost.

**Reproduction.** Byte-identical reruns on the recording machine; the
reviewer's local run kept the gate but diverged in hashes — consistent with a
different Python/libm environment (the harness uses transcendental functions
and near-tie ordering). Cross-platform byte-identity is not claimed; a pinned
reproduction environment is a round-3 item.
