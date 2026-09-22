#!/usr/bin/env python3
"""Lifecycle v1 — arms A/B/D report (deterministic, no LLM, frozen definitions).

Frozen by docs/LIFECYCLE_V1_PREREG.md §2/§5 and the 2026-09-22 corrections:

  A  all records the 0.2.0 behaviour would leave active (baseline)
  B  semantic ∪ episodic (rules policy)
  D  gold semantic ∪ episodic (diagnostic ceiling only; never for tuning)

Metrics: promotion_precision, promotion_recall, active_set_reduction (over
received and admissible), false_discard_rate (= 1 − promotion_recall on the
required set), false_semantic (precision error and FP rate), full gold×pred
confusion matrix, per-hard-case results, and per-probe evaluation with the
temporal rule ``record.seq < probe.after_seq`` (the final set is never used to
answer older probes). A memory required by several probes is counted once in
the global metrics and once per probe occurrence; both are published.

Run: PYTHONPATH=src python3 eval/lifecycle_shadow.py [--out DIR]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "src"))

from memory_machine import lifecycle as lc  # noqa: E402

FIXTURE = HERE / "fixtures" / "lifecycle_v1"


def rows(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def load_fixture(fixture: Path):
    records = rows(fixture / "records.jsonl")
    gold = {row["memory_id"]: row for row in rows(fixture / "gold.jsonl")}
    probes = rows(fixture / "probes.jsonl")
    return records, gold, probes


def arm_sets(records, gold, decisions_b):
    by_id = {row["memory_id"]: row for row in records}
    seq = {row["memory_id"]: row["seq"] for row in records}
    promoted_b = {d.memory_id for d in decisions_b if d.promoted}
    promoted_d = {mid for mid, row in gold.items()
                  if row["gold_class"] in lc.PROMOTED_CLASSES and mid in by_id}
    active_a = set(by_id)  # 0.2.0 keeps every stored record active
    return {
        "A": {"active": active_a, "promoted": active_a},
        "B": {"active": promoted_b, "promoted": promoted_b},
        "D": {"active": promoted_d, "promoted": promoted_d},
        "seq": seq,
        "by_id": by_id,
    }


def rates(promoted: set[str], required: set[str]) -> dict[str, Any]:
    found = promoted & required
    precision = len(found) / len(promoted) if promoted else 0.0
    recall = len(found) / len(required) if required else 0.0
    return {
        "promoted": len(promoted),
        "required": len(required),
        "found": len(found),
        "promotion_precision": round(precision, 4),
        "promotion_recall": round(recall, 4),
        "false_discard_rate": round(1.0 - recall, 4),
    }


def false_semantic(predicted_class: dict[str, str], gold: dict[str, dict]) -> dict[str, Any]:
    pred_sem = {mid for mid, cls in predicted_class.items() if cls == "semantic"}
    wrong = {mid for mid in pred_sem if gold.get(mid, {}).get("gold_class") != "semantic"}
    non_sem = {mid for mid, row in gold.items() if row["gold_class"] != "semantic"}
    return {
        "predicted_semantic": len(pred_sem),
        "wrong_semantic": len(wrong),
        "precision_error_rate": round(len(wrong) / len(pred_sem), 4) if pred_sem else 0.0,
        "false_positive_rate": round(len(wrong) / len(non_sem), 4) if non_sem else 0.0,
    }


def confusion(predicted_class: dict[str, str], gold: dict[str, dict]) -> dict[str, Any]:
    matrix: dict[str, Counter] = {g: Counter() for g in lc.CLASSES}
    for mid, row in gold.items():
        if mid not in predicted_class:
            continue
        matrix[row["gold_class"]][predicted_class[mid]] += 1
    return {
        gold: {cls: matrix[gold][cls] for cls in lc.CLASSES}
        for gold in lc.CLASSES
    }


def per_pattern(gold: dict[str, dict], predicted: set[str]) -> dict[str, Any]:
    grouped: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"total": 0, "promoted": 0, "required": 0, "found": 0})
    for mid, row in gold.items():
        bucket = grouped[row["pattern"]]
        bucket["total"] += 1
        bucket["promoted"] += int(mid in predicted)
    return dict(sorted(grouped.items()))


def per_probe(probes, decisions_by_id: dict[str, lc.Decision],
              seq_by_id: dict[str, int]) -> dict[str, Any]:
    """Per-probe evaluation with the frozen temporal guard.

    A record is available for a probe only if it was promoted **and** the
    admission decision happened before the probe (``seq < after_seq``). The
    final session set is never used to answer older probes.
    """
    results = []
    total_required = total_found = 0
    for probe in probes:
        if probe.get("unrecoverable"):
            results.append({"probe_id": probe["probe_id"],
                            "skipped": "unrecoverable_due_to_ingestion"})
            continue
        required = [mid for mid in probe["required_ids"] if mid in seq_by_id]
        found = [mid for mid in required
                 if decisions_by_id[mid].promoted
                 and seq_by_id[mid] < probe["after_seq"]]
        total_required += len(required)
        total_found += len(found)
        results.append({
            "probe_id": probe["probe_id"],
            "after_seq": probe["after_seq"],
            "required": required,
            "found": found,
            "recall": round(len(found) / len(required), 4) if required else 0.0,
        })
    return {
        "occurrences": total_found,
        "occurrences_total": total_required,
        "occurrence_recall": round(total_found / total_required, 4)
        if total_required else 0.0,
        "per_probe": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", default=str(FIXTURE))
    parser.add_argument("--out", default="eval/results/lifecycle_v1_report")
    args = parser.parse_args()
    fixture = Path(args.fixture)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    records, gold, probes = load_fixture(fixture)
    projection = lc.LifecycleProjection(out / "projection")
    manifest = projection.rebuild(records)
    decisions = [lc.Decision.from_dict(row) for row in projection.load_decisions()]
    by_id = {d.memory_id: d for d in decisions}
    seq_by_id = {row["memory_id"]: row["seq"] for row in records}

    sets = arm_sets(records, gold, decisions)
    required_all = {mid for probe in probes for mid in probe["required_ids"]
                    if not probe.get("unrecoverable") and mid in seq_by_id}
    predicted_class = {d.memory_id: d.target_class for d in decisions}
    predicted_class_d = {mid: row["gold_class"] for mid, row in gold.items()}

    report: dict[str, Any] = {
        "fixture": str(fixture),
        "projection_manifest": manifest,
        "required_memories": sorted(required_all),
        "arms": {},
    }
    for arm in ("A", "B", "D"):
        promoted = sets[arm]["promoted"]
        received = set(seq_by_id)
        admissible = received  # 0.2.0 accepts every non-secret record
        entry = {
            "promoted": len(promoted),
            "global_memory_metrics": rates(promoted, required_all),
            "active_set_reduction_received": round(1 - len(promoted) / len(received), 4),
            "active_set_reduction_admissible": round(
                1 - len(promoted) / len(admissible), 4),
        }
        if arm == "B":
            entry["false_semantic"] = false_semantic(predicted_class, gold)
            entry["confusion_matrix"] = confusion(predicted_class, gold)
            entry["per_pattern"] = per_pattern(gold, promoted)
        if arm == "D":
            entry["false_semantic"] = false_semantic(predicted_class_d, gold)
            entry["note"] = ("diagnostic ceiling only; never used to tune the "
                             "rules in this frozen round")
        entry["per_probe"] = per_probe(probes, by_id, seq_by_id)
        report["arms"][arm] = entry

    # deterministic rebuild check
    projection.rebuild(records)
    rebuild_two = projection.decisions_path().read_bytes()
    projection.rebuild(records)
    rebuild_three = projection.decisions_path().read_bytes()
    report["rebuild_identical"] = rebuild_two == rebuild_three

    (out / "report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8")
    lines = [
        "# Lifecycle v1 — arms A/B/D report (deterministic, frozen definitions)",
        "",
        f"- fixture: `{fixture}` · projection policy `{lc.POLICY_VERSION}`",
        f"- required memories (probes, ingested only): {len(required_all)}",
        "- note: global metrics use the final promoted set; per-probe values "
        "apply the temporal guard (seq < after_seq)",
        f"- rebuild identical: {report['rebuild_identical']}",
        "",
        "| arm | promoted | promotion precision | promotion recall | active-set reduction (received) |",
        "|---|---:|---:|---:|---:|",
    ]
    for arm in ("A", "B", "D"):
        m = report["arms"][arm]["global_memory_metrics"]
        lines.append(
            f"| {arm} | {m['promoted']} | {m['promotion_precision']:.3f} | "
            f"{m['promotion_recall']:.3f} | "
            f"{report['arms'][arm]['active_set_reduction_received']:.3f} |")
    lines += ["", "## Arm B confusion (gold rows × predicted columns)", "",
              "| gold \\ pred | semantic | episodic | event_only | reject |",
              "|---|---:|---:|---:|---:|"]
    for gold_class in lc.CLASSES:
        row = report["arms"]["B"]["confusion_matrix"][gold_class]
        lines.append(f"| {gold_class} | {row['semantic']} | {row['episodic']} | "
                     f"{row['event_only']} | {row['reject']} |")
    fs = report["arms"]["B"]["false_semantic"]
    lines += ["", "## Arm B false-semantic", "",
              f"- predicted semantic: {fs['predicted_semantic']}, wrong: "
              f"{fs['wrong_semantic']} (precision error {fs['precision_error_rate']:.3f}; "
              f"FP rate {fs['false_positive_rate']:.3f})",
              "", "## Per-probe (temporal: seq < after_seq)", "",
              "| probe | required | found | recall |", "|---|---:|---:|---:|"]
    for probe in report["arms"]["B"]["per_probe"]["per_probe"]:
        if "skipped" in probe:
            lines.append(f"| {probe['probe_id']} | — | — | skipped (ingestion) |")
        else:
            lines.append(f"| {probe['probe_id']} | {len(probe['required'])} | "
                         f"{len(probe['found'])} | {probe['recall']:.2f} |")
    lines += ["", "## Arm B hard cases (promoted / total)", ""]
    for pattern, data in report["arms"]["B"]["per_pattern"].items():
        lines.append(f"- {pattern}: {data['promoted']}/{data['total']}")
    (out / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines[:18]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
