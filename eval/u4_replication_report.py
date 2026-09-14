"""U4.2 report — identical-context oscillation floor and modal-verdict ledger.

Reads eval/graph_out/u4_replication.jsonl (produced by u4_replication.py) and
writes eval/graph_out/u4_replication_summary.md plus u4_replication_ledger.jsonl.

Metrics (pre-registered):
  strict_nominal   first-replicate strict verdicts (what the U3 run would have seen)
  strict_modal     majority verdict over N replicates (ties: higher rank wins)
  within_arm_flip  cases where the N replicates disagree (identical context)
  pair_flip_rate   fraction of replicate pairs with different verdicts
  modal_ledger     per case: i5_single modal minus precise modal (+repair/-regress)
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent / "graph_out"
RANK = {"incorrect": 0, "partial": 1, "correct": 2}


def modal_of(verdicts: list[str]) -> str:
    counts = Counter(verdicts)
    best = max(counts.items(), key=lambda item: (item[1], RANK[item[0]]))
    return best[0]


def pair_flip_rate(verdicts: list[str]) -> float:
    pairs = 0
    flips = 0
    for i in range(len(verdicts)):
        for k in range(i + 1, len(verdicts)):
            pairs += 1
            flips += verdicts[i] != verdicts[k]
    return flips / pairs if pairs else 0.0


def main() -> None:
    rows = [
        json.loads(line)
        for line in (OUT_DIR / "u4_replication.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    by_case: dict[tuple[str, int], dict[str, dict]] = defaultdict(dict)
    for row in rows:
        by_case[(row["slice"], row["case"])][row["arm"]] = row

    lines = [
        "# U4.2 replication — identical-context oscillation and modal ledger",
        "",
        "Arms: `graph_augment_precise` (A) vs `i5_single` (B); N=3 per case-arm, "
        "N=5 on the U3 flip cases. Contexts verified byte-identical to the frozen "
        "U3 snapshots (asserted at rebuild time).",
        "",
        "| case | N | A verdicts | A modal | B verdicts | B modal | modal delta |",
        "|---|---|---|---|---|---|---|",
    ]
    ledger = []
    flips_any = 0
    arm_stats: dict[str, dict[str, float]] = defaultdict(lambda: {"cases": 0, "within": 0, "pairs": 0.0, "flips": 0.0})
    nominal_vs_modal = 0
    for (slice_name, case), arms in sorted(by_case.items(), key=lambda item: (item[0][0], item[0][1])):
        a = arms["graph_augment_precise"]
        b = arms["i5_single"]
        a_modal = modal_of(a["verdicts"])
        b_modal = modal_of(b["verdicts"])
        delta = RANK[b_modal] - RANK[a_modal]
        ledger.append(
            {
                "slice": slice_name,
                "case": case,
                "n": a["n"],
                "precise_verdicts": a["verdicts"],
                "i5_single_verdicts": b["verdicts"],
                "precise_modal": a_modal,
                "i5_single_modal": b_modal,
                "modal_delta": delta,
                "within_arm_flip": len(set(a["verdicts"])) > 1 or len(set(b["verdicts"])) > 1,
            }
        )
        if ledger[-1]["within_arm_flip"]:
            flips_any += 1
        for label, row in (("A", a), ("B", b)):
            stats = arm_stats[label]
            stats["cases"] += 1
            stats["within"] += len(set(row["verdicts"])) > 1
            stats["pairs"] += 1.0
            stats["flips"] += pair_flip_rate(row["verdicts"])
            if row["verdicts"][0] != modal_of(row["verdicts"]):
                nominal_vs_modal += 1
        lines.append(
            f"| {slice_name.replace('longmemeval_u3', 'u3')}-{case} | {a['n']} | "
            f"{', '.join(v[0] for v in a['verdicts'])} | {a_modal} | "
            f"{', '.join(v[0] for v in b['verdicts'])} | {b_modal} | {delta:+d} |"
        )

    a_corr = sum(1 for md in ledger if md["precise_modal"] == "correct")
    b_corr = sum(1 for md in ledger if md["i5_single_modal"] == "correct")
    a_par = sum(1 for md in ledger if md["precise_modal"] == "partial")
    b_par = sum(1 for md in ledger if md["i5_single_modal"] == "partial")
    bins = {"u3a": [], "u3b": []}
    for md in ledger:
        bins[md["slice"].replace("longmemeval_", "")].append(md["modal_delta"])
    lines += [
        "",
        "## Aggregate",
        "",
        f"- cases: {len(ledger)} (u3a: {len(bins['u3a'])}, u3b: {len(bins['u3b'])})",
        f"- strict (correct) by **modal** verdict: precise {a_corr} (+{a_par} partial), "
        f"i5_single {b_corr} (+{b_par} partial)",
        "- nominal (first-replicate) strict for reference: see per-case table (first verdict "
        "in each cell); the modal reading above is the replication's result.",
        f"- cases where the first replicate differs from the modal verdict: {nominal_vs_modal} "
        f"(of {len(rows)} arm-cases)",
        f"- cases with any within-arm flip (identical context): {flips_any}/{len(ledger)}",
        "- pair flip rate (identical context, all replicate pairs): "
        + ", ".join(
            f"{label} {stats['flips'] / stats['pairs']:.3f} ({int(stats['within'])}/{int(stats['cases'])} cases)"
            for label, stats in sorted(arm_stats.items())
        ),
        f"- modal ledger deltas: {dict(Counter(md['modal_delta'] for md in ledger))}",
    ]
    (OUT_DIR / "u4_replication_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    with (OUT_DIR / "u4_replication_ledger.jsonl").open("w", encoding="utf-8") as handle:
        for md in ledger:
            handle.write(json.dumps(md, ensure_ascii=False) + "\n")
    print("\n".join(lines[-8:]))


if __name__ == "__main__":
    main()
