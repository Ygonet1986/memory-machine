#!/usr/bin/env python3
"""ingestion-caveats-v1: prose inspection for the two open caveats.

Deterministic, read-only diagnostic (no LLM) required before the
computation classification closes:

- u3a-14: identify the prose date components (one was not found by the
  date-token probe);
- u3b-40: identify the reference date actually available to the answerer
  (fixture question date, question wording, delivered header dates).

    PYTHONPATH=src:.:eval python3 eval/ingestion_caveats_v1.py
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

import delivery_combined_v1 as dc  # noqa: E402
import temporal_phrase_v1 as tp  # noqa: E402
from fact_presence import item_span  # noqa: E402

PROSE_DATE_RE = re.compile(
    r"\b(?:january|february|march|april|may|june|july|august|september|"
    r"october|november|december)\s+\d{1,2}(?:st|nd|rd|th)?"
    r"(?:,?\s*(?:19|20)\d{2})?"
    r"|\b\d{1,2}(?:st|nd|rd|th)?\s+of\s+"
    r"(?:january|february|march|april|may|june|july|august|september|"
    r"october|november|december)\b"
    r"|\b(?:last|first|second|third)\s+week\s+of\s+"
    r"(?:january|february|march|april|may|june|july|august|september|"
    r"october|november|december)\b"
    r"|\b(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b"
    r"|\b(?:19|20)\d{2}\b", re.IGNORECASE)
HEADER_DATE_RE = re.compile(r"\[[^|\]]+\|[^|\]]+\|\s*([^\]]+)\]")
QUESTION_DATE_RE = re.compile(
    r"\b(?:today|yesterday|last (?:week|month|year)|this (?:week|month|year)"
    r"|(?:19|20)\d{2}-\d{2}-\d{2})\b", re.IGNORECASE)


def prose_dates(text: str) -> list[dict[str, Any]]:
    out = []
    for match in PROSE_DATE_RE.finditer(text):
        start = max(0, match.start() - 60)
        end = min(len(text), match.end() + 60)
        out.append({"match": match.group(0),
                    "excerpt": text[start:end].replace("\n", " ").strip()})
    return out


def u3a14(records: dict) -> dict[str, Any]:
    found = []
    for memory_id in ("M0045", "M0032"):
        record = records.get((14, memory_id))
        if record is None:
            continue
        hits = prose_dates(f"{record['summary']} {record['why']}")
        found.append({"memory_id": memory_id, "hits": hits})
    header_dates = {}
    for memory_id in ("M0045", "M0032"):
        record = records.get((14, memory_id))
        if record is not None:
            header_dates[memory_id] = record["created_at"][:10]
    interval_days = None
    if len(header_dates) == 2:
        from datetime import date
        values = sorted(header_dates.values())
        y1, m1, d1 = (int(part) for part in values[0].split("-"))
        y2, m2, d2 = (int(part) for part in values[1].split("-"))
        interval_days = (date(y2, m2, d2) - date(y1, m1, d1)).days
    return {"case": "u3a:14", "question": "How many weeks passed between ...",
            "prose_dates": found,
            "header_dates": header_dates,
            "interval_days": interval_days,
            "distinct_date_like": sorted({hit["match"].lower()
                                          for entry in found
                                          for hit in entry["hits"]})}


def u3b40(cases: list[dict], records: dict) -> dict[str, Any]:
    case = next(c for c in cases if (c["block"], c["case"]) == ("u3b", 40))
    context = tp.rebuild(case, records, "W1")
    header_dates = sorted(set(HEADER_DATE_RE.findall(context)))
    return {"case": "u3b:40", "question": case["question"],
            "gold": case["gold"],
            "case_keys": sorted(case.keys()),
            "has_question_date_field": "question_date" in case,
            "question_date_tokens": QUESTION_DATE_RE.findall(case["question"]),
            "delivered_header_dates": header_dates}


def collect() -> dict[str, Any]:
    cases, records = dc.load_fixture(HERE / "fixtures" / "composition_u4")
    return {"prereg": "docs/INGESTION_TRACE_V1_PREREG.md",
            "u3a14": u3a14(records), "u3b40": u3b40(cases, records)}


def render(report: dict[str, Any]) -> list[str]:
    lines = ["# ingestion-caveats-v1", ""]
    a = report["u3a14"]
    lines += ["## u3a-14 - prose date components", "",
              f"- distinct date-like tokens: {a['distinct_date_like']}"]
    for entry in a["prose_dates"]:
        for hit in entry["hits"][:6]:
            lines.append(f"  - {entry['memory_id']}: `{hit['match']}` ... {hit['excerpt'][:110]}")
    b = report["u3b40"]
    lines += ["", "## u3b-40 - reference date availability", "",
              f"- question: {b['question']}",
              f"- question-date field in fixture: {b['has_question_date_field']}",
              f"- question date/weekday tokens: {b['question_date_tokens']}",
              f"- delivered header dates: {b['delivered_header_dates']}"]
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out",
                        default=str(HERE / "results" / "ingestion_caveats_v1"))
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    report = collect()
    (out / "report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8")
    markdown = "\n".join(render(report)) + "\n"
    (out / "report.md").write_text(markdown, encoding="utf-8")
    print(markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
