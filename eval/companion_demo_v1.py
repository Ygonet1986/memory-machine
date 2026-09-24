#!/usr/bin/env python3
"""companion-demo-v1: scripted §7 demonstration against the real engine.

Frozen by docs/COMPANION_DEMO_V1_PREREG.md. One-shot; real LLM
(``DEEPSEEK_API_KEY``); temporary relationship roots; gates G1-G7.

    PYTHONPATH=src python3 eval/companion_demo_v1.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from app.companion_backend import CompanionBackend  # noqa: E402
from memory_machine.companion_memory import CompanionMemory  # noqa: E402
from memory_machine.groups import ensure_group, load_manifest, save_manifest  # noqa: E402
from memory_machine.llm import LLMClient  # noqa: E402
from memory_machine.tape import MemoryRecord, parse_id  # noqa: E402

FIXTURE = HERE / "fixtures" / "companion_demo_v1"
RESULTS = HERE / "results" / "companion_demo_v1"


def _load_fixture() -> tuple[dict[str, Any], dict[str, Any]]:
    script_text = (FIXTURE / "script.json").read_text(encoding="utf-8")
    manifest = json.loads((FIXTURE / "manifest.json").read_text(encoding="utf-8"))
    digest = hashlib.sha256(script_text.encode("utf-8")).hexdigest()
    assert digest == manifest["script_sha256"], "fixture hash mismatch"
    return json.loads(script_text), manifest


def _contains(reply: str, token: str) -> bool:
    return token.casefold() in (reply or "").casefold()


def _record_types(backend: CompanionBackend, ids: list[str]) -> list[str]:
    tape = CompanionMemory(backend.session.root).tape
    by_id = {record.id: record for record in tape.read()}
    return [by_id[memory_id].type for memory_id in ids if memory_id in by_id]


def _statuses(backend: CompanionBackend, ids: list[str]) -> dict[str, str]:
    tape = CompanionMemory(backend.session.root).tape
    by_id = {record.id: record for record in tape.read()}
    return {memory_id: by_id[memory_id].status for memory_id in ids
            if memory_id in by_id}


def _write_report(path: Path, report: dict[str, Any]) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8")
    lines = ["# companion-demo-v1", "",
             f"- model: {report['model']}",
             f"- calls: {report['total_calls']} (budget {report['budget_calls']})",
             f"- gates: {json.dumps(report['gates'], sort_keys=True)}",
             f"- all_pass: {report['all_pass']}", "",
             "| step | kind | checks | calls | latency s |",
             "|---|---|---|---|---|"]
    for row in report["rows"]:
        lines.append(
            f"| {row['id']} | {row['kind']} | "
            f"{json.dumps(row.get('checks', {}), sort_keys=True)} | "
            f"{row.get('calls', '')} | {row.get('latency_s', '')} |")
    (path / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(script: dict[str, Any], out: Path, model: str,
        base: Path) -> dict[str, Any]:
    key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not key:
        raise SystemExit("DEEPSEEK_API_KEY is not set")
    client = LLMClient("https://api.deepseek.com", key, model, retries=1)
    backend = CompanionBackend("demo", "lia", "main", client=client, base=base)
    approval = backend.approve_persona(ROOT / script["persona"])
    if not approval.get("ok"):
        raise SystemExit(f"persona approval failed: {approval}")

    rows: list[dict[str, Any]] = []
    targets: dict[str, str] = {}
    provided_seen: set[str] = set()
    trailer_failures = 0
    total_calls = 0
    g7_report = g7_story = False
    g5_ok = True

    for step in script["steps"]:
        kind = step["kind"]
        if kind == "turn":
            started = time.time()
            result = backend.turn(step["message"], save=step.get("save", True))
            latency = round(time.time() - started, 2)
            checks: dict[str, Any] = {}
            if not result.get("ok"):
                checks["turn"] = f"error: {result.get('error')}"
            else:
                reply = result.get("reply", "")
                for token in step.get("must_contain", []):
                    checks[f"contain:{token}"] = _contains(reply, token)
                for token in step.get("must_not_contain", []):
                    checks[f"forbid:{token}"] = not _contains(reply, token)
                if step.get("expect_used"):
                    checks["used_nonempty"] = bool(result.get("used"))
                violations = result.get("violations") or []
                hygiene = [v for v in violations
                           if v.get("kind") in {"missing_trailer", "unknown_used"}]
                checks["trailer_ok"] = not hygiene
                if hygiene:
                    g5_ok = False
                    trailer_failures += len(hygiene)
                provided_seen.update(result.get("provided") or [])
                saved_ids = (result.get("saved") or {}).get("records") or []
                types = _record_types(backend, saved_ids)
                if step.get("expect_record_types"):
                    checks["record_types"] = types
                    for wanted in step["expect_record_types"]:
                        checks[f"wrote:{wanted}"] = wanted in types
                    if step["id"] == "t1" and "person_report" in types:
                        g7_report = True
                        index = types.index("person_report")
                        targets["report_from:t1"] = saved_ids[index]
                    if step["id"] == "t6" and "story" in types:
                        g7_story = True
                checks["used"] = [item["memory_id"] for item in result.get("used") or []]
                total_calls += int(result.get("calls") or 0)
            rows.append({"id": step["id"], "kind": kind,
                         "reply": result.get("reply", ""), "checks": checks,
                         "calls": result.get("calls"), "latency_s": latency,
                         "violations": result.get("violations") or []})
        elif kind == "correct":
            target = targets.get(step["target"], "")
            outcome = backend.correct(target, step["summary"])
            new_id = (outcome.get("record") or {}).get("memory_id", "")
            statuses = _statuses(backend, [target, new_id]) if new_id else {}
            targets[f"corrected_from:{step['id']}"] = new_id
            rows.append({"id": step["id"], "kind": kind, "checks": {
                "ok": bool(outcome.get("ok")),
                "target": target,
                "replacement": new_id,
                "old_status": statuses.get(target, ""),
                "new_status": statuses.get(new_id, ""),
            }})
        elif kind == "delete":
            target = targets.get(step["target"], "")
            outcome = backend.delete(target)
            rows.append({"id": step["id"], "kind": kind, "checks": {
                "ok": bool(outcome.get("ok")),
                "target": target,
                "removed": outcome.get("removed") or [],
            }})
        elif kind == "isolation":
            other = step["other"]
            other_backend = CompanionBackend(
                other["person"], other["character"], other["continuity"],
                client=client, base=base)
            if not other_backend.approve_persona(ROOT / script["persona"]).get("ok"):
                raise SystemExit("isolation persona approval failed")
            other_memory = CompanionMemory(other_backend.session.root)
            appended = other_memory.tape.append(MemoryRecord(
                type="person_report", summary=other["report"], author="person",
                source="demo#b1",
                origin={"kind": "turn", "turn_ids": ["b1"]}))
            manifest = load_manifest(other_backend.session.root / "manifest.json")
            ensure_group(manifest, parse_id(appended.id))
            save_manifest(manifest, other_backend.session.root / "manifest.json")

            result = backend.turn(step["message"], save=True)
            reply = result.get("reply", "")
            leaked = [memory_id for memory_id in (
                list(result.get("provided") or [])
                + [item["memory_id"] for item in result.get("used") or []])
                if memory_id == appended.id]
            checks = {f"forbid:{token}": not _contains(reply, token)
                      for token in step.get("must_not_contain", [])}
            checks["structural"] = not leaked
            total_calls += int(result.get("calls") or 0)
            rows.append({"id": step["id"], "kind": kind,
                         "reply": reply, "checks": checks,
                         "calls": result.get("calls")})

    def step_ok(step_id: str, key: str) -> bool:
        row = next((r for r in rows if r["id"] == step_id), None)
        return bool(row and row["checks"].get(key))

    correction = next(r for r in rows if r["id"] == "c1")["checks"]
    gates = {
        "G1_fiction": step_ok("t7", "forbid:biblioteca")
        and step_ok("t7", "forbid:ilha"),
        "G2_deletion": step_ok("t8", "forbid:mãe")
        and step_ok("t8", "forbid:irmã"),
        "G3_correction": step_ok("t5", "contain:mãe")
        and step_ok("t5", "forbid:irmã")
        and correction.get("old_status") == "superseded"
        and correction.get("new_status") == "active",
        "G4_isolation": step_ok("i1", "forbid:astronomia")
        and step_ok("i1", "structural"),
        "G5_trailer": g5_ok,
        "G6_budget": total_calls <= int(script["budget_calls"]),
        "G7_extraction": g7_report and g7_story,
    }
    report = {
        "prereg": "docs/COMPANION_DEMO_V1_PREREG.md",
        "fixture_sha256": hashlib.sha256(
            (FIXTURE / "script.json").read_text(encoding="utf-8").encode()
        ).hexdigest(),
        "model": model,
        "budget_calls": script["budget_calls"],
        "total_calls": total_calls,
        "trailer_failures": trailer_failures,
        "rows": rows,
        "gates": gates,
        "all_pass": all(gates.values()),
        "base": str(base),
        "scope": ("lab-only demo of the Companion stack; nothing promoted; "
                  "opencode/window untouched"),
    }
    _write_report(out, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(RESULTS))
    parser.add_argument("--model", default="deepseek-v4-flash")
    parser.add_argument("--base", default="")
    args = parser.parse_args()
    script, _manifest = _load_fixture()
    base = Path(args.base) if args.base else Path(
        tempfile.mkdtemp(prefix="companion-demo-"))
    report = run(script, Path(args.out), args.model, base)
    print(json.dumps({"gates": report["gates"],
                      "all_pass": report["all_pass"],
                      "total_calls": report["total_calls"]},
                     indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
