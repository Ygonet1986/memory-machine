#!/usr/bin/env python3
"""diagnostic-trace-v1: four-stage per-case trace (origin/ingestion/delivery/answer).

Frozen by docs/DIAGNOSTIC_TRACE_V1_PREREG.md. Cases u3a-12/19/22 and u3b-27,
arms W0/W1/W3, N=3 answers on frozen contexts with the same answerer and the
frozen blind judge.

    PYTHONPATH=src:.:eval python3 eval/diagnostic_trace_v1.py --skip-llm
    PYTHONPATH=src:.:eval python3 eval/diagnostic_trace_v1.py
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

import delivery_anchors_v1 as da  # noqa: E402
import delivery_combined_v1 as dc  # noqa: E402
from fact_presence import atom_present, item_fact_atoms, item_span, norm  # noqa: E402

TRACKED = (("u3a", 12), ("u3a", 19), ("u3a", 22), ("u3b", 27))
POLICIES = ("W0", "W1", "W3")
RUNS = 3
VALUE_RE = re.compile(r"\b\d+(?:[.,]\d+)?\b|[a-z]{4,}", re.IGNORECASE)


def gold_values(case: dict[str, Any]) -> list[str]:
    values = []
    for atom in item_fact_atoms(str(case["gold"])):
        if atom["kind"] in {"number", "date", "entity"}:
            values.append(str(atom["value"]))
    return values


def stage_checks(case: dict, records: dict, context: str) -> dict[str, Any]:
    atoms = item_fact_atoms(str(case["gold"]))
    record_texts = []
    provenance_ok = True
    for memory_id in case["required_ids"]:
        record = records.get((int(case["case"]), memory_id))
        if record is None:
            provenance_ok = False
            continue
        record_texts.append(norm(f"{record['summary']} {record['why']}"))
        provenance_ok = provenance_ok and bool(record.get("id")) and \
            bool(record.get("created_at")) and bool(record.get("source"))
    record_union = " ".join(record_texts)

    spans = []
    for memory_id in case["required_ids"]:
        span, found = item_span(context, memory_id)
        if found:
            spans.append(norm(span))
    payload_union = " ".join(spans)

    def missing(union: str) -> list[str]:
        return [f"{atom['kind']}:{atom['value']}" for atom in atoms
                if not atom_present(atom, union)]

    record_excerpt = record_union[:240].replace("\n", " ")
    payload_excerpt = payload_union[:240].replace("\n", " ")
    return {
        "context_sha256": hashlib.sha256(context.encode("utf-8")).hexdigest(),
        "record_excerpt": record_excerpt,
        "payload_excerpt": payload_excerpt,
        "origin_missing": missing(record_union),
        "origin_ok": not missing(record_union),
        "origin_basis": "record_text",
        "provenance_ok": provenance_ok,
        "ingestion_missing": missing(record_union),
        "ingestion_ok": not missing(record_union),
        "delivery_missing": missing(payload_union),
        "delivery_ok": not missing(payload_union),
    }


def answer_stage(case: dict, context: str, runs: int, clients: Any) -> dict[str, Any]:
    from memory_machine.main_chatbot import run_main_chatbot
    from memory_machine.whiteboard import Whiteboard
    from e2e_bench import judge

    answerer, judge_client = clients
    values = gold_values(case)
    verdicts = []
    used = 0
    samples = []
    for _ in range(runs):
        whiteboard = Whiteboard()
        whiteboard.subject = case["question"]
        try:
            answer, _mem, _reason = run_main_chatbot(
                answerer, whiteboard, case["question"],
                extra_context=context, temperature=0.0)
            verdict, reason = judge(judge_client, case["question"],
                                    str(case["gold"]), answer.strip())
        except Exception as error:
            verdicts.append("infra_error")
            samples.append({"verdict": "infra_error",
                            "reason": type(error).__name__})
            continue
        answer_norm = norm(answer)
        value_used = False
        if values:
            value_used = any(norm(value) in answer_norm for value in values)
        used += 1 if value_used else 0
        verdicts.append(verdict)
        samples.append({"verdict": verdict, "value_used": value_used,
                        "answer": answer.strip()[:200],
                        "reason": reason[:200]})
    return {"verdicts": verdicts, "value_used_runs": used, "runs": runs,
            "samples": samples}


def collect(*, skip_llm: bool) -> tuple[list[dict], dict[str, Any]]:
    cases, records = dc.load_fixture(HERE / "fixtures" / "composition_u4")
    selected = [case for case in cases
                if (case["block"], case["case"]) in TRACKED]
    clients = None
    if not skip_llm:
        from memory_machine.config import Config
        from memory_machine.llm import LLMClient
        from view_router_bench import CountingClient

        import os
        key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
        if not key:
            raise RuntimeError("DEEPSEEK_API_KEY is not set")
        config = Config()
        clients = (CountingClient(LLMClient("https://api.deepseek.com", key,
                                            config.model, retries=1)),
                   CountingClient(LLMClient("https://api.deepseek.com", key,
                                            config.model, retries=1)))

    rows: list[dict] = []
    for case in selected:
        contexts = dc.contexts(case, records)
        for policy in POLICIES:
            row = {"block": case["block"], "case": case["case"],
                   "question": case["question"], "gold": case["gold"],
                   "arm": policy, "context_chars": len(contexts[policy])}
            row.update(stage_checks(case, records, contexts[policy]))
            if clients is not None:
                row["answer"] = answer_stage(case, contexts[policy], RUNS, clients)
            rows.append(row)

    consistency = all(
        row["answer"]["value_used_runs"] == 0 or row["delivery_ok"]
        for row in rows if "answer" in row)
    summary = {
        "cases": sorted({f"{r['block']}:{r['case']}" for r in rows}),
        "arms": list(POLICIES), "runs": RUNS,
        "T1_stage_consistency": consistency,
        "rows": len(rows),
        "llm_calls": (clients[0].calls + clients[1].calls) if clients else 0,
    }
    return rows, summary


def render(rows: list[dict], summary: dict[str, Any]) -> list[str]:
    lines = ["# diagnostic-trace-v1", "",
             f"- cases: {summary['cases']} · arms: {summary['arms']} · "
             f"runs: {summary['runs']} · llm calls: {summary['llm_calls']}",
             f"- T1 stage consistency: {summary['T1_stage_consistency']}", "",
             "| case | arm | origin | ingestion | delivery | answer verdicts | value used |",
             "|---|---|---|---|---|---|---|"]
    for row in rows:
        answer = row.get("answer")
        verdicts = "/".join(answer["verdicts"]) if answer else "-"
        used = f"{answer['value_used_runs']}/{answer['runs']}" if answer else "-"
        lines.append(f"| {row['block']}:{row['case']} | {row['arm']} | "
                     f"{'ok' if row['origin_ok'] else 'MISS ' + ','.join(row['origin_missing'])} | "
                     f"{'ok' if row['ingestion_ok'] else 'MISS'} | "
                     f"{'ok' if row['delivery_ok'] else 'MISS ' + ','.join(row['delivery_missing'])} | "
                     f"{verdicts} | {used} |")
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out",
                        default=str(HERE / "results" / "diagnostic_trace_v1"))
    parser.add_argument("--skip-llm", action="store_true")
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    rows, summary = collect(skip_llm=args.skip_llm)
    (out / "trace.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
                for row in rows), encoding="utf-8")
    report = {"prereg": "docs/DIAGNOSTIC_TRACE_V1_PREREG.md",
              "summary": summary, "rows": rows}
    (out / "report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8")
    markdown = "\n".join(render(rows, summary)) + "\n"
    (out / "report.md").write_text(markdown, encoding="utf-8")
    print(markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
