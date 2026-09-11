"""Analyze the e2e snapshots: final table, AUR, failure taxonomy, judge audit."""
import json
from pathlib import Path

OUT = Path.home() / "memory-machine" / "eval" / "out"
ARMS = ["no_memory", "bm25", "agents_group", "agents_view", "agents_view_ctx", "agents_view_payload", "oracle"]


def load(arm):
    path = OUT / f"e2e_{arm}.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def mean(xs):
    return sum(xs) / len(xs) if xs else 0.0


print(f"{'arm':<19} {'n':>3} {'evid':>6} {'strict':>7} {'lenient':>8} {'AUR':>6} "
      f"{'fact_cov':>8} {'ctx_ch':>7} {'pl_ch':>6} {'eff':>5} {'calls':>7}")
for arm in ARMS:
    rows = load(arm)
    if not rows:
        continue
    complete = [r for r in rows if r["evidence_complete"] == 1]
    strict = [r for r in rows if r["judge"]["verdict"] == "correct"]
    lenient = [r for r in rows if r["judge"]["verdict"] in {"correct", "partial"}]
    aur = mean([1 if r["judge"]["verdict"] == "correct" else 0 for r in complete]) if complete else None
    ctx_chars = mean([r.get("context_chars", 0) for r in rows])
    pl_chars = mean([r.get("payload_chars", 0) for r in rows])
    total_chars = max(ctx_chars, pl_chars)
    eff = (len(strict) / len(rows)) / (total_chars / 1000) if total_chars else 0.0
    print(
        f"{arm:<19} {len(rows):>3} {len(complete)/len(rows):>6.2f} {len(strict)/len(rows):>7.2f} "
        f"{len(lenient)/len(rows):>8.2f} {(f'{aur:.2f}' if aur is not None else '  -'):>6} "
        f"{mean([r['fact_coverage'] for r in rows]):>8.2f} {ctx_chars:>7.0f} {pl_chars:>6.0f} "
        f"{eff:>5.2f} {mean([r['calls'] for r in rows]):>7.1f}"
    )

print("\nfailure taxonomy (strict-incorrect rows):")
for arm in ARMS:
    rows = [r for r in load(arm) if r["judge"]["verdict"] != "correct"]
    if not rows:
        continue
    kinds = {"retrieval": 0, "context_loss": 0, "answerer": 0}
    for r in rows:
        if r["evidence_complete"] == 0:
            kinds["retrieval"] += 1
        elif r["fact_coverage"] < 0.6:
            kinds["context_loss"] += 1
        else:
            kinds["answerer"] += 1
    print(f"  {arm:<17} {kinds}")

print("\nper-task verdicts (agents_view vs agents_view_ctx vs oracle):")
base = {r["task"]: r for r in load("agents_view")}
ctx = {r["task"]: r for r in load("agents_view_ctx")}
orc = {r["task"]: r for r in load("oracle")}
print(f"  {'task':>4} {'cat':<12} {'view':<10} {'view_ctx':<10} {'oracle':<10}")
for task in sorted(set(base) | set(ctx) | set(orc)):
    def v(d):
        return d[task]["judge"]["verdict"] if task in d else "-"
    cat = (base.get(task) or ctx.get(task) or orc.get(task))["cat"]
    print(f"  {task:>4} {cat:<12} {v(base):<10} {v(ctx):<10} {v(orc):<10}")

print("\njudge audit:")
for arm in ARMS:
    path = OUT / f"judge_audit_{arm}.jsonl"
    if not path.exists():
        continue
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    if not rows:
        continue
    agree = sum(1 for r in rows if r["first_verdict"] == r["audit_verdict"])
    print(f"  {arm:<17} {agree}/{len(rows)} ({agree/len(rows):.2f}) model={rows[0]['audit_model']}")
