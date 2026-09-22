#!/usr/bin/env python3
"""delivery-anchors-v1 harness: W0 current vs W1 factual window vs W2 anchors.

Frozen by docs/DELIVERY_ANCHORS_V1_PREREG.md. Deterministic, no LLM: re-fills
truncated payload items (bounded by their frozen body length) and measures
gold-atom presence per case. Production defaults untouched.

    PYTHONPATH=src:.:eval python3 eval/delivery_anchors_v1.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "src"))

from memory_machine.payload import fact_window  # noqa: E402
from memory_machine.retrieval import tokenize  # noqa: E402

from fact_presence import (  # noqa: E402
    atom_present,
    item_fact_atoms,
    item_span,
    norm,
)

POLICIES = ("W0", "W1", "W2")
NUM_CUE_RE = re.compile(
    r"\d|before|after|increase|decrease|difference|more|less|compare|change"
    r"|much|many|long|old|total|number|percent|years|days|weeks|times",
    re.IGNORECASE)
DATE_RE = re.compile(
    r"\b(?:\d{4}-\d{2}-\d{2}|(?:19|20)\d{2})\b"
    r"|\b(?:january|february|march|april|may|june|july|august|september|"
    r"october|november|december)\b", re.IGNORECASE)
NUMBER_RE = re.compile(r"\b\d+(?:[.,]\d+)?\b")


def data_numbers(part: str) -> list[str]:
    """Numbers that are not leading list markers ("1. ...")."""
    out = []
    for match in NUMBER_RE.finditer(part):
        if match.start() == 0 and part[match.end():match.end() + 1] == ".":
            continue
        out.append(match.group(0))
    return out
SEGMENT_RE = re.compile(r"(?<=[.!?])\s+|\n+")


def segments(text: str) -> list[str]:
    return [part.strip() for part in SEGMENT_RE.split(text) if part.strip()]


def anchors_window(text: str, question: str, allocation: int) -> str:
    if allocation <= 0 or not text:
        return text[: max(0, allocation)]
    parts = segments(text)
    if not parts or sum(len(part) + 1 for part in parts) <= allocation:
        return text[:allocation]
    q_tokens = set(tokenize(question))
    scores = [len(q_tokens & set(tokenize(part))) for part in parts]
    best = max(range(len(parts)), key=lambda i: (scores[i], -i))

    order: list[int] = [best]
    for neighbor in (best - 1, best + 1):
        if 0 <= neighbor < len(parts) and neighbor not in order:
            order.append(neighbor)
    for index, part in enumerate(parts):
        if DATE_RE.search(part) and index not in order:
            order.append(index)
    if NUM_CUE_RE.search(question):
        numeric = [i for i, part in enumerate(parts) if data_numbers(part)]
        for index in ([numeric[0]] if numeric else []) + ([numeric[-1]] if numeric else []):
            if index not in order:
                order.append(index)
    for index in sorted(range(len(parts)), key=lambda i: (-scores[i], i)):
        if index not in order:
            order.append(index)

    chosen: list[int] = []
    used = 0
    for index in order:
        cost = len(parts[index]) + (3 if chosen else 0)
        if used + cost <= allocation:
            chosen.append(index)
            used += cost
    chosen.sort()
    return " … ".join(parts[index] for index in chosen)[:allocation]


def refill(record: dict[str, Any], body: str, question: str, policy: str) -> str:
    """Body for a truncated item under W1/W2 (header+summary preserved)."""
    header_room = len(record["summary"]) + 1
    room = len(body) - header_room
    if room < 120:
        return body
    why = str(record.get("why") or "")
    if policy == "W1":
        windowed = fact_window(why, question, room)
    else:
        windowed = anchors_window(why, question, room)
    return f"{record['summary']}\n{windowed}"[: len(body)]


def rebuild_context(case: dict[str, Any], records: dict[int, dict[str, Any]],
                    policy: str) -> str:
    # replace spans item by item using the frozen context as the base
    out = case["context"]
    for memory_id in case["payload_ids"]:
        span, found = item_span(out, memory_id)
        if not found:
            continue
        record = records.get((int(case["case"]), memory_id))
        if record is None:
            continue
        full_body = f"{record['summary']}\n{record['why']}"
        body_start = span.find("\n")
        header = span[:body_start]
        frozen_body = span[body_start + 1:]
        if len(full_body) <= len(frozen_body):
            continue
        new_body = refill(record, frozen_body, case["question"], policy)
        if new_body == frozen_body:
            continue
        out = out.replace(span, header + "\n" + new_body, 1)
    return out


def presence(case: dict[str, Any], context: str) -> tuple[float, bool, list[str]]:
    atoms = item_fact_atoms(str(case["gold"]))
    spans = []
    for memory_id in case["required_ids"]:
        span, found = item_span(context, memory_id)
        if found:
            spans.append(norm(span))
    union = " ".join(spans)
    if not atoms:
        return (1.0, True, [])
    missing = [f"{atom['kind']}:{atom['value']}" for atom in atoms
               if not atom_present(atom, union)]
    present = (len(atoms) - len(missing)) / len(atoms)
    return (round(present, 4), not missing, missing)


def collect(fixture: Path) -> dict[str, Any]:
    cases = [json.loads(line) for line in
             (fixture / "cases.jsonl").read_text(encoding="utf-8").splitlines()
             if line.strip()]
    records = {}
    for line in (fixture / "records.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            records[(int(row["case"]), str(row["id"]))] = row

    per_case: list[dict[str, Any]] = []
    for case in cases:
        numeric = bool(NUM_CUE_RE.search(case["question"]))
        contexts = {"W0": case["context"], "W1": rebuild_context(case, records, "W1")}
        contexts["W2"] = (rebuild_context(case, records, "W2") if numeric
                          else case["context"])
        entry: dict[str, Any] = {"case": case["case"], "block": case["block"],
                                 "cat": case["cat"],
                                 "numeric": bool(NUM_CUE_RE.search(case["question"])),
                                 "gold": case["gold"], "policies": {}}
        for policy in POLICIES:
            rate, all_present, missing = presence(case, contexts[policy])
            entry["policies"][policy] = {"presence": rate,
                                         "all_present": all_present,
                                         "missing": missing,
                                         "chars": len(contexts[policy])}
        per_case.append(entry)

    report: dict[str, Any] = {
        "prereg": "docs/DELIVERY_ANCHORS_V1_PREREG.md",
        "fixture": str(fixture),
        "cases": len(cases),
        "policies": {}, "per_case": per_case, "gates": {},
    }
    for policy in POLICIES:
        total = len(cases)
        all_present = sum(1 for entry in per_case
                          if entry["policies"][policy]["all_present"])
        mean = sum(entry["policies"][policy]["presence"] for entry in per_case) / total
        numeric = [entry for entry in per_case if entry["numeric"]]
        nonnumeric = [entry for entry in per_case if not entry["numeric"]]
        report["policies"][policy] = {
            "all_present_cases": all_present,
            "all_present_rate": round(all_present / total, 4),
            "mean_presence": round(mean, 4),
            "mean_presence_numeric": round(
                sum(entry["policies"][policy]["presence"] for entry in numeric)
                / len(numeric), 4) if numeric else 0.0,
            "mean_presence_nonnumeric": round(
                sum(entry["policies"][policy]["presence"] for entry in nonnumeric)
                / len(nonnumeric), 4) if nonnumeric else 0.0,
        }
    w0, w1, w2 = (report["policies"][key] for key in POLICIES)
    repairs_w1 = sum(1 for entry in per_case
                     if entry["policies"]["W1"]["presence"]
                     > entry["policies"]["W0"]["presence"])
    repairs_w2 = sum(1 for entry in per_case
                     if entry["policies"]["W2"]["presence"]
                     > entry["policies"]["W0"]["presence"])
    regressions_w2 = sum(1 for entry in per_case
                         if entry["policies"]["W2"]["presence"]
                         < entry["policies"]["W0"]["presence"])
    case0 = next(entry for entry in per_case
                 if entry["block"] == "u3a" and entry["case"] == 12)
    report["repairs"] = {"W1": repairs_w1, "W2": repairs_w2}
    w1_numeric = [entry for entry in per_case if entry["numeric"]
                  and entry["policies"]["W1"]["presence"]
                  > entry["policies"]["W0"]["presence"]]
    w2_numeric = [entry for entry in per_case if entry["numeric"]
                  and entry["policies"]["W2"]["presence"]
                  > entry["policies"]["W0"]["presence"]]
    report["gates"] = {
        "D1_no_regression": regressions_w2 == 0,
        "D2_numeric_mean": (w2["mean_presence_numeric"]
                            >= w1["mean_presence_numeric"]),
        "D3_case0_anchor": (case0["policies"]["W1"]["presence"]
                            < case0["policies"]["W0"]["presence"]
                            and case0["policies"]["W2"]["presence"]
                            >= case0["policies"]["W0"]["presence"]),
        "D4_numeric_repairs": len(w2_numeric) >= max(1, len(w1_numeric)),
        "D5_nonnumeric_unchanged": all(
            entry["policies"]["W2"]["presence"] == entry["policies"]["W0"]["presence"]
            for entry in per_case if not entry["numeric"]),
        "D6_budget": all(
            entry["policies"][policy]["chars"] <= entry["policies"]["W0"]["chars"]
            for entry in per_case for policy in ("W1", "W2")),
    }
    report["case0"] = case0
    return report


def content_digest(report: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(report, sort_keys=True,
                                     ensure_ascii=False).encode("utf-8")).hexdigest()


def run(fixture: Path) -> dict[str, Any]:
    report = collect(fixture)
    first = content_digest(report)
    second = content_digest(collect(fixture))
    report["determinism"] = {"run1": first, "run2": second,
                             "identical": first == second}
    report["gates"]["D7_determinism"] = first == second
    report["all_pass"] = all(report["gates"].values())
    return report


def render(report: dict[str, Any]) -> list[str]:
    lines = ["# delivery-anchors-v1 (lab)", "",
             f"- cases: {report['cases']} · repairs W1/W2: "
             f"{report['repairs']['W1']}/{report['repairs']['W2']}", "",
             "| arm | all-present | mean presence | numeric | non-numeric |",
             "|---|---:|---:|---:|---:|"]
    for policy in POLICIES:
        data = report["policies"][policy]
        lines.append(f"| {policy} | {data['all_present_cases']}/{report['cases']} "
                     f"| {data['mean_presence']:.3f} | "
                     f"{data['mean_presence_numeric']:.3f} | "
                     f"{data['mean_presence_nonnumeric']:.3f} |")
    lines += ["", f"gates: {json.dumps(report['gates'], sort_keys=True)}",
              f"all_pass: {report['all_pass']}", "",
              "## case u3a-12 (16GB anchor)",
              json.dumps(report["case0"]["policies"], sort_keys=True)]
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture",
                        default=str(HERE / "fixtures" / "composition_u4"))
    parser.add_argument("--out",
                        default=str(HERE / "results" / "delivery_anchors_v1"))
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    report = run(Path(args.fixture))
    (out / "report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8")
    markdown = "\n".join(render(report)) + "\n"
    (out / "report.md").write_text(markdown, encoding="utf-8")
    print(markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
