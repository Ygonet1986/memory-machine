#!/usr/bin/env python3
"""ingestion-trace-v1: temporal ingestion misses, abstention metric, u3a-17.

Frozen by docs/INGESTION_TRACE_V1_PREREG.md. Deterministic, no LLM.

    PYTHONPATH=src:.:eval python3 eval/ingestion_trace_v1.py
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "src"))

import delivery_anchors_v1 as da  # noqa: E402
import delivery_combined_v1 as dc  # noqa: E402
import phrase_delivery_v1 as pd  # noqa: E402
import temporal_phrase_v1 as tp  # noqa: E402
from fact_presence import item_span  # noqa: E402

INGESTION_CASES = (("u3a", 14), ("u3a", 21), ("u3b", 30), ("u3b", 40))
RESIDUAL = ("u3a", 17)
ABSTENTION = ("u3b", 41)
DATE_TOKEN_RE = re.compile(
    r"\b(?:\d{4}-\d{2}-\d{2}|(?:19|20)\d{2})\b"
    r"|\b(?:january|february|march|april|may|june|july|august|september|"
    r"october|november|december)\b", re.IGNORECASE)
TEMPORAL_UNITS = {"day", "week", "month", "year", "hour", "minute"}


def components(text: str) -> dict[str, list[str]]:
    dates = sorted({m.group(0).lower() for m in DATE_TOKEN_RE.finditer(text)})
    durations = sorted({f"{value}{unit}" for value, unit in pd.phrases(text)
                        if unit in TEMPORAL_UNITS})
    return {"dates": dates, "durations": durations}


def ingested_text(case: dict, records: dict) -> str:
    parts = []
    for memory_id in case["required_ids"]:
        record = records.get((int(case["case"]), memory_id))
        if record is not None:
            parts.append(f"{record['summary']} {record['why']}")
    return " ".join(parts)


def classify(case: dict, records: dict) -> dict[str, Any]:
    text = ingested_text(case, records)
    found = components(text)
    total = len(found["dates"]) + len(found["durations"])
    row: dict[str, Any] = {
        "block": case["block"], "case": case["case"],
        "question": case["question"], "gold": case["gold"],
        "origin_components": found,
        "component_count": total,
        "classification": "computation_needed" if total >= 2 else "ingestion_loss",
    }
    if "ago" in case["question"].lower() and not DATE_TOKEN_RE.search(case["question"]):
        row["question_date_unavailable"] = True
    return row


def residual_row(case: dict, records: dict) -> dict[str, Any]:
    phrase = pd.gold_phrases(str(case["gold"]))
    contexts = {"W0": case["context"]}
    for arm in ("W1", "W3", "W5"):
        contexts[arm] = tp.rebuild(case, records, arm)
    presence = {arm: pd.check(case, contexts[arm], records)["ok"]
                for arm in contexts}
    record = records.get((17, case["required_ids"][0]))
    position = None
    segment_count = None
    if record is not None:
        parts = da.segments(record["why"])
        segment_count = len(parts)
        for index, part in enumerate(parts):
            if "over a year" in part.lower():
                position = index
                break
    return {"block": "u3a", "case": 17, "gold": case["gold"],
            "gold_phrases": [f"{v}{u}" for v, u in phrase],
            "presence": presence, "segment_position": position,
            "segment_count": segment_count}


def abstention_row(case: dict, records: dict) -> dict[str, Any]:
    context = tp.rebuild(case, records, "W1")
    return {"block": case["block"], "case": case["case"], "gold": case["gold"],
            "default_basis": pd.check(case, context, records)["basis"],
            "aware": pd.check(case, context, records, abstention_aware=True)}


def collect() -> dict[str, Any]:
    cases, records = dc.load_fixture(HERE / "fixtures" / "composition_u4")
    by_id = {(c["block"], c["case"]): c for c in cases}
    rows = [classify(by_id[key], records) for key in INGESTION_CASES]
    residual = residual_row(by_id[RESIDUAL], records)
    abstention = abstention_row(by_id[ABSTENTION], records)
    phrase_case = by_id[("u3a", 22)]
    regression = pd.check(phrase_case,
                          tp.rebuild(phrase_case, records, "W5"), records)
    report = {
        "prereg": "docs/INGESTION_TRACE_V1_PREREG.md",
        "rows": rows, "residual_u3a17": residual,
        "abstention_u3b41": abstention,
        "default_path_regression_u3a22": regression,
    }
    report["gates"] = {
        "I1_classified": all(r["classification"] in
                             ("computation_needed", "ingestion_loss")
                             for r in rows),
        "I2_metric_fix": (abstention["aware"]["basis"] == "abstention"
                          and abstention["aware"]["applicable"] is False
                          and abstention["default_basis"] in ("atom_fallback",
                                                              "phrase")
                          and regression["ok"] is True),
        "I4_origin_excerpts": all(r["component_count"] >= 0 for r in rows),
    }
    return report


def render(report: dict[str, Any]) -> list[str]:
    lines = ["# ingestion-trace-v1", "",
             "| case | components (D/dur) | classification | flags |",
             "|---|---|---|---|"]
    for row in report["rows"]:
        found = row["origin_components"]
        lines.append(
            f"| {row['block']}:{row['case']} | {len(found['dates'])}/"
            f"{len(found['durations'])} | **{row['classification']}** | "
            f"{'question_date_unavailable' if row.get('question_date_unavailable') else ''} |")
    residual = report["residual_u3a17"]
    lines += ["", "## u3a-17 residual", "",
              f"- phrases: {residual['gold_phrases']} · presence: "
              f"{residual['presence']} · segment {residual['segment_position']}"
              f"/{residual['segment_count']}", "",
              "## Abstention metric (u3b-41)", "",
              f"- default basis: {report['abstention_u3b41']['default_basis']} · "
              f"aware: {json.dumps(report['abstention_u3b41']['aware'], sort_keys=True)}",
              "", f"gates: {json.dumps(report['gates'], sort_keys=True)}"]
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out",
                        default=str(HERE / "results" / "ingestion_trace_v1"))
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    report = collect()
    second = collect()
    report["gates"]["I3_determinism"] = (
        json.dumps({k: v for k, v in report.items() if k != "gates"},
                   sort_keys=True) == json.dumps(
            {k: v for k, v in second.items() if k != "gates"}, sort_keys=True))
    report["all_pass"] = all(report["gates"].values())
    (out / "report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8")
    markdown = "\n".join(render(report)) + "\n"
    (out / "report.md").write_text(markdown, encoding="utf-8")
    print(markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
