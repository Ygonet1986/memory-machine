"""Uniform view-router benchmark report, reconstructed from per-task caches.

Works even when an arm did not finish (reports its n), so partial arms stay
comparable on the same task set. Core metrics come from each task's
recall_cache.json (routing + annotations); calls are estimated from the routing
metadata (router call + groups consulted).
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "eval")
sys.path.insert(0, "src")
import view_router_bench as vb  # noqa: E402
from memory_machine.config import Config  # noqa: E402

ARMS = ["full", "similarity", "view_bm25", "view_llm", "view_oracle", "cascade_bm25", "cascade_llm"]
KEEP = Path("/tmp/mm-view-keep")
RUN = Path("/tmp/mm-view-run")
ROUTER_CALLS = {"similarity": 1, "view_llm": 1, "cascade_llm": 1}

specs = {s["key"]: s for s in vb.MEMORIES if s.get("key")}
m, id_map = vb.build_machine(Path(tempfile.mkdtemp()), Config(capacity=5))
total = sum(1 for r in m.tape.read() if r.status == "active")


def arm_roots(arm):
    roots = []
    if (RUN / arm / arm).exists():
        roots.append(RUN / arm / arm)
    if (KEEP / arm).exists():
        roots.append(KEEP / arm)
    return roots


def find_cache(arm, index):
    for root in arm_roots(arm):
        p = root / f"task_{index:02d}" / "recall_cache.json"
        if p.exists():
            return p
    return None


def row_for(arm, index, task):
    cache = find_cache(arm, index)
    if cache is None:
        return None
    res = json.loads(cache.read_text())["result"]
    rt = res.get("routing") or {}
    selected = set(rt.get("selected_views") or [])
    consulted = set(rt.get("consulted_ids") or [])
    annotated = {a["memory_id"] for a in res.get("annotations") or []}
    required = {id_map[k] for k in task["required"]}
    per_memory = [vb._target_views(specs[k]) for k in task["required"]]
    target = set().union(*per_memory)
    view_hits = [1 if selected & v else 0 for v in per_memory]
    calls = ROUTER_CALLS.get(arm, 0) + int(rt.get("groups_consulted") or 0)
    row = {
        "cat": task["cat"],
        "view_recall": sum(view_hits) / len(view_hits),
        "view_precision": (len(selected & target) / len(selected)) if selected else 0.0,
        "evidence_recall": len(consulted & required) / len(required),
        "complete_evidence": int(required <= consulted),
        "agent_recall": len(annotated & required) / len(required),
        "complete_agent": int(required <= annotated),
        "reduction": 1.0 - (len(consulted) / total if total else 0.0),
        "expansion": len(consulted) / max(1, rt.get("records_level1") or len(consulted)),
        "level": rt.get("level", 0),
        "fallback": int(rt.get("level", 0) > 1),
        "reasons": list(rt.get("fallback_reasons") or []),
        "calls": calls,
    }
    if not all(view_hits):
        row["attribution"] = "view_miss"
    elif not row["complete_evidence"]:
        row["attribution"] = "evidence_miss"
    elif not row["complete_agent"]:
        row["attribution"] = "agent_miss"
    else:
        row["attribution"] = ""
    return row


def mean(rows, key):
    return sum(r[key] for r in rows) / len(rows) if rows else 0.0


def summarize(rows):
    reasons: dict[str, int] = {}
    attrib: dict[str, int] = {}
    for r in rows:
        for reason in r["reasons"]:
            reasons[reason] = reasons.get(reason, 0) + 1
        if r["attribution"]:
            attrib[r["attribution"]] = attrib.get(r["attribution"], 0) + 1
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
        "reasons": reasons,
        "attribution": attrib,
    }


by_arm = {}
for arm in ARMS:
    rows = []
    for i, task in enumerate(vb.TASKS):
        r = row_for(arm, i, task)
        if r is not None:
            rows.append(r)
    by_arm[arm] = rows

summary = {arm: summarize(rows) for arm, rows in by_arm.items()}
header = (
    f"{'arm':<14} {'n':>3} {'vrec':>6} {'vprec':>6} {'erec':>6} {'ecomp':>6} {'arec':>6} "
    f"{'acomp':>6} {'reduce':>7} {'exp':>5} {'fall':>5} {'calls*':>6}"
)
print(header)
print("-" * len(header))
for arm, s in summary.items():
    print(
        f"{arm:<14} {s['n']:>3} {s['view_recall']:>6.2f} {s['view_precision']:>6.2f} "
        f"{s['evidence_recall']:>6.2f} {s['complete_evidence']:>6.2f} {s['agent_recall']:>6.2f} "
        f"{s['complete_agent']:>6.2f} {s['reduction']:>7.2f} {s['expansion']:>5.2f} "
        f"{s['fallback']:>5.2f} {s['calls']:>6.1f}"
    )

print("\nby category (view recall / complete evidence / agent recall):")
for arm, rows in by_arm.items():
    for cat in ["single", "same_view", "cross_view", "adversarial"]:
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
print("\nattribution (view_miss / evidence_miss / agent_miss):")
for arm, s in summary.items():
    print(f"  {arm}: {s['attribution']}")

Path("/tmp/mm-view-summary.json").write_text(
    json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
)
print("\nwrote /tmp/mm-view-summary.json  (* calls estimated from routing metadata)")
