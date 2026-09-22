#!/usr/bin/env python3
"""phrase-delivery-v1: sentence-level phrase metric for delivered spans.

Frozen by docs/PHRASE_DELIVERY_V1_PREREG.md. Deterministic, no LLM: verifies
that the phrase metric sees the u3a-22 loss and does not false-alarm on the
controls, against the frozen contexts of diagnostic-trace-v1.

    PYTHONPATH=src:.:eval python3 eval/phrase_delivery_v1.py
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
from diagnostic_trace_v1 import TRACKED  # noqa: E402
from fact_presence import atom_present, item_fact_atoms, item_span, norm  # noqa: E402

UNITS = (r"days?|weeks?|months?|years?|hours?|minutes?|gb|mb|kb|tb"
         r"|%|percent|dollars?|usd")
NUMBER_WORDS = {
    "one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
    "six": "6", "seven": "7", "eight": "8", "nine": "9", "ten": "10",
    "eleven": "11", "twelve": "12", "a": "1", "an": "1",
}
DIGIT_UNIT_RE = re.compile(rf"(\d+(?:[.,]\d+)?)\s*({UNITS})")
WORD_UNIT_RE = re.compile(rf"\b({ '|'.join(NUMBER_WORDS) })\s+({UNITS})\b")
CURRENCY_RE = re.compile(r"\$\s*(\d+(?:[.,]\d+)?)")
ABSTENTION_RE = re.compile(
    r"not enough information|information provided is not enough|"
    r"insufficient information|cannot be determined|no information",
    re.IGNORECASE)


def phrases(text: str) -> list[tuple[str, str]]:
    t = norm(text)
    out: list[tuple[str, str]] = []
    for match in DIGIT_UNIT_RE.finditer(t):
        out.append((match.group(1), match.group(2).rstrip("s") if match.group(2)
                    not in {"%", "percent"} else match.group(2)))
    for match in WORD_UNIT_RE.finditer(t):
        word = NUMBER_WORDS[match.group(1)]
        unit = match.group(2)
        out.append((word, unit.rstrip("s") if unit not in {"%", "percent"} else unit))
    for match in CURRENCY_RE.finditer(t):
        out.append((match.group(1), "$"))
    return out


def gold_phrases(gold: str) -> list[tuple[str, str]]:
    return phrases(gold)


def phrase_present(phrase: tuple[str, str], span: str) -> bool:
    value, unit = phrase
    for span_value, span_unit in phrases(span):
        if span_value == value and span_unit == unit:
            return True
    return False


def check(case: dict, context: str, records: dict, *,
          abstention_aware: bool = False) -> dict[str, Any]:
    spans = []
    for memory_id in case["required_ids"]:
        span, found = item_span(context, memory_id)
        if found:
            spans.append(span)
    union = " ".join(spans)
    if abstention_aware and ABSTENTION_RE.search(str(case["gold"])):
        return {"basis": "abstention", "applicable": False, "ok": True,
                "gold_phrases": [], "missing": []}
    gold = gold_phrases(str(case["gold"]))
    if gold:
        missing = [f"{v}{u}" for v, u in gold if not phrase_present((v, u), union)]
        return {"basis": "phrase", "gold_phrases": [f"{v}{u}" for v, u in gold],
                "missing": missing, "ok": not missing}
    atoms = item_fact_atoms(str(case["gold"]))
    missing = [f"{a['kind']}:{a['value']}" for a in atoms
               if not atom_present(a, norm(union))]
    return {"basis": "atom_fallback", "missing": missing, "ok": not missing}


def collect() -> dict[str, Any]:
    cases, records = dc.load_fixture(HERE / "fixtures" / "composition_u4")
    selected = [case for case in cases if (case["block"], case["case"]) in TRACKED]
    trace = {}
    trace_path = HERE / "results" / "diagnostic_trace_v1" / "trace.jsonl"
    if trace_path.exists():
        for line in trace_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                trace[(row["block"], row["case"], row["arm"])] = row
    rows = []
    for case in selected:
        contexts = dc.contexts(case, records)
        for arm in ("W0", "W1", "W3"):
            result = check(case, contexts[arm], records)
            row = {"block": case["block"], "case": case["case"], "arm": arm,
                   "question": case["question"], "gold": case["gold"],
                   "context_sha256": _sha(contexts[arm]), **result}
            if (case["block"], case["case"], arm) in trace:
                row["answer_verdicts"] = trace[(case["block"], case["case"], arm)][
                    "answer"]["verdicts"]
                row["trace_context_sha256"] = trace[(case["block"], case["case"], arm)][
                    "context_sha256"]
            rows.append(row)

    def row_of(case: int, arm: str) -> dict:
        return next(r for r in rows if r["case"] == case and r["arm"] == arm)

    p1 = (row_of(22, "W0")["ok"] and row_of(22, "W1")["ok"]
          and not row_of(22, "W3")["ok"])
    p2 = (row_of(12, "W0")["ok"] and row_of(12, "W1")["ok"]
          and row_of(12, "W3")["ok"]
          and row_of(27, "W0")["ok"] and row_of(27, "W1")["ok"]
          and row_of(27, "W3")["ok"])
    p3 = not row_of(19, "W0")["ok"] and not row_of(19, "W1")["ok"] \
        and not row_of(19, "W3")["ok"]
    p4 = all(row["context_sha256"] == row.get("trace_context_sha256")
             for row in rows if "trace_context_sha256" in row)
    report = {"prereg": "docs/PHRASE_DELIVERY_V1_PREREG.md",
              "rows": rows,
              "gates": {"P1_detects_u3a22": p1, "P2_controls": p2,
                        "P3_locates_u3a19": p3, "P4_hashes": p4}}
    return report


def _sha(text: str) -> str:
    import hashlib
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def render(report: dict[str, Any]) -> list[str]:
    lines = ["# phrase-delivery-v1", "",
             "| case | arm | basis | gold phrase/info | present | answer verdicts |",
             "|---|---|---|---|---|---|"]
    for row in report["rows"]:
        info = ",".join(row.get("gold_phrases") or row.get("missing") or [])
        lines.append(f"| {row['block']}:{row['case']} | {row['arm']} | "
                     f"{row['basis']} | {info} | {'ok' if row['ok'] else 'MISS'} | "
                     f"{'/'.join(row.get('answer_verdicts') or []) or '-'} |")
    lines += ["", f"gates: {json.dumps(report['gates'], sort_keys=True)}"]
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out",
                        default=str(HERE / "results" / "phrase_delivery_v1"))
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    report = collect()
    second = collect()
    report["gates"]["P5_determinism"] = (
        json.dumps(report["rows"], sort_keys=True)
        == json.dumps(second["rows"], sort_keys=True))
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
