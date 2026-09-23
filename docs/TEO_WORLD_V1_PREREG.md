# teo-world-v1 — pre-registration (flat history vs typed records in a simulated world)

Status: **frozen; executed 2026-09-23** (record at the end). Date: 2026-09-23.
Track: Trilepsia thesis (owner axis). `sim/ab.py` is the execution commit's
payload (§10).

Relation to the closed lines: E2 closed as `localized repair only`
(`docs/COMPOSITION_V1.md` §12); the B2 vs B2+ gate closed as **provenance layer
only** (`docs/TRILEPSIA_GATE_V1.md`), T3 blocked; the active line is
E5/answerer-composition. This axis measures what the gate did not: **online
hypothesis revision and transfer** with an objective oracle (the world's own
next position instead of an LLM judge). Motivation is not license: the static
gate not having measured this is what justifies running the axis, not an
expectation that it passes. Owner decision (2026-09-23): the axis is
**decoupled from T3** — its outcome is neither a prerequisite for, nor a
promotion of, T3. A pass is evidence about the thesis in this regime; a fail
closes the thesis harder in this regime.

## 1. Variable

Representation, deterministic consumer, no LLM:

- **A (flat):** raw `(t, x, y)` history + deterministic consumer.
- **B (typed):** Trilepsia-style records — object, event at instant `t`,
  observation, hypothesis with declared scope and confidence, supporting
  evidence, revision with recorded reason, ledger across episodes.

"Text vs Trilepsia" is reserved for a later phase with an LLM reader; out of
scope here. The first commit measures representation, not a parser.

## 2. Worlds

- Base families (frozen; `piecewise` is **not** a family — the break is an
  orthogonal wrapper below). Laws are per axis, `x`/`y` draw independent
  parameters, signs are drawn per axis, `T` = episode length, `H` = horizon,
  and `T = H = 20` (frozen; also the `T` used in the ranges below):

| family | law (per axis) | parameters (per axis) | scale `S` |
|---|---|---|---|
| `linear` | `x(t) = a + v*t` | `a in [-0.5, 0.5]`; `v = +/- 2/T` | 2 |
| `const_accel` | `x(t) = a + v*t + c*t^2/2` | `a in [-0.5, 0.5]`; `v = +/- 1/T`; `|c| in [0.005, 0.02]`, sign per axis; `c = 0` excluded (would degenerate into `linear`) | 2 |
| `attract` | `x(t) = x* + d*exp(-lambda*t)` | `x* in [-0.5, 0.5]`; `d = +/- 2`; `lambda in [0.10, 0.20]` | 2 |
| `oscill` | `x(t) = mu + A*sin(2*pi*t/P + phi)` | `mu in [-0.25, 0.25]`; `A in [0.9, 1.0]`; `P in {6, 8, 10, 12}`; `phi in [0, 2*pi)` | 2 |

  `c` names the quadratic coefficient; `a` is only the intercept (never the
  acceleration).
- **Identifiability floor (frozen).** The dominant unmodeled term of each
  family at horizon `H` must reach `>= 4*sigma` (`sigma = 0.02`, so
  `4*sigma = 0.08`); verified deterministically at the execution commit. On
  failure the family is reported **non-identifiable**, never adjusted after
  seeing arm outputs.

| family | dominant unmodeled term at `H = 20` | floor |
|---|---|---|
| `linear` | `|v|*H = 2.0` = 100 sigma | clear |
| `const_accel` | `|c|*H^2/2 in [1.0, 4.0]` = 50-200 sigma | `|c| >= 0.16/H^2 = 4.0e-4` (range minimum clears it ~12x) |
| `attract` | `r = |d|*(lambda*H/2)^3/24 >= 0.083` = 4.17 sigma (minimax quadratic residual of the exponential) | `lambda*H >= 2` |
| `oscill` | `A in [0.9, 1.0]` = 45-50 sigma against a constant fit | clear |

- `attract` is the **overdamped** form on purpose: the underdamped/harmonic
  form has the closed form `x* + A*sin(omega*t + phi)`, i.e. exactly `oscill`
  — a duplicate. `const_accel` is a distinct fit class (2nd order) from
  `linear`; `linear` and `attract` separate only beyond short windows. The
  `const_accel` ceiling `|c| = 0.02` keeps the confounder alive on purpose:
  a higher ceiling would make it trivially separable and waste the
  order-extension vs model-switch test.
- **Regime break (uniform across the four families):** re-anchored at index
  `k`, C0-continuous (a kink, not a jump: `x(k^-) = x(k^+)`), with a
  derivative discontinuity, applied **independently per axis** (`k_x != k_y`
  allowed); no family has its own break form, and stable control episodes
  share the generation path.
- State: position and velocity; the agent sees only observations it chooses.
- Noise: `sigma = 1%` of `S` = 0.02, independent per axis (identical axes
  would make the second dimension degenerate).
- Observation grid, `H_a`, `theta`, `W`: appendix B (fixed before any run).

## 3. Loop (both arms)

Per step: observe -> register -> update trajectory -> propose/keep a hypothesis
with declared scope ("valid for the last `k` observations") -> predict 1 step
and `k` steps ahead -> choose the next observation on a **discrete time grid
inside `H_a`** (finite active sampling; a uniform grid is the degenerate
pre-fixed case). Same grid and same selection policy in both arms within a
cell.

## 4. Consumer freeze (the no-LLM confound)

Without an LLM both arms need a deterministic consumer; the experiment must not
become an engineering contest. A1 and B are frozen as code with an **identical
budget** — same number of observations, same grid, same `sigma/theta/W/H` —
except where the representation **forces** divergence. Forced divergences are
listed here and nowhere else:

| # | forced divergence | why it is representation, not tuning |
|---|---|---|
| D1 | state kept: A1 = last-`k` window; B = hypotheses with scope and confidence | scope/confidence are fields of the typed record (§1) |
| D2 | revision trigger: A1 = windowed residual sustained `> theta` for `W`; B = active hypothesis's scope-relative expected error violated, plus a competing hypothesis explaining the window better | the trigger reads typed state that A1 does not have |
| D3 | discard reason recorded (feeds M6) | only B has a discard event (§6) |
| D4 | ledger persists across episodes (feeds M5) | the flat arm has no cross-episode record |

- **A2** = `CusumConsumer` is diagnostic only: it yields its own M4 reading and
  **does not feed** A1/B decisions.
- **Matched ablation B−**: same skeleton and fitter as B, but the typed state
  reduced to A1's information set (last-`k` window, A1 trigger). Companion to
  the falsifier, not a new criterion: if `B ≈ B−`, the gain is engineering, not
  structure (§8).

## 5. Phases

0. hidden rule, no break (full cycle);
1. convergence under the full loop;
2. silent break, interleaved with **stable** episodes (false-alarm control);
3. unseen worlds: later worlds reuse earlier rules or parameter combinations,
   so the ledger has something to transfer.

## 6. Metrics

| # | metric | operational definition | A (flat) | B (typed) |
|---|---|---|---|---|
| M1 | prediction error 1/k | normalized MAE (primary), RMSE (secondary), mean over steps and seeds | windowed fit | hypothesis-conditioned fit |
| M2 | observations to converge | count until the normalized error stays `< theta` for `W` consecutive observations | same | same |
| M3 | detection latency | observations after the break until the normalized error stays `> theta` for `W` consecutive observations; **right-censored at H**, reported as `latency/H` | same | same |
| M4 | false alarm | rate of **stable** episodes with an announced detection | same | same |
| M5 | re-identification | `latency(repeated rule) - latency(new rule)`, via the ledger | ledger does not persist across episodes: ~0 expected | expected gain from the ledger |
| M6 | discards with reason | fraction of hypotheses withdrawn **with a recorded reason** | n/a | only exists in B (descriptive; never a gate) |

## 7. Design and primary test

- World = unit. `N = 64` per family. Paired by seed.
- Primary: **c1** (A, fixed observation policy) vs **c3** (B, fixed policy).
- Secondary 2x2 (declared in advance, oscillatory family only):
  c1 (flat, fixed), c2 (flat, active), c3 (typed, fixed), c4 (typed, active).
  Readings: `(c3-c1)` structure; `(c2-c1)` loop; `(c4-c3)` interaction. Only
  c1 vs c3 decides advancement; c2/c4 are diagnostic.
- Companion control: **c3−** (B−, fixed policy) runs alongside c3 and serves
  only the §4/§8 attribution check.
- Ledger persists hypotheses, identities and revisions across episodes; reset:
  position, observation budget, noise seed.
- **Scale rule (frozen).** `R_fam = p95(|x(t) - x(0)|)` over the trajectories
  sampled under the frozen Π, `t in [0, H]`; `M1 = error / R_fam` (realized
  reach, not the raw amplitude: `attract` uses `2*(1 - e^(-lambda*H)) ~ 1.73`
  at `lambda = 0.10`, `H = 20`, i.e. 13.5% below `|d| = 2`). `R_fam` comes
  from the frozen Π and is **never recomputed after seeing arm outputs**; all
  arm-vs-arm readings use pre-declared denominators (`error / R_fam`,
  `latency / H`), so LOFO and the pooled gate never compare raw scales.
- The primary claim is **typed vs flat under a fixed observation policy**; the
  policy enters the claim only through the secondary 2x2 — the thesis sentence
  of the protocol should be read this way (owner decision of 2026-09-23, fork 2,
  c1 x c3 as the only advance criterion).

## 8. Decision criteria (a priori)

1. **Falsifier.** Pooled over families (equal weight, `N = 64` per family,
   world-level pairing preserved in the bootstrap), B must win **both** M3 and
   M5 against A1 (paired mean difference favoring B, 95% bootstrap CI
   excluding zero) and clear the three guards:
   - **M4 per family**: `B_f <= A_f + 0.05` in **every** family (pooled M4 is
     reported, never gated) — pooling must not hide a family where B alarms
     badly;
   - **leave-one-family-out**: removing any single family must not flip the
     sign of the pooled M3 or M5 gain — otherwise one family is speaking for
     the aggregate, a profile disguised as aggregate;
   - **B− attribution**: `B - B−` positive under the same pooled test — if
     `B ≈ B−`, the gain is engineering, not structure.
   Missing M3, M5 or any guard -> the structure adds nothing in this regime:
   do not scale, report the profile.
2. **Profile, not aggregate victory.** The result is the per-family vector
   (M1..M5) plus M6, with pooled tests as the gate and per-family readings as
   diagnostics; a pooled win driven by one family is reported as such.
3. No generality claim before phase 3 shows transfer.
4. Censoring rule (§6, M3) applies to every latency metric.

## 9. Non-goals

- No causality and no interventions: the causal part of T0 (acting to change
  the world) is not exercised; no causal reading of this experiment.
- No LLM in this phase; no test of the T1 extractor or the product pipeline.
- T3 stays closed: this axis is decoupled (owner decision 2026-09-23); its
  outcome is neither a prerequisite for nor a promotion of T3.

## 10. Execution protocol

`sim/ab.py` (stdlib only) is written only at authorization; outputs
`sim/results/teo_world_v1/{episodes.jsonl,summary.json,summary.md}`; one primary
run plus a determinism rerun (byte-identical). This document is committed
first, the execution commit next.

§4 is frozen here and is **revalidated at the execution commit** against the
current E5/answerer-composition contract: if that line changed the consumer
contract between this freeze and the execution commit, §4 reopens before any
run.

## Appendix A — skeleton (specification, not runnable)

```python
# SPECIFICATION ONLY — stdlib only; not runnable until authorized.
import random
from dataclasses import dataclass, field

FAMILIES = ("linear", "const_accel", "attract", "oscill")


@dataclass(frozen=True)
class Regime:
    family: str
    params_x: tuple
    params_y: tuple  # independent from x


@dataclass
class World:
    regime: Regime
    break_at: int | None = None
    regime_after: Regime | None = None
    seed: int = 0

    def position(self, t: int) -> tuple[float, float]:
        """Deterministic truth; the agent never calls this directly."""
        ...

    def observe(self, t: int) -> tuple[float, float]:
        """Adds sigma = 1% of family scale, independent per axis."""
        ...


@dataclass
class Observation:
    t: int
    x: float
    y: float


@dataclass
class Hypothesis:
    family: str
    scope: tuple[int, int]  # declared validity window
    confidence: float
    evidence: list[int] = field(default_factory=list)
    discard_reason: str | None = None


@dataclass
class Ledger:
    """Persists across episodes: hypotheses, identities, revisions."""
    hypotheses: list[Hypothesis] = field(default_factory=list)
    revisions: list[tuple[int, str]] = field(default_factory=list)


class FlatConsumer:
    """A1: windowed least squares + sustained residual trigger."""
    ...


class CusumConsumer:
    """A2: same fitter; CUSUM-style residual monitor (robustness only)."""
    ...


class TypedConsumer:
    """B: hypothesis set + scope + evidence + discard reasons; same fitter."""
    ...


def next_observation(consumer, grid: tuple[int, ...], h_a: int) -> int:
    """Same policy in every arm within a cell."""
    ...
```

## Appendix B — frozen values (authorized 2026-09-23, then immutable)

| item | value |
|---|---|
| `T` (episode length), `H` (horizon) | 20 both (frozen; §2) |
| `theta` (on the normalized error) | 0.05 |
| `W` | 3 consecutive observations |
| grid / `H_a` | all integer steps `0..20` / `H_a = 20` |
| observation budget | `B_obs = 7` per episode, both policies |
| fixed policy Π_fixa | `t = 0, 3, 6, 9, 12, 15, 18` |
| active policy Π_ativa | first `t = 0`; then the grid time maximizing disagreement between the top-2 candidate models (ties: earliest); same heuristic in every arm |
| fit window `k_win` | 6 |
| break index | per axis, uniform in `{6..14}`, independent (`k_x != k_y` allowed); post-break rule re-anchored C0 at `k` (§2) |
| episodes per world / arm | stable (M4 control) -> break (M3) -> novel (M5) -> repeat of the world's own rule (M5) |
| M1/M2/M3 operationalization | normalized one-observation-ahead errors (prediction made before each observation); M2 = observation count until `W` consecutive errors `< theta`, right-censored at `B_obs`; M3 = observations after `max(k_x, k_y)` until `W` consecutive errors `> theta`, reported as `latency/H`, right-censored at `1.0` |
| M5 | `M2(novel) - M2(repeat)` per world; ledger persists across episodes (B only) |
| `R_fam` | `p95(|x(t) - x(0)|)` over the generated worlds under the frozen Π, `t in 0..H`, computed once before any arm runs and never recomputed |
| bootstrap | 1000 resamples within family, equal family weights, world-level pairing, seed `20260923`, percentile CI 95% |
| A2 (diagnostic) | CUSUM slack `theta`, threshold `5*theta`; never feeds A1/B |
| `N` | 64 per family |
| noise | `sigma = 1%` of `S` = 0.02 |

#### Execution record — revalidation and authorization (2026-09-23)

- §4 revalidation (§10): E5/answerer-composition closed with `both levers fail ->
  consolidation (provenance layer), no new mechanism`; the consumer contract
  relevant to §4 is unchanged and **§4 stands**.
- Identifiability floor: verified deterministically by the execution run,
  which reports pass/fail per family (no adjustment afterwards, §2).
- Authorized execution: `sim/ab.py` (stdlib only), outputs under
  `sim/results/teo_world_v1/`.

#### Execution record — results (2026-09-23)

Harness `sim/ab.py`, outputs `sim/results/teo_world_v1/`; deterministic
rerun byte-identical (`episodes.jsonl` sha256 `904ef626...`, `summary.json`
sha256 `02f862cc...`). A harness smoke run preceded this record; the only
post-smoke change was M4 faithfulness per §6 ("announced detection" = the
consumer's trigger, not the raw sustained statistic). Criteria unchanged;
both readings agreed. Identifiability floor: all four families pass
(linear 100.0 sigma, const_accel 51.5, attract 4.4, oscill 45.0).

| family | M3 c1 -> c3 | M4 c1 -> c3 | M5 c1 -> c3 (reid B) |
|---|---:|---:|---:|
| linear | 0.934 -> 0.734 | 0.016 -> 0.234 (FAIL) | 0.000 -> 0.641 (1.00) |
| const_accel | 0.894 -> 0.762 | 0.000 -> 0.688 (FAIL) | 0.000 -> 1.469 (1.00) |
| attract | 0.641 -> 0.615 | 0.172 -> 0.172 | 0.000 -> 0.531 (1.00) |
| oscill | 0.748 -> 0.761 | 0.438 -> 0.453 | 0.109 -> 0.266 (0.64) |

Pooled c3 - c1: M3 mean -0.0858 (95% CI [-0.1196, -0.0531]), M5 mean +0.6961
(95% CI [+0.5703, +0.8203]); LOFO keeps both signs for every dropped family;
B- (B's skeleton with A1's information set) is behaviorally identical to A1
on every recorded metric, so the attribution check B - B- equals B - A1 and
is positive on both metrics. M4 fails the per-family guard (linear,
const_accel): every B false alarm occurs at or before convergence
(early-commitment churn; `trigger_obs <= M2` in 100% of the flagged stable
episodes).

**Verdict (frozen §8): `advance = false` — B wins M3 and M5, passes LOFO
and the B- attribution, but misses the M4 guard; per the frozen falsifier the
structure is not scaled in this regime. The profile is the result:** typed
scope/ledger buys detection and transfer, but committing before convergence
announces changes that never happened.

Secondary (diagnostic, oscill 2x2, M1/M3/M5): c1 0.423/0.748/0.109, c2
0.833/0.231/0.000, c3 0.433/0.761/0.266, c4 0.889/0.204/-0.031 — the active
observation policy sharpens detection and destroys prediction accuracy.
A2 (CUSUM) behaves like A1 on M3/M4 (same predictor) and shows no M5 gain
(no ledger).
