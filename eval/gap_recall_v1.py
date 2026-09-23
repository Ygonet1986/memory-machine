#!/usr/bin/env python3
"""gap-recall-v1: bounded, gap-directed second search (R1-R6).

Frozen by docs/GAP_RECALL_V1_PREREG.md. Deterministic, no LLM. Pass 1 is the
default retrieval+window; the gap detector (questions demanding a value, a
date or two components vs the delivered text) triggers at most two directed
lexical queries against the tape, with a full audit log of what each query
found and what changed.

    PYTHONPATH=src:.:eval python3 eval/gap_recall_v1.py
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

from memory_machine.payload import fact_window  # noqa: E402
from memory_machine.retrieval import bm25, rank, tokenize  # noqa: E402

FIXTURE = HERE / "fixtures" / "gap_recall_v1"
RESULTS = HERE / "results" / "gap_recall_v1"
ALLOCATION = 3600
K_PASS1 = 3
K_BREADTH = 4  # equal-budget breadth control: exactly one extra record
MAX_DIRECTED = 2
ARMS = ("G0", "G1", "G2", "G3")
ANSWER_CASES = ("C01", "C05", "C09")
ANSWER_ARMS = ("G0", "G1")
RUNS = 3
CUE_WORDS = {"when", "much", "amount", "cost", "spend", "total", "price",
             "date", "paid", "pay", "combined", "how", "was", "the", "and"}
NUM_CUE = re.compile(r"(?i)\bhow much\b|\bamount\b|\bcost\b|\bspend\b|"
                     r"\btotal\b|\bprice\b")
DATE_CUE = re.compile(r"(?i)\bwhen\b|\bdate\b")
TWO_ITEMS = re.compile(r"(?i)\band the\b")
MONEY_RE = re.compile(r"\$\s?[\d,]+")
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
SENTENCE_RE = re.compile(r"(?<=\.)\s+")


def load_cases() -> list[dict[str, Any]]:
    return [json.loads(line) for line in
            (FIXTURE / "cases.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()]


def record_text(record: dict[str, Any]) -> str:
    return f"{record['summary']} {record['why']}".strip()


def docs_of(case: dict[str, Any]) -> list[str]:
    return [record_text(r) for r in case["records"]]


def demand(question: str) -> dict[str, int]:
    """Declared demand model: numeral count and date, from question cues."""
    numerals = 0
    if NUM_CUE.search(question):
        numerals = 2 if TWO_ITEMS.search(question) else 1
    return {"numerals": numerals, "date": 1 if DATE_CUE.search(question) else 0}


def detect_gaps(question: str, delivered: str) -> list[dict[str, Any]]:
    want = demand(question)
    have = {"numerals": len(MONEY_RE.findall(delivered)),
            "date": 1 if DATE_RE.search(delivered) else 0}
    gaps = []
    for kind in ("numerals", "date"):
        if have[kind] < want[kind]:
            gaps.append({"kind": kind, "missing": want[kind] - have[kind]})
    return gaps


def entity_terms(question: str) -> list[str]:
    return [t for t in tokenize(question) if t not in CUE_WORDS]


def directed_queries(question: str) -> list[str]:
    """One directed query per demanded type (numeral, date); max two."""
    want = demand(question)
    base = " ".join(entity_terms(question))
    queries = []
    if want["numerals"]:
        queries.append(f"{base} invoice amount")
    if want["date"]:
        queries.append(f"{base} payment date")
    return queries[:MAX_DIRECTED]


def is_complete(case: dict[str, Any], delivered: str) -> bool:
    return not detect_gaps(case["question"], delivered)


def pass_window(case: dict[str, Any], index: int, query: str) -> str:
    record = case["records"][index]
    room = ALLOCATION - len(record["summary"]) - 1
    return f"{record['summary']}\n{fact_window(record['why'], query, room)}"


def pass1(case: dict[str, Any], k: int = K_PASS1) -> dict[str, Any]:
    docs = docs_of(case)
    order = [index for index, _score in rank(case["question"], docs, limit=k)]
    delivered = "\n".join(pass_window(case, index, case["question"])
                          for index in order)
    return {"consulted": order, "delivered": delivered,
            "queries": [case["question"]]}


def gap_recall(case: dict[str, Any]) -> dict[str, Any]:
    first = pass1(case)
    consulted = list(first["consulted"])
    delivered = first["delivered"]
    audit = []
    queries = list(first["queries"])
    docs = docs_of(case)
    directed_extra = 0
    for query in directed_queries(case["question"]):
        gaps = detect_gaps(case["question"], delivered)
        if not gaps:
            break
        scores = bm25(query, docs)
        candidates = [i for i in sorted(range(len(docs)),
                                        key=lambda i: -scores[i])
                      if i not in consulted and scores[i] > 0]
        if not candidates:
            audit.append({"gap": gaps, "query": query, "records": [],
                          "exhausted": True, "complete_before": False,
                          "complete_after": is_complete(case, delivered)})
            directed_extra += 1
            queries.append(query)
            continue
        index = candidates[0]
        before = is_complete(case, delivered)
        delivered = f"{delivered}\n{pass_window(case, index, query)}"
        after = is_complete(case, delivered)
        consulted.append(index)
        directed_extra += 1
        queries.append(query)
        audit.append({"gap": gaps, "query": query,
                      "records": [case["records"][index]["memory_id"]],
                      "exhausted": False, "complete_before": before,
                      "complete_after": after})
    return {"consulted": consulted, "delivered": delivered, "queries": queries,
            "directed_extra": directed_extra, "audit": audit}


def oracle(case: dict[str, Any]) -> dict[str, Any]:
    indices = [0] + [i for i, r in enumerate(case["records"])
                     if r["memory_id"] in case.get("missing_records", [])]
    delivered = "\n".join(pass_window(case, i, case["question"])
                          for i in dict.fromkeys(indices))
    return {"consulted": list(dict.fromkeys(indices)), "delivered": delivered,
            "queries": []}


def run_arm(case: dict[str, Any], arm: str) -> dict[str, Any]:
    if arm == "G0":
        return pass1(case)
    if arm == "G1":
        return gap_recall(case)
    if arm == "G2":
        return pass1(case, k=K_BREADTH)
    return oracle(case)


def evaluate(cases: list[dict[str, Any]]) -> dict[str, Any]:
    rows = []
    for case in cases:
        row = {"case_id": case["case_id"], "kind": case["kind"],
               "arms": {}}
        for arm in ARMS:
            result = run_arm(case, arm)
            row["arms"][arm] = {
                "consulted": result["consulted"],
                "complete": is_complete(case, result["delivered"]),
                "gaps": detect_gaps(case["question"], result["delivered"]),
                "directed_extra": result.get("directed_extra", 0),
                "audit": result.get("audit", []),
            }
        rows.append(row)

    gap_cases = [r for r in rows if r["kind"] != "control"]
    controls = [r for r in rows if r["kind"] == "control"]
    recovered = [r["case_id"] for r in gap_cases
                 if not r["arms"]["G0"]["complete"] and r["arms"]["G1"]["complete"]]
    complete = {arm: sum(1 for r in rows if r["arms"][arm]["complete"])
                for arm in ARMS}
    attributed = sum(
        1 for r in gap_cases
        if r["case_id"] in recovered
        and any(e["complete_before"] is False and e["complete_after"] is True
                for e in r["arms"]["G1"]["audit"]))
    extra = sum(r["arms"]["G1"]["directed_extra"] for r in rows)
    control_triggers = sum(r["arms"]["G1"]["directed_extra"] for r in controls)
    max_extra = max(r["arms"]["G1"]["directed_extra"] for r in rows)
    return {
        "rows": rows,
        "complete": complete,
        "gap_cases": len(gap_cases),
        "recovered": recovered,
        "gates": {
            "R1_no_loss": all(r["arms"]["G1"]["complete"]
                              for r in rows if r["arms"]["G0"]["complete"]),
            "R2_recovery": complete["G1"] > complete["G0"],
            "R3_direction": complete["G1"] > complete["G2"],
            "R4_budget": (control_triggers == 0
                          and max_extra <= MAX_DIRECTED
                          and extra <= len(rows)),
            "R6_audit": attributed == len(recovered) and len(recovered) > 0,
        },
        "budget": {"directed_extra_total": extra,
                   "control_triggers": control_triggers,
                   "max_extra_per_case": max_extra,
                   "mean_extra_per_case": round(extra / len(rows), 4)},
    }


def explore_segment_search() -> dict[str, Any]:
    """Declared EXPLORATORY: fact hidden by the W1 window in the old frozen
    fixtures (money_holdout_v2: single target; multi_component_holdout_v1:
    both components); the directed sentence search appends the best
    numeral-bearing sentence matching the directed query. Not gated."""
    readings = {}
    for name in ("money_holdout_v2", "multi_component_holdout_v1"):
        fixture = HERE / "fixtures" / name
        cases = [json.loads(line) for line in
                 (fixture / "cases.jsonl").read_text(encoding="utf-8").splitlines()
                 if line.strip()]
        w1_found = directed_found = 0
        for case in cases:
            record = case["records"][0]
            room = ALLOCATION - len(record["summary"]) - 1
            window = fact_window(record["why"], case["question"], room)
            if "components" in case:
                wanted = [f"${value}" for value in case["components"]]
            else:
                wanted = [f"${case['target']}"]
            w1_found += 1 if all(w in window for w in wanted) else 0
            query = f"{' '.join(entity_terms(case['question']))} invoice amount"
            q_tokens = set(tokenize(query))
            best_sentence, best_score = "", -1
            for sentence in SENTENCE_RE.split(record["why"]):
                if not MONEY_RE.search(sentence):
                    continue
                score = len(q_tokens & set(tokenize(sentence)))
                if score > best_score:
                    best_sentence, best_score = sentence, score
            directed = f"{window}\n{best_sentence}" if best_sentence else window
            directed_found += 1 if all(w in directed for w in wanted) else 0
        readings[name] = {"cases": len(cases), "w1_found": w1_found,
                          "directed_found": directed_found}
    return readings


def answer_stage(cases: list[dict[str, Any]]) -> dict[str, Any]:
    """Answer addendum (36 calls): same answerer + blind judge, G0 vs G1."""
    from memory_machine.config import Config
    from memory_machine.llm import LLMClient
    from memory_machine.main_chatbot import run_main_chatbot
    from memory_machine.whiteboard import Whiteboard
    from e2e_bench import judge
    from view_router_bench import CountingClient
    import os

    key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not key:
        raise RuntimeError("DEEPSEEK_API_KEY is not set")
    config = Config()
    answerer = CountingClient(LLMClient("https://api.deepseek.com", key,
                                        config.model, retries=1))
    judge_client = CountingClient(LLMClient("https://api.deepseek.com", key,
                                            config.model, retries=1))
    by_id = {case["case_id"]: case for case in cases}
    entries = []
    failures = 0
    for case_id in ANSWER_CASES:
        case = by_id[case_id]
        entry = {"case_id": case_id, "kind": case["kind"],
                 "gold": case["gold"], "arms": {}}
        for arm in ANSWER_ARMS:
            delivered = run_arm(case, arm)["delivered"]
            verdicts = []
            for _ in range(RUNS):
                whiteboard = Whiteboard()
                whiteboard.subject = case["question"]
                try:
                    reply, _m, _r = run_main_chatbot(
                        answerer, whiteboard, case["question"],
                        extra_context=delivered, temperature=0.0)
                    verdict, _reason = judge(judge_client, case["question"],
                                             str(case["gold"]), reply.strip())
                except Exception as error:
                    verdict = f"infra_error:{type(error).__name__}"
                    failures += 1
                verdicts.append(verdict)
            entry["arms"][arm] = verdicts
        entries.append(entry)

    def score(case_id: str, arm: str) -> float:
        entry = next(e for e in entries if e["case_id"] == case_id)
        return sum({"correct": 1.0, "partial": 0.5}.get(v, 0.0)
                   for v in entry["arms"][arm]) / RUNS

    score_g0 = sum(score(cid, "G0") for cid in ANSWER_CASES)
    score_g1 = sum(score(cid, "G1") for cid in ANSWER_CASES)
    return {"cases": entries, "score_g0": round(score_g0, 4),
            "score_g1": round(score_g1, 4),
            "llm_calls": answerer.calls + judge_client.calls,
            "failures": failures,
            "gates": {"A1_answers": score_g1 > score_g0,
                      "A2_infra": failures <= 0.2 * RUNS * len(ANSWER_ARMS)
                      * len(ANSWER_CASES)}}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(RESULTS))
    parser.add_argument("--no-explore", action="store_true")
    parser.add_argument("--skip-llm", action="store_true")
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    cases = load_cases()
    report = evaluate(cases)
    second = evaluate(cases)
    report["gates"]["R5_determinism"] = (
        json.dumps(report["rows"], sort_keys=True)
        == json.dumps(second["rows"], sort_keys=True))
    if not args.skip_llm:
        report["answer"] = answer_stage(cases)
        report["gates"].update(report["answer"]["gates"])
    report["all_pass"] = all(report["gates"].values())
    report["prereg"] = "docs/GAP_RECALL_V1_PREREG.md"
    report["scope"] = ("lab-only: mechanism test with distinct-record gaps; "
                       "easy controls must stay at one pass; no product or "
                       "economy claim; windows OFF; shadow/track S untouched")
    if not args.no_explore:
        report["exploratory"] = explore_segment_search()
    (out / "report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8")
    lines = ["# gap-recall-v1", "",
             f"- complete: {json.dumps(report['complete'], sort_keys=True)}",
             f"- recovered (gap cases): {len(report['recovered'])}/"
             f"{report['gap_cases']} {report['recovered']}",
             f"- budget: {json.dumps(report['budget'], sort_keys=True)}", "",
             "| case | kind | G0 | G1 | G2 | G3 | extra |",
             "|---|---|---|---|---|---|---|"]
    for row in report["rows"]:
        lines.append(
            f"| {row['case_id']} | {row['kind']} | "
            f"{row['arms']['G0']['complete']} | {row['arms']['G1']['complete']} | "
            f"{row['arms']['G2']['complete']} | {row['arms']['G3']['complete']} | "
            f"{row['arms']['G1']['directed_extra']} |")
    lines += ["", f"gates: {json.dumps(report['gates'], sort_keys=True)}",
              f"all_pass: {report['all_pass']}"]
    if "answer" in report:
        lines += ["", "| answer case | kind | G0 | G1 |", "|---|---|---|---|"]
        for entry in report["answer"]["cases"]:
            lines.append(f"| {entry['case_id']} | {entry['kind']} | "
                         f"{'/'.join(entry['arms']['G0'])} | "
                         f"{'/'.join(entry['arms']['G1'])} |")
        lines += [f"- scores: G0 {report['answer']['score_g0']} vs G1 "
                  f"{report['answer']['score_g1']} "
                  f"(calls {report['answer']['llm_calls']}, failures "
                  f"{report['answer']['failures']})"]
    if "exploratory" in report:
        lines += ["", "exploratory (segment search on frozen fixtures, not gated):",
                  f"{json.dumps(report['exploratory'], sort_keys=True)}"]
    markdown = "\n".join(lines) + "\n"
    (out / "report.md").write_text(markdown, encoding="utf-8")
    print(markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
