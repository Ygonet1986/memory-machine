#!/usr/bin/env python3
"""teo-world-v1 — flat history vs typed records in a simulated world.

Deterministic, stdlib only, no LLM. Specification frozen in
docs/TEO_WORLD_V1_PREREG.md (94b679e); execution constants in Appendix B of
that file. Running this file is the execution commit's payload.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
from dataclasses import dataclass
from pathlib import Path

T = H = 20
SIGMA = 0.02
THETA = 0.05
W = 3
K_WIN = 6
B_OBS = 7
GRID = tuple(range(0, H + 1))
FIXED_TIMES = (0, 3, 6, 9, 12, 15, 18)
FAMILIES = ("linear", "const_accel", "attract", "oscill")
FAM_ORDER = {f: i for i, f in enumerate(FAMILIES)}
N_PER_FAMILY = 64
BREAK_LO, BREAK_HI = 6, 14
BOOT_N = 1000
BOOT_SEED = 20260923
TWO_PI = 2.0 * math.pi
CUSUM_H = 5.0 * THETA
LAMBDAS = tuple(0.10 + 0.01 * i for i in range(11))
PERIODS = (6, 8, 10, 12)
ARM_ORDER = ("c1", "c3", "c3m", "a2", "c2", "c4")
KIND_ORDER = ("stable", "broken", "novel", "repeat")


# ---------------------------------------------------------------- worlds

def draw_params(rng: random.Random, family: str) -> tuple:
    if family == "linear":
        return (rng.uniform(-0.5, 0.5), rng.choice((2.0 / T, -2.0 / T)))
    if family == "const_accel":
        c = rng.choice((-1.0, 1.0)) * rng.uniform(0.005, 0.02)
        return (rng.uniform(-0.5, 0.5), rng.choice((1.0 / T, -1.0 / T)), c)
    if family == "attract":
        return (rng.uniform(-0.5, 0.5), rng.choice((2.0, -2.0)), rng.uniform(0.10, 0.20))
    if family == "oscill":
        return (rng.uniform(-0.25, 0.25), rng.uniform(0.9, 1.0),
                rng.choice(PERIODS), rng.uniform(0.0, TWO_PI))
    raise ValueError(family)


def eval_params(family: str, p: tuple, t: float) -> float:
    if family == "linear":
        a, v = p
        return a + v * t
    if family == "const_accel":
        a, v, c = p
        return a + v * t + 0.5 * c * t * t
    if family == "attract":
        xs, d, lam = p
        return xs + d * math.exp(-lam * t)
    if family == "oscill":
        mu, amp, per, phi = p
        return mu + amp * math.sin(TWO_PI * t / per + phi)
    raise ValueError(family)


def reanchor(family: str, p: tuple, k: int, target: float) -> tuple:
    if family == "linear":
        _, v = p
        return (target - v * k, v)
    if family == "const_accel":
        _, v, c = p
        return (target - v * k - 0.5 * c * k * k, v, c)
    if family == "attract":
        xs, _, lam = p
        return (xs, target - xs, lam)
    if family == "oscill":
        mu, amp, per, _ = p
        if target - mu > 0.95 * amp:
            mu = target - 0.95 * amp
        elif target - mu < -0.95 * amp:
            mu = target + 0.95 * amp
        q = max(-1.0, min(1.0, (target - mu) / amp))
        return (mu, amp, per, math.asin(q) - TWO_PI * k / per)
    raise ValueError(family)


@dataclass(frozen=True)
class World:
    family: str
    rule0: tuple
    rule1: tuple | None
    kx: int | None
    ky: int | None
    seed: int

    def axis_rule(self, axis: int, t: int) -> tuple:
        if self.rule1 is None:
            return self.rule0[axis]
        k = self.kx if axis == 0 else self.ky
        return self.rule0[axis] if t < k else self.rule1[axis]

    def value(self, t: int) -> tuple:
        return (eval_params(self.family, self.axis_rule(0, t), t),
                eval_params(self.family, self.axis_rule(1, t), t))

    def observe(self, t: int) -> tuple:
        rng = random.Random(self.seed * 1000003 + t)
        x, y = self.value(t)
        return (x + rng.gauss(0.0, SIGMA), y + rng.gauss(0.0, SIGMA))


@dataclass(frozen=True)
class Bundle:
    stable: World
    broken: World
    novel: World


def make_broken(rng: random.Random, stable: World) -> World:
    fam = stable.family
    kx = rng.randint(BREAK_LO, BREAK_HI)
    ky = rng.randint(BREAK_LO, BREAK_HI)
    px = reanchor(fam, draw_params(rng, fam), kx, eval_params(fam, stable.rule0[0], kx))
    py = reanchor(fam, draw_params(rng, fam), ky, eval_params(fam, stable.rule0[1], ky))
    return World(fam, stable.rule0, (px, py), kx, ky, stable.seed)


def generate_bundles(family: str, seed_base: int) -> list[Bundle]:
    rng = random.Random(seed_base)
    bundles = []
    for i in range(N_PER_FAMILY):
        seed = seed_base * 1000 + i
        rule0 = (draw_params(rng, family), draw_params(rng, family))
        stable = World(family, rule0, None, None, None, seed)
        broken = make_broken(rng, stable)
        nrule = (draw_params(rng, family), draw_params(rng, family))
        novel = World(family, nrule, None, None, None, seed)
        bundles.append(Bundle(stable, broken, novel))
    return bundles


# ---------------------------------------------------------------- fitting

def solve(rows: list[tuple], ys: list[float]):
    n = len(rows[0])
    m = len(rows)
    a = [[0.0] * n for _ in range(n)]
    b = [0.0] * n
    for i in range(m):
        ri = rows[i]
        yi = ys[i]
        for r in range(n):
            rr = ri[r]
            if rr == 0.0:
                continue
            b[r] += rr * yi
            ar = a[r]
            for c in range(n):
                ar[c] += rr * ri[c]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(a[r][col]))
        if abs(a[piv][col]) < 1e-12:
            return None
        if piv != col:
            a[col], a[piv] = a[piv], a[col]
            b[col], b[piv] = b[piv], b[col]
        inv = 1.0 / a[col][col]
        for r in range(col + 1, n):
            f = a[r][col] * inv
            if f == 0.0:
                continue
            for c in range(col, n):
                a[r][c] -= f * a[col][c]
            b[r] -= f * b[col]
    x = [0.0] * n
    for r in range(n - 1, -1, -1):
        s = b[r]
        for c in range(r + 1, n):
            s -= a[r][c] * x[c]
        x[r] = s / a[r][r]
    return x


def sse_of(rows: list[tuple], ys: list[float], coef: list[float]) -> float:
    total = 0.0
    n = len(coef)
    for i in range(len(ys)):
        p = 0.0
        ri = rows[i]
        for j in range(n):
            p += ri[j] * coef[j]
        d = p - ys[i]
        total += d * d
    return total


@dataclass(frozen=True)
class Fit:
    family: str
    params: tuple
    sse: float


def fit_family(family: str, obs: list[tuple]) -> Fit | None:
    if family == "linear":
        if len(obs) < 2:
            return None
        rows = [(1.0, float(t)) for t, _ in obs]
        ys = [v for _, v in obs]
        co = solve(rows, ys)
        if co is None:
            return None
        return Fit(family, (co[0], co[1]), sse_of(rows, ys, co))
    if family == "const_accel":
        if len(obs) < 3:
            return None
        rows = [(1.0, float(t), 0.5 * t * t) for t, _ in obs]
        ys = [v for _, v in obs]
        co = solve(rows, ys)
        if co is None:
            return None
        return Fit(family, (co[0], co[1], co[2]), sse_of(rows, ys, co))
    if family == "attract":
        if len(obs) < 2:
            return None
        best_sse = math.inf
        best_params = None
        for lam in LAMBDAS:
            rows = [(1.0, math.exp(-lam * t)) for t, _ in obs]
            ys = [v for _, v in obs]
            co = solve(rows, ys)
            if co is None:
                continue
            s = sse_of(rows, ys, co)
            if s < best_sse:
                best_sse = s
                best_params = (co[0], co[1], lam)
        if best_params is None:
            return None
        return Fit(family, best_params, best_sse)
    if family == "oscill":
        if len(obs) < 3:
            return None
        best_sse = math.inf
        best_params = None
        for per in PERIODS:
            rows = [(1.0, math.sin(TWO_PI * t / per), math.cos(TWO_PI * t / per))
                    for t, _ in obs]
            ys = [v for _, v in obs]
            co = solve(rows, ys)
            if co is None:
                continue
            s = sse_of(rows, ys, co)
            if s < best_sse:
                best_sse = s
                amp = math.hypot(co[1], co[2])
                phi = math.atan2(co[2], co[1])
                best_params = (co[0], amp, per, phi)
        if best_params is None:
            return None
        return Fit(family, best_params, best_sse)
    raise ValueError(family)


def fit_all(obs: list[tuple]) -> list[Fit]:
    out = []
    for fam in FAMILIES:
        f = fit_family(fam, obs)
        if f is not None:
            out.append(f)
    out.sort(key=lambda f: (f.sse, FAM_ORDER[f.family]))
    return out


def predict_params(family: str, params: tuple, t: float) -> float:
    return eval_params(family, params, t)


# ---------------------------------------------------------------- consumers

class FlatConsumer:
    """A1: last-k window refit over the four families + sustained trigger."""

    def __init__(self) -> None:
        self.obs: list[tuple] = []
        self.triggered = False
        self.trigger_obs: int | None = None
        self.run = 0

    def start_episode(self) -> None:
        self.obs = []
        self.triggered = False
        self.trigger_obs = None
        self.run = 0

    def candidates(self, t: float) -> list[tuple]:
        ox = [(tt, v[0]) for tt, v in self.obs][-K_WIN:]
        oy = [(tt, v[1]) for tt, v in self.obs][-K_WIN:]
        fx = fit_all(ox) if len(ox) >= 2 else []
        fy = fit_all(oy) if len(oy) >= 2 else []
        if not fx or not fy:
            return []
        pairs = [(predict_params(fx[0].family, fx[0].params, t),
                  predict_params(fy[0].family, fy[0].params, t))]
        if len(fx) > 1 and len(fy) > 1:
            pairs.append((predict_params(fx[1].family, fx[1].params, t),
                          predict_params(fy[1].family, fy[1].params, t)))
        return pairs

    def predict(self, t: float):
        cands = self.candidates(t)
        return cands[0] if cands else None

    def observe(self, t: int, value: tuple, err: float | None) -> None:
        self.obs.append((t, value))
        if err is not None:
            if err > THETA:
                self.run += 1
            else:
                self.run = 0
            if self.run >= W:
                self.triggered = True
                if self.trigger_obs is None:
                    self.trigger_obs = len(self.obs)


class CusumConsumer(FlatConsumer):
    """A2: same fitter; CUSUM-style residual monitor (diagnostic only)."""

    def start_episode(self) -> None:
        super().start_episode()
        self.cusum = 0.0
        self.cusum_triggered = False

    def observe(self, t: int, value: tuple, err: float | None) -> None:
        super().observe(t, value, err)
        if err is not None:
            self.cusum = max(0.0, self.cusum + (err - THETA))
            if self.cusum > CUSUM_H:
                self.cusum_triggered = True
                self.cusum = 0.0


@dataclass
class Hypothesis:
    family: str
    params_x: tuple
    params_y: tuple
    scope_start: int
    scope_end: int
    reason: str | None = None


class TypedConsumer:
    """B: hypotheses with scope/confidence/evidence + ledger (typed=True).

    With typed=False it is the matched ablation B- (B's skeleton, A1's
    information set: window refit, sustained trigger, no ledger, no reasons).
    """

    def __init__(self, typed: bool) -> None:
        self.typed = typed
        self.ledger: list[Hypothesis] = []
        self.obs: list[tuple] = []
        self.active: Hypothesis | None = None
        self.run = 0
        self.triggered = False
        self.trigger_obs: int | None = None
        self.discards: list[str] = []
        self.reidentified = False

    def start_episode(self) -> None:
        self.obs = []
        self.active = None
        self.run = 0
        self.triggered = False
        self.trigger_obs = None
        self.discards = []
        self.reidentified = False

    def _fit_hyp(self, family: str, scope_start: int, scope_end: int) -> Hypothesis | None:
        win = self.obs[scope_start:scope_end + 1]
        ax = [(t, v[0]) for t, v in win]
        ay = [(t, v[1]) for t, v in win]
        fx = fit_family(family, ax)
        fy = fit_family(family, ay)
        if fx is None or fy is None:
            return None
        return Hypothesis(family, fx.params, fy.params, scope_start, scope_end)

    def candidates(self, t: float) -> list[tuple]:
        pairs: list[tuple] = []
        if self.typed and self.active is not None:
            h = self.active
            pairs.append((predict_params(h.family, h.params_x, t),
                          predict_params(h.family, h.params_y, t)))
            win = self.obs[-K_WIN:]
            ax = [(tt, v[0]) for tt, v in win]
            ay = [(tt, v[1]) for tt, v in win]
            best_fam = None
            best_sse = math.inf
            best = None
            for fam in FAMILIES:
                fx = fit_family(fam, ax)
                fy = fit_family(fam, ay)
                if fx is None or fy is None:
                    continue
                s = fx.sse + fy.sse
                if s < best_sse:
                    best_sse = s
                    best_fam = fam
                    best = (fx.params, fy.params)
            if best is not None and best_fam is not None:
                pairs.append((predict_params(best_fam, best[0], t),
                              predict_params(best_fam, best[1], t)))
            return pairs
        ox = [(tt, v[0]) for tt, v in self.obs][-K_WIN:]
        oy = [(tt, v[1]) for tt, v in self.obs][-K_WIN:]
        fx = fit_all(ox) if len(ox) >= 2 else []
        fy = fit_all(oy) if len(oy) >= 2 else []
        if not fx or not fy:
            return []
        pairs.append((predict_params(fx[0].family, fx[0].params, t),
                      predict_params(fy[0].family, fy[0].params, t)))
        if len(fx) > 1 and len(fy) > 1:
            pairs.append((predict_params(fx[1].family, fx[1].params, t),
                          predict_params(fy[1].family, fy[1].params, t)))
        return pairs

    def predict(self, t: float):
        if self.typed and self.active is not None:
            refit = self._fit_hyp(self.active.family, self.active.scope_start,
                                  self.active.scope_end)
            if refit is not None:
                self.active.params_x = refit.params_x
                self.active.params_y = refit.params_y
            h = self.active
            return (predict_params(h.family, h.params_x, t),
                    predict_params(h.family, h.params_y, t))
        cands = self.candidates(t)
        return cands[0] if cands else None

    def _try_ledger(self, norm: float) -> bool:
        if not self.typed or not self.ledger or len(self.obs) < 2:
            return False
        first = self.obs[:2]
        for h in reversed(self.ledger):
            ok = True
            for tt, (vx, vy) in first:
                ex = abs(predict_params(h.family, h.params_x, tt) - vx)
                ey = abs(predict_params(h.family, h.params_y, tt) - vy)
                if (ex + ey) / (2.0 * norm) > THETA:
                    ok = False
                    break
            if ok:
                adopted = Hypothesis(h.family, h.params_x, h.params_y, 0, len(self.obs) - 1)
                self.active = adopted
                self.ledger.append(adopted)
                self.reidentified = True
                return True
        return False

    def _adopt_fresh(self) -> None:
        win = self.obs[-K_WIN:]
        ax = [(tt, v[0]) for tt, v in win]
        ay = [(tt, v[1]) for tt, v in win]
        best_fam = None
        best_sse = math.inf
        best = None
        for fam in FAMILIES:
            fx = fit_family(fam, ax)
            fy = fit_family(fam, ay)
            if fx is None or fy is None:
                continue
            s = fx.sse + fy.sse
            if s < best_sse:
                best_sse = s
                best_fam = fam
                best = (fx.params, fy.params)
        if best is None:
            return
        start = max(0, len(self.obs) - K_WIN)
        h = Hypothesis(best_fam, best[0], best[1], start, len(self.obs) - 1)
        self.active = h
        self.ledger.append(h)

    def _discard_and_adopt(self) -> None:
        win = self.obs[-K_WIN:]
        ax = [(tt, v[0]) for tt, v in win]
        ay = [(tt, v[1]) for tt, v in win]
        old = self.active
        if old is None:
            return
        old_sse = 0.0
        for tt, (vx, vy) in win:
            dx = predict_params(old.family, old.params_x, tt) - vx
            dy = predict_params(old.family, old.params_y, tt) - vy
            old_sse += dx * dx + dy * dy
        best_fam = None
        best_sse = math.inf
        best = None
        for fam in FAMILIES:
            fx = fit_family(fam, ax)
            fy = fit_family(fam, ay)
            if fx is None or fy is None:
                continue
            s = fx.sse + fy.sse
            if s < best_sse:
                best_sse = s
                best_fam = fam
                best = (fx.params, fy.params)
        if best is None:
            return
        if best_sse < old_sse:
            reason = f"sustained violation; {best_fam} fits window better"
            self.discards.append(reason)
            old.reason = reason
            start = max(0, len(self.obs) - K_WIN)
            new = Hypothesis(best_fam, best[0], best[1], start, len(self.obs) - 1)
            self.active = new
            self.ledger.append(new)
            self.run = 0

    def observe(self, t: int, value: tuple, err: float | None, norm: float = 1.0) -> None:
        self.obs.append((t, value))
        n = len(self.obs)
        if self.typed:
            if self.active is None:
                if self._try_ledger(norm):
                    return
                if n >= 4:
                    self._adopt_fresh()
                return
            if err is not None:
                if err > THETA:
                    self.run += 1
                    if self.run >= W:
                        self._discard_and_adopt()
                        if self.discards:
                            self.triggered = True
                            if self.trigger_obs is None:
                                self.trigger_obs = len(self.obs)
                else:
                    self.run = 0
                    if n - 1 > self.active.scope_end:
                        self.active.scope_end = n - 1
            return
        # B- path: A1 information set
        if err is not None:
            if err > THETA:
                self.run += 1
            else:
                self.run = 0
            if self.run >= W:
                self.triggered = True
                if self.trigger_obs is None:
                    self.trigger_obs = len(self.obs)


# ---------------------------------------------------------------- episodes

def choose_next(consumer, last_t: int, remaining: int) -> int:
    cap = H - (remaining - 1)
    best_t = None
    best_score = -1.0
    for t in GRID:
        if t <= last_t or t > cap:
            continue
        cands = consumer.candidates(float(t))
        if len(cands) >= 2:
            p1, p2 = cands[0], cands[1]
            score = abs(p1[0] - p2[0]) + abs(p1[1] - p2[1])
        else:
            score = 0.0
        if score > best_score + 1e-12:
            best_score = score
            best_t = t
    if best_t is None:
        best_t = cap if cap > last_t else last_t + 1
    return best_t


@dataclass
class EpResult:
    kind: str
    m1_mae: float | None
    m1_rmse: float | None
    m1k_mae: float | None
    m2: int
    detected: bool
    triggered: bool
    trigger_obs: int | None
    m3: float | None
    discards: int
    discards_with_reason: int
    reidentified: bool


def run_episode(consumer, world: World, kind: str, policy: str,
                norm: float) -> EpResult:
    consumer.start_episode()
    errors: list[tuple[int, float, int]] = []
    k_errors: list[float] = []
    pending3: dict[int, tuple] = {}
    last_t = 0
    for step in range(B_OBS):
        if policy == "fixed":
            t = FIXED_TIMES[step]
        elif step == 0:
            t = 0
        else:
            t = choose_next(consumer, last_t, B_OBS - step)
        last_t = t
        pred = consumer.predict(float(t))
        vx, vy = world.observe(t)
        err = None
        if pred is not None:
            err = (abs(pred[0] - vx) + abs(pred[1] - vy)) / (2.0 * norm)
            errors.append((step, err, t))
            if t in pending3:
                p3 = pending3.pop(t)
                k_errors.append((abs(p3[0] - vx) + abs(p3[1] - vy)) / (2.0 * norm))
            if t + 3 <= H:
                pending3[t + 3] = pred
        if isinstance(consumer, TypedConsumer):
            consumer.observe(t, (vx, vy), err, norm)
        else:
            consumer.observe(t, (vx, vy), err)
    m1_mae = sum(e for _, e, _ in errors) / len(errors) if errors else None
    m1_rmse = math.sqrt(sum(e * e for _, e, _ in errors) / len(errors)) if errors else None
    m1k_mae = sum(k_errors) / len(k_errors) if k_errors else None
    m2 = B_OBS
    for i in range(len(errors)):
        if i + 1 >= W and all(errors[i - j][1] < THETA for j in range(W)):
            m2 = min(B_OBS, errors[i][0] + 1)
            break
    detected = False
    for i in range(len(errors)):
        if i + 1 >= W and all(errors[i - j][1] > THETA for j in range(W)):
            detected = True
            break
    m3 = None
    if kind == "broken":
        k_max = max(world.kx or 0, world.ky or 0)
        count = 0
        run = 0
        found = None
        for _, e, t in errors:
            if t <= k_max:
                continue
            count += 1
            if e > THETA:
                run += 1
            else:
                run = 0
            if run >= W:
                found = count / H
                break
        m3 = 1.0 if found is None else found
    discards = len(consumer.discards) if isinstance(consumer, TypedConsumer) else 0
    with_reason = len([r for r in consumer.discards if r]) if isinstance(consumer, TypedConsumer) else 0
    reidentified = bool(getattr(consumer, "reidentified", False))
    triggered = bool(getattr(consumer, "triggered", False))
    trigger_obs = getattr(consumer, "trigger_obs", None)
    return EpResult(kind, m1_mae, m1_rmse, m1k_mae, m2, detected, triggered,
                    trigger_obs, m3, discards, with_reason, reidentified)


# ---------------------------------------------------------------- stats

def percentile(sorted_vals: list[float], q: float) -> float:
    if not sorted_vals:
        return float("nan")
    k = (len(sorted_vals) - 1) * q
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return sorted_vals[int(k)]
    return sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f)


def r_fam_of(bundles: list[Bundle]) -> float:
    vals = []
    for b in bundles:
        w = b.stable
        for axis in (0, 1):
            base = eval_params(w.family, w.rule0[axis], 0)
            for t in GRID:
                vals.append(abs(eval_params(w.family, w.rule0[axis], t) - base))
    vals.sort()
    return percentile(vals, 0.95)


def floor_of(family: str, bundles: list[Bundle]) -> dict:
    vals = []
    if family == "linear":
        for b in bundles:
            for axis in (0, 1):
                _, v = b.stable.rule0[axis]
                vals.append(abs(v) * H)
        term = "|v|*H"
    elif family == "const_accel":
        for b in bundles:
            for axis in (0, 1):
                _, _, c = b.stable.rule0[axis]
                vals.append(0.5 * abs(c) * H * H)
        term = "|c|*H^2/2"
    elif family == "attract":
        for b in bundles:
            for axis in (0, 1):
                _, d, lam = b.stable.rule0[axis]
                vals.append(abs(d) * (lam * H / 2.0) ** 3 / 24.0)
        term = "|d|*(lambda*H/2)^3/24"
    elif family == "oscill":
        for b in bundles:
            for axis in (0, 1):
                _, amp, _, _ = b.stable.rule0[axis]
                vals.append(amp)
        term = "A (against a constant fit)"
    else:
        raise ValueError(family)
    vmin = min(vals)
    return {"term": term, "min": vmin, "pass": vmin >= 4.0 * SIGMA,
            "in_sigma": vmin / SIGMA}


def bootstrap_ci(diffs: dict[str, list[float]], seed: int) -> dict:
    rng = random.Random(seed)
    fams = [f for f in FAMILIES if len(diffs.get(f, [])) > 0]
    if not fams:
        return {"mean": float("nan"), "lo": float("nan"), "hi": float("nan")}
    means = []
    for _ in range(BOOT_N):
        total = 0.0
        for fam in fams:
            vals = diffs[fam]
            k = len(vals)
            s = 0.0
            for _ in range(k):
                s += vals[rng.randrange(k)]
            total += s / k
        means.append(total / len(fams))
    means.sort()
    return {"mean": sum(means) / len(means),
            "lo": percentile(means, 0.025),
            "hi": percentile(means, 0.975)}


def pooled_mean(diffs: dict[str, list[float]]) -> float:
    fams = [f for f in FAMILIES if len(diffs.get(f, [])) > 0]
    if not fams:
        return float("nan")
    return sum(sum(diffs[f]) / len(diffs[f]) for f in fams) / len(fams)


def lofo_means(diffs: dict[str, list[float]]) -> dict:
    out = {}
    for drop in FAMILIES:
        fams = [f for f in FAMILIES if f != drop and len(diffs.get(f, [])) > 0]
        if not fams:
            continue
        out[drop] = sum(sum(diffs[f]) / len(diffs[f]) for f in fams) / len(fams)
    return out


# ---------------------------------------------------------------- main

def run_arm(arm: str, families: list[str], bundles_by_family: dict,
            rfam: dict[str, float]) -> dict:
    policy = "active" if arm in ("c2", "c4") else "fixed"
    per_family: dict[str, dict] = {}
    for family in families:
        if arm == "c1":
            consumer = FlatConsumer()
        elif arm == "c2":
            consumer = FlatConsumer()
        elif arm == "c3":
            consumer = TypedConsumer(typed=True)
        elif arm == "c3m":
            consumer = TypedConsumer(typed=False)
        elif arm == "c4":
            consumer = TypedConsumer(typed=True)
        elif arm == "a2":
            consumer = CusumConsumer()
        else:
            raise ValueError(arm)
        worlds = bundles_by_family[family]
        rows = []
        for bi, b in enumerate(worlds):
            stable = run_episode(consumer, b.stable, "stable", policy, rfam[family])
            broken = run_episode(consumer, b.broken, "broken", policy, rfam[family])
            novel = run_episode(consumer, b.novel, "novel", policy, rfam[family])
            repeat = run_episode(consumer, b.stable, "repeat", policy, rfam[family])
            rows.append({
                "world": bi,
                "seed": b.stable.seed,
                "m1": stable.m1_mae,
                "m3": broken.m3,
                "m5": novel.m2 - repeat.m2,
                "m4": 1 if stable.triggered else 0,
                "m4_sustained": 1 if stable.detected else 0,
                "trigger_obs": stable.trigger_obs,
                "m2_stable": stable.m2,
                "m2_novel": novel.m2,
                "m2_repeat": repeat.m2,
                "reid": repeat.reidentified,
                "discards": broken.discards + stable.discards + novel.discards + repeat.discards,
                "cusum_m4": (1 if getattr(stable, "cusum_triggered", False) else 0)
                if isinstance(consumer, CusumConsumer) else None,
            })
        per_family[family] = rows
    return per_family


def summarize_arm(per_family: dict) -> dict:
    out = {}
    for family, rows in per_family.items():
        m1 = [r["m1"] for r in rows if r["m1"] is not None]
        out[family] = {
            "m1_mean": sum(m1) / len(m1) if m1 else None,
            "m3_mean": sum(r["m3"] for r in rows) / len(rows),
            "m4_rate": sum(r["m4"] for r in rows) / len(rows),
            "m4_sustained_rate": sum(r["m4_sustained"] for r in rows) / len(rows),
            "early_churn_rate": sum(
                1 for r in rows
                if r["trigger_obs"] is not None and r["trigger_obs"] <= r["m2_stable"]
            ) / len(rows),
            "m5_mean": sum(r["m5"] for r in rows) / len(rows),
            "m2_novel_mean": sum(r["m2_novel"] for r in rows) / len(rows),
            "m2_repeat_mean": sum(r["m2_repeat"] for r in rows) / len(rows),
            "reid_rate": sum(1 for r in rows if r["reid"]) / len(rows),
        }
    return out


def paired_diffs(a: dict, b: dict, key: str) -> dict:
    diffs = {}
    for family in FAMILIES:
        if family not in a:
            continue
        rows_a = a[family]
        rows_b = b[family]
        diffs[family] = [ra[key] - rb[key] for ra, rb in zip(rows_a, rows_b)]
    return diffs


def build_summary(bundles_by_family: dict, rfam: dict, results: dict) -> dict:
    arms = {}
    for arm in ARM_ORDER:
        arms[arm] = summarize_arm(results[arm])

    d3 = paired_diffs(results["c3"], results["c1"], "m3")
    d5 = paired_diffs(results["c3"], results["c1"], "m5")
    d3m = paired_diffs(results["c3"], results["c3m"], "m3")
    d5m = paired_diffs(results["c3"], results["c3m"], "m5")

    m3_ci = bootstrap_ci(d3, BOOT_SEED)
    m5_ci = bootstrap_ci(d5, BOOT_SEED)
    m3m_ci = bootstrap_ci(d3m, BOOT_SEED)
    m5m_ci = bootstrap_ci(d5m, BOOT_SEED)

    lofo_m3 = lofo_means(d3)
    lofo_m5 = lofo_means(d5)

    m4_guard = True
    m4_rows = {}
    for family in FAMILIES:
        a = arms["c1"][family]["m4_rate"]
        b = arms["c3"][family]["m4_rate"]
        ok = b <= a + 0.05 + 1e-12
        m4_rows[family] = {"c1": a, "c3": b, "ok": ok}
        if not ok:
            m4_guard = False

    m3_win = m3_ci["hi"] < 0.0
    m5_win = m5_ci["lo"] > 0.0
    lofo_ok = all(v < 0.0 for v in lofo_m3.values()) and \
        all(v > 0.0 for v in lofo_m5.values())
    bminus_ok = m3m_ci["hi"] < 0.0 and m5m_ci["lo"] > 0.0
    advance = bool(m3_win and m5_win and m4_guard and lofo_ok and bminus_ok)

    floor = {fam: floor_of(fam, bundles_by_family[fam]) for fam in FAMILIES}

    osc = {}
    for arm in ("c1", "c2", "c3", "c4"):
        s = arms[arm].get("oscill")
        if s:
            osc[arm] = {"m1_mean": s["m1_mean"], "m3_mean": s["m3_mean"],
                        "m5_mean": s["m5_mean"]}

    return {
        "constants": {
            "T": T, "H": H, "SIGMA": SIGMA, "THETA": THETA, "W": W,
            "K_WIN": K_WIN, "B_OBS": B_OBS, "N_PER_FAMILY": N_PER_FAMILY,
            "FIXED_TIMES": list(FIXED_TIMES), "BREAK_RANGE": [BREAK_LO, BREAK_HI],
            "BOOT_N": BOOT_N, "BOOT_SEED": BOOT_SEED,
        },
        "R_fam": rfam,
        "floor": floor,
        "arms": arms,
        "pooled": {
            "m3": {"ci": m3_ci, "lofo": lofo_m3},
            "m5": {"ci": m5_ci, "lofo": lofo_m5},
        },
        "bminus": {"m3": m3m_ci, "m5": m5m_ci},
        "m4": m4_rows,
        "secondary_2x2_oscill": osc,
        "gate": {
            "m3_win": m3_win, "m5_win": m5_win, "m4_guard": m4_guard,
            "lofo_ok": lofo_ok, "bminus_ok": bminus_ok, "advance": advance,
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="sim/results/teo_world_v1")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    families = list(FAMILIES)
    bundles_by_family = {fam: generate_bundles(fam, 20260923 * 10 + i)
                         for i, fam in enumerate(FAMILIES)}
    rfam = {fam: r_fam_of(bundles_by_family[fam]) for fam in FAMILIES}

    results = {}
    for arm in ARM_ORDER:
        fams = ["oscill"] if arm in ("c2", "c4") else families
        results[arm] = run_arm(arm, fams, bundles_by_family, rfam)

    summary = build_summary(bundles_by_family, rfam, results)

    with open(out / "episodes.jsonl", "w", encoding="utf-8") as fh:
        for arm in ARM_ORDER:
            for family, rows in results[arm].items():
                for r in rows:
                    fh.write(json.dumps({"arm": arm, "family": family, **r},
                                        sort_keys=True) + "\n")
    (out / "summary.json").write_text(
        json.dumps(summary, indent=1, sort_keys=True) + "\n", encoding="utf-8")

    h_e = hashlib.sha256((out / "episodes.jsonl").read_bytes()).hexdigest()
    h_s = hashlib.sha256((out / "summary.json").read_bytes()).hexdigest()
    lines = []
    lines.append("# teo-world-v1 — execution summary")
    lines.append("")
    lines.append(f"- episodes.jsonl sha256: `{h_e}`")
    lines.append(f"- summary.json sha256: `{h_s}`")
    lines.append("")
    lines.append("## Identifiability floor (>= 4 sigma; sigma=0.02)")
    for fam in FAMILIES:
        f = summary["floor"][fam]
        lines.append(f"- {fam}: min {f['term']} = {f['min']:.4f} "
                     f"({f['in_sigma']:.2f} sigma) -> {'pass' if f['pass'] else 'FAIL'}")
    lines.append("")
    lines.append("## R_fam (p95 realized reach)")
    for fam in FAMILIES:
        lines.append(f"- {fam}: {summary['R_fam'][fam]:.4f}")
    lines.append("")
    lines.append("## Pooled primary (c3 - c1; M3 negative/lower is better, M5 positive is better)")
    lines.append(f"- M3 diff mean={summary['pooled']['m3']['ci']['mean']:.4f} "
                 f"CI=[{summary['pooled']['m3']['ci']['lo']:.4f}, "
                 f"{summary['pooled']['m3']['ci']['hi']:.4f}]")
    lines.append(f"- M5 diff mean={summary['pooled']['m5']['ci']['mean']:.4f} "
                 f"CI=[{summary['pooled']['m5']['ci']['lo']:.4f}, "
                 f"{summary['pooled']['m5']['ci']['hi']:.4f}]")
    lines.append(f"- B- attribution M3 mean={summary['bminus']['m3']['mean']:.4f} "
                 f"CI=[{summary['bminus']['m3']['lo']:.4f}, {summary['bminus']['m3']['hi']:.4f}]")
    lines.append(f"- B- attribution M5 mean={summary['bminus']['m5']['mean']:.4f} "
                 f"CI=[{summary['bminus']['m5']['lo']:.4f}, {summary['bminus']['m5']['hi']:.4f}]")
    lines.append("")
    lines.append("## Per-family profile (m1, m3, m4, m5)")
    for fam in FAMILIES:
        a = summary["arms"]["c1"][fam]
        b = summary["arms"]["c3"][fam]
        lines.append(f"- {fam}: A1 m1={a['m1_mean']:.4f} m3={a['m3_mean']:.4f} "
                     f"m4={a['m4_rate']:.3f} m5={a['m5_mean']:.3f} | "
                     f"B m1={b['m1_mean']:.4f} m3={b['m3_mean']:.4f} "
                     f"m4={b['m4_rate']:.3f} m5={b['m5_mean']:.3f} "
                     f"(reid={b['reid_rate']:.3f})")
    lines.append("")
    lines.append("M4 = announced detection (consumer trigger; §6). "
                 "Sustained-statistic reading reported as m4_sustained in summary.json.")
    lines.append("")
    lines.append("## Gate")
    g = summary["gate"]
    lines.append(f"- m3_win={g['m3_win']} m5_win={g['m5_win']} m4_guard={g['m4_guard']} "
                 f"lofo_ok={g['lofo_ok']} bminus_ok={g['bminus_ok']}")
    lines.append(f"- advance = **{g['advance']}**")
    lines.append("")
    (out / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
