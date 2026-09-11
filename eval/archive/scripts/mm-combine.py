"""Combine the per-arm view-router benchmark JSONs into one report table."""
import json
import sys
from pathlib import Path

ARMS = ["full", "similarity", "view_bm25", "view_llm", "view_oracle", "cascade_bm25", "cascade_llm"]
ROOT = Path("/tmp/mm-view-run")

rows_by_arm = {}
for arm in ARMS:
    p = ROOT / f"{arm}.json"
    if p.exists():
        rows_by_arm[arm] = json.loads(p.read_text())["arms"][arm]

if not rows_by_arm:
    print("no arm JSONs yet")
    sys.exit(0)


def mean(rows, key):
    return sum(r[key] for r in rows) / len(rows) if rows else 0.0


def summarize(rows):
    reasons = {}
    attrib = {}
    for r in rows:
        for reason in r.get("reasons") or []:
            reasons[reason] = reasons.get(reason, 0) + 1
        a = r.get("attribution") or ""
        if a:
            attrib[a] = attrib.get(a, 0) + 1
    return {
        "n": len(rows),
        "view_recall": mean(rows, "view_recall"),
        "view_precision": mean(rows, "view_precision"),
        "evidence_recall": mean(rows, "evidence_recall"),
        "complete_evidence": mean(rows, "complete_evidence"),
        "agent_recall": mean(rows, "agent_recall"),
        "complete_agent": mean(rows, "complete_agent"),
        "reduction": mean(rows, "reduction"),
        "expansion": mean(rows, "expansion"),
        "fallback": mean(rows, "fallback"),
        "calls": mean(rows, "calls"),
        "tokens": mean(rows, "tokens"),
        "latency": mean(rows, "latency"),
        "reasons": reasons,
        "attribution": attrib,
    }


summary = {arm: summarize(rows) for arm, rows in rows_by_arm.items()}
header = (
    f"{'arm':<14} {'vrec':>6} {'vprec':>6} {'erec':>6} {'ecomp':>6} {'arec':>6} "
    f"{'acomp':>6} {'reduce':>7} {'exp':>5} {'fall':>5} {'calls':>6} {'tok/q':>7} {'lat':>6}"
)
print(header)
print("-" * len(header))
for arm, s in summary.items():
    print(
        f"{arm:<14} {s['view_recall']:>6.2f} {s['view_precision']:>6.2f} {s['evidence_recall']:>6.2f} "
        f"{s['complete_evidence']:>6.2f} {s['agent_recall']:>6.2f} {s['complete_agent']:>6.2f} "
        f"{s['reduction']:>7.2f} {s['expansion']:>5.2f} {s['fallback']:>5.2f} "
        f"{s['calls']:>6.1f} {s['tokens']:>7.0f} {s['latency']:>6.1f}"
    )

print("\nby category (view recall / complete evidence / agent recall):")
cats = ["single", "same_view", "cross_view", "adversarial"]
for arm, rows in rows_by_arm.items():
    for cat in cats:
        sub = [r for r in rows if r["cat"] == cat]
        if not sub:
            continue
        s = summarize(sub)
        print(
            f"  {arm:<14} {cat:<12} n={s['n']:<3} vrec={s['view_recall']:.2f} "
            f"ecomp={s['complete_evidence']:.2f} arec={s['agent_recall']:.2f} calls={s['calls']:.1f}"
        )

print("\nfallback reasons:")
for arm, s in summary.items():
    if s["reasons"]:
        print(f"  {arm}: {s['reasons']}")
print("\nattribution:")
for arm, s in summary.items():
    print(f"  {arm}: {s['attribution']}")

Path("/tmp/mm-view-summary.json").write_text(
    json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
)
print("\nwrote /tmp/mm-view-summary.json")
