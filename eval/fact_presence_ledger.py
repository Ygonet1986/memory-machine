"""U4.1 ledger: do verdict flips follow item-fact presence changes?

Reads the fact_presence snapshots of the two U3 blocks and prints, per case,
the item-fact presence rate per arm, the verdict change (precise -> i5_single)
and the presence delta. A repair/regression is only causally attributed to the
delivery policy when the presence rate moves in the same direction.
"""

from __future__ import annotations

import json
from pathlib import Path

OUT = Path(__file__).resolve().parent / "graph_out"
RANK = {"incorrect": 0, "partial": 1, "correct": 2}


def load() -> list[dict]:
    rows = []
    for block in ("longmemeval_u3a", "longmemeval_u3b"):
        path = OUT / f"fact_presence_{block}.jsonl"
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
    return rows


def rate(data: dict) -> float:
    total = sum(f["item_facts"]["total"] for f in data["items"].values())
    present = sum(f["item_facts"]["present"] for f in data["items"].values())
    return present / total if total else 0.0


def main() -> None:
    rows = load()
    print(
        f"{'case':>4} {'class':<12} {'precise':>8} {'i5':>8} {'single':>8} {'mixed':>8} "
        f"| verdict precise -> single | facts delta | verdict delta"
    )
    for row in rows:
        arms = row["arms"]
        precise = arms["graph_augment_precise"]
        single = arms["i5_single"]
        delta_facts = rate(single) - rate(precise)
        delta_verdict = ""
        if precise["verdict"] and single["verdict"]:
            change = RANK[single["verdict"]] - RANK[precise["verdict"]]
            delta_verdict = "REPAIRED" if change > 0 else ("REGRESSED" if change < 0 else "same")
        print(
            f"{row['case']:>4} {row['question_class']:<12} {rate(precise):>8.3f} "
            f"{rate(arms['i5']):>8.3f} {rate(single):>8.3f} {rate(arms['i5_mixed']):>8.3f} "
            f"| {precise['verdict']:>9} -> {single['verdict']:>9} | {delta_facts:+.3f} | {delta_verdict}"
        )


if __name__ == "__main__":
    main()
