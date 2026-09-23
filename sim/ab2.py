#!/usr/bin/env python3
"""teo-world-v2 execution — candidate/adopted/in-review state machine.

Spec: docs/TEO_WORLD_V2_PREREG.md (reserved seed base 20260926). Stdlib only,
deterministic, no LLM. Imports the round-1 harness (sim/ab.py) for worlds,
fitting and statistics; only the typed consumer and its runner are new.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ab  # noqa: E402

V_LOCAL = 2
V_MEM = 3
L_POOL = 8
RESERVED_BASE = 20260926
ARM_ORDER = ("c1", "c3", "c3m")
KINDS = ("stable", "broken", "novel", "repeat")


@dataclass
class Cand:
    family: str
    params_x: tuple
    params_y: tuple
    source: str
    order: int
    counter: int = 0
    need: int = 2


class V2Consumer:
    """Candidate / adopted / in-review under the same budget."""

    def __init__(self) -> None:
        self.ledger: list[tuple] = []  # (family, px, py), most recent last
        self.obs: list[tuple] = []
        self.cands: list[Cand] = []
        self.window_cand: Cand | None = None
        self.adopted: Cand | None = None
        self.in_review = False
        self.run = 0
        self.pending: list[tuple[Cand, tuple]] = []
        self.review_events: list[int] = []
        self.adoptions: list[int] = []
        self.reidentified = False

    def start_episode(self) -> None:
        self.obs = []
        self.adopted = None
        self.in_review = False
        self.run = 0
        self.pending = []
        self.review_events = []
        self.adoptions = []
        self.reidentified = False
        self.cands = []
        for order, (fam, px, py) in enumerate(reversed(self.ledger[-L_POOL:])):
            self.cands.append(Cand(fam, px, py, "ledger", order, need=V_MEM))
        self.window_cand = None

    def _window_fit(self) -> Cand | None:
        if len(self.obs) < 4:
            return None
        win = self.obs[-ab.K_WIN:]
        ax = [(t, v[0]) for t, v in win]
        ay = [(t, v[1]) for t, v in win]
        best_fam = None
        best_sse = math.inf
        best = None
        for fam in ab.FAMILIES:
            fx = ab.fit_family(fam, ax)
            fy = ab.fit_family(fam, ay)
            if fx is None or fy is None:
                continue
            s = fx.sse + fy.sse
            if s < best_sse:
                best_sse = s
                best_fam = fam
                best = (fx.params, fy.params)
        if best is None:
            return None
        return Cand(best_fam, best[0], best[1], "window", -1)

    def _provisional(self, t: float):
        win = self.obs[-ab.K_WIN:]
        if len(win) < 2:
            return None
        ax = [(tt, v[0]) for tt, v in win]
        ay = [(tt, v[1]) for tt, v in win]
        fx = ab.fit_all(ax)
        fy = ab.fit_all(ay)
        if not fx or not fy:
            return None
        return (ab.predict_params(fx[0].family, fx[0].params, t),
                ab.predict_params(fy[0].family, fy[0].params, t))

    def _primary(self) -> Cand | None:
        if self.adopted is not None and not self.in_review:
            return self.adopted
        pool = [c for c in self.cands if c.counter > 0]
        if pool:
            pool = pool + [self.window_cand] if self.window_cand else pool
        else:
            pool = list(self.cands)
            if self.window_cand is not None:
                pool.append(self.window_cand)
        if not pool:
            return None
        pool.sort(key=lambda c: (-c.counter, 0 if c.source == "window" else 1, c.order))
        return pool[0]

    def predict(self, t: float):
        if self.window_cand is None or self.window_cand.counter == 0:
            wf = self._window_fit()
            if wf is not None:
                self.window_cand = wf
        self.pending = []
        for c in list(self.cands) + ([self.window_cand] if self.window_cand else []):
            self.pending.append((c, (ab.predict_params(c.family, c.params_x, t),
                                     ab.predict_params(c.family, c.params_y, t))))
        if self.adopted is not None and not self.in_review:
            a = self.adopted
            return (ab.predict_params(a.family, a.params_x, t),
                    ab.predict_params(a.family, a.params_y, t))
        p = self._primary()
        if p is not None:
            return (ab.predict_params(p.family, p.params_x, t),
                    ab.predict_params(p.family, p.params_y, t))
        return self._provisional(t)

    def _adopt(self, c: Cand) -> None:
        self.adopted = Cand(c.family, c.params_x, c.params_y, c.source, c.order)
        self.ledger.append((c.family, c.params_x, c.params_y))
        self.adoptions.append(len(self.obs))
        if c.source == "ledger":
            self.reidentified = True
        self.in_review = False
        self.run = 0

    def observe(self, t: int, value: tuple, err: float | None, norm: float) -> None:
        self.obs.append((t, value))
        # 1) candidate validation from the pre-observation snapshot
        for c, pred in self.pending:
            e = (abs(pred[0] - value[0]) + abs(pred[1] - value[1])) / (2.0 * norm)
            c.counter = c.counter + 1 if e < ab.THETA else 0
        self.pending = []
        # 2) adoption when a candidate validates
        if self.adopted is None or self.in_review:
            pool = list(self.cands) + ([self.window_cand] if self.window_cand else [])
            pool.sort(key=lambda c: (-c.counter, 0 if c.source == "window" else 1, c.order))
            for c in pool:
                if c.counter >= c.need:
                    self._adopt(c)
                    break
        # 3) adopted-rule violation bookkeeping
        if self.adopted is not None and not self.in_review and err is not None:
            if err > ab.THETA:
                self.run += 1
                if self.run >= ab.W:
                    self.in_review = True
                    self.review_events.append(len(self.obs))
                    self.run = 0
                    for c in self.cands:
                        c.counter = 0
                    if self.window_cand is not None:
                        self.window_cand.counter = 0
            else:
                self.run = 0


def run_episode_v2(consumer: V2Consumer, world: ab.World, kind: str,
                   policy: str, norm: float) -> dict:
    consumer.start_episode()
    errors: list[tuple[int, float, int]] = []
    pending3: dict[int, tuple] = {}
    last_t = 0
    for step in range(ab.B_OBS):
        if policy == "fixed":
            t = ab.FIXED_TIMES[step]
        else:
            t = 0 if step == 0 else ab.choose_next(consumer, last_t, ab.B_OBS - step)
        last_t = t
        pred = consumer.predict(float(t))
        vx, vy = world.observe(t)
        err = None
        if pred is not None:
            err = (abs(pred[0] - vx) + abs(pred[1] - vy)) / (2.0 * norm)
            errors.append((step, err, t))
            if t in pending3:
                pending3.pop(t)
            if t + 3 <= ab.H:
                pending3[t + 3] = pred
        consumer.observe(t, (vx, vy), err, norm)
    m1_mae = sum(e for _, e, _ in errors) / len(errors) if errors else None
    m2 = ab.B_OBS
    for i in range(len(errors)):
        if i + 1 >= ab.W and all(errors[i - j][1] < ab.THETA for j in range(ab.W)):
            m2 = min(ab.B_OBS, errors[i][0] + 1)
            break
    detected = False
    for i in range(len(errors)):
        if i + 1 >= ab.W and all(errors[i - j][1] > ab.THETA for j in range(ab.W)):
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
            if e > ab.THETA:
                run += 1
            else:
                run = 0
            if run >= ab.W:
                found = count / ab.H
                break
        m3 = 1.0 if found is None else found
    announced = bool(consumer.review_events)
    trigger_obs = consumer.review_events[0] if consumer.review_events else None
    return {
        "m1": m1_mae,
        "m2": m2,
        "detected": detected,
        "m3": m3,
        "m4": 1 if announced else 0,
        "m4_sustained": 1 if detected else 0,
        "trigger_obs": trigger_obs,
        "adoptions": list(consumer.adoptions),
        "reviews": list(consumer.review_events),
        "reid": consumer.reidentified,
    }


def run_arm_v2(arm: str, families: list[str], bundles_by_family: dict,
               rfam: dict[str, float]) -> dict:
    per_family: dict[str, dict] = {}
    for family in families:
        worlds = bundles_by_family[family]
        rows = []
        if arm == "c3":
            consumer = V2Consumer()
            for bi, b in enumerate(worlds):
                eps = {}
                for kind, world in (("stable", b.stable), ("broken", b.broken),
                                    ("novel", b.novel), ("repeat", b.stable)):
                    eps[kind] = run_episode_v2(consumer, world, kind, "fixed", rfam[family])
                rows.append({
                    "world": bi, "seed": b.stable.seed,
                    "m1": eps["stable"]["m1"], "m3": eps["broken"]["m3"],
                    "m5": eps["novel"]["m2"] - eps["repeat"]["m2"],
                    "m4": eps["stable"]["m4"], "m4_sustained": eps["stable"]["m4_sustained"],
                    "trigger_obs": eps["stable"]["trigger_obs"],
                    "m2_stable": eps["stable"]["m2"],
                    "m2_novel": eps["novel"]["m2"], "m2_repeat": eps["repeat"]["m2"],
                    "reid": eps["repeat"]["reid"],
                    "adopt_counts": {k: len(eps[k]["adoptions"]) for k in KINDS},
                    "first_adopt": {k: (eps[k]["adoptions"][0] if eps[k]["adoptions"] else None)
                                    for k in KINDS},
                    "review_counts": {k: len(eps[k]["reviews"]) for k in KINDS},
                })
        else:
            consumer = ab.FlatConsumer() if arm == "c1" else ab.TypedConsumer(typed=False)
            for bi, b in enumerate(worlds):
                stable = ab.run_episode(consumer, b.stable, "stable", "fixed", rfam[family])
                broken = ab.run_episode(consumer, b.broken, "broken", "fixed", rfam[family])
                novel = ab.run_episode(consumer, b.novel, "novel", "fixed", rfam[family])
                repeat = ab.run_episode(consumer, b.stable, "repeat", "fixed", rfam[family])
                rows.append({
                    "world": bi, "seed": b.stable.seed,
                    "m1": stable.m1_mae, "m3": broken.m3,
                    "m5": novel.m2 - repeat.m2,
                    "m4": 1 if stable.triggered else 0,
                    "m4_sustained": 1 if stable.detected else 0,
                    "trigger_obs": stable.trigger_obs,
                    "m2_stable": stable.m2, "m2_novel": novel.m2, "m2_repeat": repeat.m2,
                    "reid": False,
                    "adopt_counts": {k: 0 for k in KINDS},
                    "first_adopt": {k: None for k in KINDS},
                    "review_counts": {k: 0 for k in KINDS},
                })
        per_family[family] = rows
    return per_family


def summarize_v2(per_family: dict) -> dict:
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
            "adopt_mean": {k: sum(r["adopt_counts"][k] for r in rows) / len(rows)
                           for k in KINDS},
            "first_adopt_mean": {
                k: (sum(r["first_adopt"][k] for r in rows if r["first_adopt"][k] is not None)
                    / max(1, sum(1 for r in rows if r["first_adopt"][k] is not None)))
                for k in KINDS},
            "adopt_rate": {k: sum(1 for r in rows if r["adopt_counts"][k] > 0) / len(rows)
                           for k in KINDS},
            "review_mean": {k: sum(r["review_counts"][k] for r in rows) / len(rows)
                            for k in KINDS},
        }
    return out


def build_summary_v2(bundles_by_family: dict, rfam: dict, results: dict) -> dict:
    arms = {arm: summarize_v2(results[arm]) for arm in ARM_ORDER}
    d3 = ab.paired_diffs(results["c3"], results["c1"], "m3")
    d5 = ab.paired_diffs(results["c3"], results["c1"], "m5")
    d3m = ab.paired_diffs(results["c3"], results["c3m"], "m3")
    d5m = ab.paired_diffs(results["c3"], results["c3m"], "m5")
    m3_ci = ab.bootstrap_ci(d3, ab.BOOT_SEED)
    m5_ci = ab.bootstrap_ci(d5, ab.BOOT_SEED)
    m3m_ci = ab.bootstrap_ci(d3m, ab.BOOT_SEED)
    m5m_ci = ab.bootstrap_ci(d5m, ab.BOOT_SEED)
    lofo_m3 = ab.lofo_means(d3)
    lofo_m5 = ab.lofo_means(d5)
    m4_rows = {}
    m4_guard = True
    for family in ab.FAMILIES:
        a = arms["c1"][family]["m4_rate"]
        b = arms["c3"][family]["m4_rate"]
        ok = b <= a + 0.05 + 1e-12
        m4_rows[family] = {"c1": a, "c3": b, "ok": ok}
        m4_guard = m4_guard and ok
    m3_win = m3_ci["hi"] < 0.0
    m5_win = m5_ci["lo"] > 0.0
    lofo_ok = all(v < 0.0 for v in lofo_m3.values()) and \
        all(v > 0.0 for v in lofo_m5.values())
    bminus_ok = m3m_ci["hi"] < 0.0 and m5m_ci["lo"] > 0.0
    advance = bool(m3_win and m5_win and m4_guard and lofo_ok and bminus_ok)
    floor = {fam: ab.floor_of(fam, bundles_by_family[fam]) for fam in ab.FAMILIES}
    return {
        "constants": {"T": ab.T, "H": ab.H, "SIGMA": ab.SIGMA, "THETA": ab.THETA,
                      "W": ab.W, "K_WIN": ab.K_WIN, "B_OBS": ab.B_OBS,
                      "V_LOCAL": V_LOCAL, "V_MEM": V_MEM, "L_POOL": L_POOL,
                      "N_PER_FAMILY": ab.N_PER_FAMILY, "BOOT_N": ab.BOOT_N,
                      "BOOT_SEED": ab.BOOT_SEED},
        "R_fam": rfam, "floor": floor, "arms": arms,
        "pooled": {"m3": {"ci": m3_ci, "lofo": lofo_m3},
                   "m5": {"ci": m5_ci, "lofo": lofo_m5}},
        "bminus": {"m3": m3m_ci, "m5": m5m_ci},
        "m4": m4_rows,
        "gate": {"m3_win": m3_win, "m5_win": m5_win, "m4_guard": m4_guard,
                 "lofo_ok": lofo_ok, "bminus_ok": bminus_ok, "advance": advance},
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="sim/results/teo_world_v2")
    ap.add_argument("--seed-base", type=int, default=RESERVED_BASE,
                    help="dev override (default = reserved base)")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    base = args.seed_base

    bundles_by_family = {fam: ab.generate_bundles(fam, base * 10 + i)
                         for i, fam in enumerate(ab.FAMILIES)}
    rfam = {fam: ab.r_fam_of(bundles_by_family[fam]) for fam in ab.FAMILIES}
    results = {arm: run_arm_v2(arm, list(ab.FAMILIES), bundles_by_family, rfam)
               for arm in ARM_ORDER}
    summary = build_summary_v2(bundles_by_family, rfam, results)
    summary["seed_base"] = base

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
    lines = ["# teo-world-v2 — execution summary", "",
             f"- reserved seed base: {base}",
             f"- episodes.jsonl sha256: `{h_e}`", f"- summary.json sha256: `{h_s}`", "",
             "## Identifiability floor (>= 4 sigma)"]
    for fam in ab.FAMILIES:
        f = summary["floor"][fam]
        lines.append(f"- {fam}: min {f['term']} = {f['min']:.4f} "
                     f"({f['in_sigma']:.2f} sigma) -> {'pass' if f['pass'] else 'FAIL'}")
    lines.append("")
    lines.append("## R_fam (p95 realized reach)")
    for fam in ab.FAMILIES:
        lines.append(f"- {fam}: {summary['R_fam'][fam]:.4f}")
    lines.append("")
    lines.append("## Pooled primary (c3 - c1; M3 < 0 better, M5 > 0 better)")
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
    lines.append("## Per-family profile (A1 vs V2: m1, m3, m4, m5; adoption diagnostics)")
    for fam in ab.FAMILIES:
        a = summary["arms"]["c1"][fam]
        b = summary["arms"]["c3"][fam]
        lines.append(f"- {fam}: A1 m1={a['m1_mean']:.4f} m3={a['m3_mean']:.4f} "
                     f"m4={a['m4_rate']:.3f} m5={a['m5_mean']:.3f} | "
                     f"V2 m1={b['m1_mean']:.4f} m3={b['m3_mean']:.4f} "
                     f"m4={b['m4_rate']:.3f} m5={b['m5_mean']:.3f} "
                     f"(adopt/rep={b['adopt_rate']['repeat']:.2f} "
                     f"first={b['first_adopt_mean']['repeat']:.1f} "
                     f"reid={b['reid_rate']:.3f})")
    lines.append("")
    lines.append("## Gate")
    g = summary["gate"]
    lines.append(f"- m3_win={g['m3_win']} m5_win={g['m5_win']} m4_guard={g['m4_guard']} "
                 f"lofo_ok={g['lofo_ok']} bminus_ok={g['bminus_ok']}")
    lines.append(f"- advance = **{g['advance']}**")
    lines.append("")
    lines.append("M4 = announced detection = first entry into review (V2) or the "
                 "sustained trigger (A1/B-); per-family guard in summary.json.")
    (out / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
