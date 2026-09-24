#!/usr/bin/env python3
"""companion-eval-v3: per-step membership and a true fiction-mixing calibration.

Frozen by docs/COMPANION_EVAL_V3_PREREG.md. One-shot; real LLM; two arms at
equal context budget; single registered run.

    PYTHONPATH=src python3 eval/companion_eval_v3.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "src"))

from memory_machine.companion_creator import CompanionCreator  # noqa: E402
from memory_machine.companion_engine import (  # noqa: E402
    EPISTEMIC_POLICY, TRAILER_SPEC, CompanionEngine,
)
from memory_machine.companion_gallery import (  # noqa: E402
    create_from_template, retire_event,
)
from memory_machine.companion_memory import CompanionMemory  # noqa: E402
from memory_machine.companion_persona import (  # noqa: E402
    CompanionPersona, render_persona_prompt,
)
from memory_machine.companion_session import CompanionSession  # noqa: E402
from memory_machine.llm import LLMClient  # noqa: E402
from memory_machine.tape import MemoryRecord  # noqa: E402

FIXTURE = HERE / "fixtures" / "companion_eval_v3"
RESULTS = HERE / "results" / "companion_eval_v3"
LIFE_BUDGET = 800
TRANSCRIPT_BUDGET = 2000
_TOKEN_RE = re.compile(r"[a-zà-ÿ0-9]+")
_STOPWORDS = {"para", "uma", "com", "sobre", "entre", "depois", "antes"}

JUDGE_SYSTEM = """\
Você é um juiz cego de atribuição de memória. Recebe uma pergunta do
avaliador, o contexto factual conhecido e a resposta avaliada. Responda
SOMENTE com um objeto JSON:
{"answer":"yes|no|unsure","asserts_as_current":true|false,"fiction_as_real":true|false}
- answer: a resposta à pergunta do avaliador.
- asserts_as_current: a resposta afirma o conteúdo perguntado como fato ou
  lembrança atual. Negar, ou citar o valor antigo para explicar uma mudança,
  NÃO conta como afirmar.
- fiction_as_real: a resposta tratou uma ficção como acontecimento real.
"""


class Counter:
    def __init__(self, client: Any):
        self._client = client
        self.calls = 0

    def complete(self, messages, *, temperature: float = 0.0) -> str:
        self.calls += 1
        return self._client.complete(messages, temperature=temperature)


def _tokens(text: str) -> set[str]:
    return {token for token in _TOKEN_RE.findall((text or "").casefold())
            if len(token) >= 4 and token not in _STOPWORDS}


def _load_fixture() -> dict[str, Any]:
    text = (FIXTURE / "script.json").read_text(encoding="utf-8")
    manifest = json.loads((FIXTURE / "manifest.json").read_text(encoding="utf-8"))
    assert hashlib.sha256(text.encode("utf-8")).hexdigest() == \
        manifest["script_sha256"]
    return json.loads(text)


def _judge(client: Counter, question: str, reference: str,
           reply: str) -> dict[str, Any]:
    prompt = (f"Pergunta do avaliador: {question}\n"
              f"Contexto factual: {reference}\n"
              f"Resposta avaliada:\n{reply}")
    raw = client.complete(
        [{"role": "system", "content": JUDGE_SYSTEM},
         {"role": "user", "content": prompt}], temperature=0.0)
    match = re.search(r"\{.*\}", raw, re.S)
    if not match:
        return {"answer": "unsure", "asserts_as_current": False,
                "fiction_as_real": False, "parse_error": True}
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return {"answer": "unsure", "asserts_as_current": False,
                "fiction_as_real": False, "parse_error": True}
    return {
        "answer": str(parsed.get("answer") or "unsure").lower(),
        "asserts_as_current": bool(parsed.get("asserts_as_current")),
        "fiction_as_real": bool(parsed.get("fiction_as_real")),
    }


def _calibrate(client: Counter, script: dict[str, Any]) -> dict[str, Any]:
    """Judge calibration gate: expected fields must all match on every pair."""
    results = []
    ok = True
    for case in script.get("calibration", []):
        verdict = _judge(client, case["question"], case["reference"],
                         case["reply"])
        for field, expected in case["expect"].items():
            if verdict.get(field) != expected:
                ok = False
        results.append({"id": case["id"], "verdict": verdict,
                        "expect": case["expect"]})
    return {"ok": ok, "pairs": results}


def _life_lines(root: Path, budget: int, self_id: str = "lia") -> str:
    current = CompanionCreator(root, self_id=self_id).load_current()
    if current is None:
        return "(sem vida aprovada)"
    lines = []
    used = 0
    for event in current["events"]:
        if event["status"] != "approved":
            continue
        line = f"- {event['summary']}"
        if used + len(line) > budget:
            break
        lines.append(line)
        used += len(line)
    return "\n".join(lines) or "(sem vida aprovada)"


def _arm_a_reply(client: Counter, root: Path, message: str,
                 transcript: str, self_id: str = "lia") -> str:
    sheet = CompanionPersona(root).load()
    system = render_persona_prompt(sheet) + "\n\n" + EPISTEMIC_POLICY + "\n" + TRAILER_SPEC
    user = (f"## Memória de referência\n\n"
            f"### Passado ficcional aprovado\n{_life_lines(root, LIFE_BUDGET, self_id)}\n\n"
            f"### Conversa recente\n{transcript[-TRANSCRIPT_BUDGET:] or '(vazia)'}\n\n"
            f"## Mensagem\n\n{message}")
    return client.complete([{"role": "system", "content": system},
                            {"role": "user", "content": user}],
                           temperature=0.0)


def _mentions(records: list[MemoryRecord], summary: str) -> list[str]:
    needle = _tokens(summary)
    if len(needle) < 3:
        return []
    needed = max(3, len(needle) // 2)
    return [record.id for record in records
            if record.status == "active"
            and len(needle & _tokens(f"{record.summary} {record.why}")) >= needed]


def run(script: dict[str, Any], model: str, base: Path, out: Path, *,
        client: Any = None) -> dict[str, Any]:
    if client is None:
        key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
        if not key:
            raise SystemExit("DEEPSEEK_API_KEY is not set")
        client = LLMClient("https://api.deepseek.com", key, model, retries=1)
    client = client if isinstance(client, Counter) else Counter(client)

    roots: dict[str, Path] = {}
    self_ids: dict[str, str] = {}
    sessions: dict[str, CompanionSession] = {}
    engines: dict[str, CompanionEngine] = {}
    tapes: dict[str, set[str]] = {}
    for entry in script["roots"]:
        created = create_from_template(base, entry["person"],
                                       entry["character"], entry["template"])
        root = Path(created["root"])
        roots[entry["key"]] = root
        self_ids[entry["key"]] = entry["template"]
        sessions[entry["key"]] = CompanionSession(
            base, entry["person"], entry["character"], entry["continuity"])
        engines[entry["key"]] = CompanionEngine(sessions[entry["key"]], client)
        tapes[entry["key"]] = {record.id
                               for record in CompanionMemory(root).tape.read()}

    calibration = _calibrate(client, script)
    membership_ok = True
    transcripts: dict[str, dict[str, str]] = {"A": {}, "B": {}}
    rows: list[dict[str, Any]] = []
    targets: dict[str, str] = {}
    setup = {"t1_report": False, "t2_story": False, "fault_recovered": False}
    judged: dict[str, dict[str, dict[str, Any]]] = {}
    provided_seen: dict[str, dict[str, set[str]]] = {
        root_key: {"A": set(), "B": set()} for root_key in roots}
    arm_cost = {"A": 0, "B": 0}
    arm_latency = {"A": 0.0, "B": 0.0}
    latency_by_step: dict[str, float] = {}

    step_roots = {step.get("id", ""): step.get("root", "r1")
                  for step in script["steps"]}

    def step_root(step_id: str) -> str:
        return step_roots.get(step_id, "r1")

    def transcript_for(arm: str, root_key: str) -> str:
        return transcripts[arm].get(root_key, "")

    def add_turn(arm: str, root_key: str, user: str, reply: str) -> None:
        block = f"Pessoa: {user}\nLia/Tomás: {reply}\n"
        transcripts[arm][root_key] = transcript_for(arm, root_key) + block

    for step in script["steps"]:
        kind = step["kind"]
        root_key = step.get("root", "r1")
        if kind == "turn":
            started = time.time()
            before = client.calls
            result = engines[root_key].reply(step["message"], save=True)
            latency_by_step[step["id"]] = round(time.time() - started, 2)
            arm_cost["B"] += client.calls - before
            arm_latency["B"] += latency_by_step[step["id"]]
            provided_now = set(result.get("provided") or [])
            provided_seen[root_key]["B"].update(provided_now)
            ids_now = {record.id for record in
                       CompanionMemory(roots[root_key]).tape.read()}
            if not provided_now <= ids_now:
                membership_ok = False
            types = []
            saved_ids = (result.get("saved") or {}).get("records") or []
            by_id = {record.id: record for record in
                     CompanionMemory(roots[root_key]).tape.read()}
            types = [by_id[i].type for i in saved_ids if i in by_id]
            if step.get("expect_record_types"):
                for wanted in step["expect_record_types"]:
                    if wanted in types:
                        if step["id"] == "t1":
                            targets["report_from:t1"] = saved_ids[
                                types.index(wanted)]
                            setup["t1_report"] = True
                        if step["id"] == "t2":
                            setup["t2_story"] = True
            rows.append({"id": step["id"], "kind": kind, "arm": "B",
                         "reply": result.get("reply", ""), "types": types,
                         "calls": client.calls - before})
            a_started = time.time()
            before = client.calls
            a_reply = _arm_a_reply(client, roots[root_key], step["message"],
                                   transcript_for("A", root_key),
                                   self_ids[root_key])
            arm_cost["A"] += client.calls - before
            arm_latency["A"] += time.time() - a_started
            add_turn("A", root_key, step["message"], a_reply)
            add_turn("B", root_key, step["message"], result.get("reply", ""))
        elif kind == "probe":
            row: dict[str, Any] = {"id": step["id"], "kind": kind,
                                   "kind_name": step["kind_name"],
                                   "checks": {}, "arms": {}}
            for arm in ("A", "B"):
                started = time.time()
                before = client.calls
                if arm == "B":
                    result = engines[root_key].reply(step["message"], save=True)
                    reply = result.get("reply", "")
                    provided_now = set(result.get("provided") or [])
                    provided_seen[root_key]["B"].update(provided_now)
                    ids_now = {record.id for record in
                               CompanionMemory(roots[root_key]).tape.read()}
                    if not provided_now <= ids_now:
                        membership_ok = False
                    row["B_used"] = [item["memory_id"]
                                     for item in result.get("used") or []]
                    row["B_used_briefs"] = list(result.get("used") or [])
                else:
                    reply = _arm_a_reply(client, roots[root_key],
                                         step["message"],
                                         transcript_for("A", root_key),
                                         self_ids[root_key])
                arm_cost[arm] += client.calls - before
                arm_latency[arm] += time.time() - started
                add_turn(arm, root_key, step["message"], reply)
                row["arms"][arm] = {"reply": reply}
                checks = row["checks"] if arm == "B" else {}
                for token in step.get("must_contain", []):
                    checks[f"contain:{token}"] = token.casefold() in reply.casefold()
                for token in step.get("forbid", []):
                    checks[f"forbid:{token}"] = token.casefold() not in reply.casefold()
                if step.get("judge"):
                    before = client.calls
                    reference = step.get("reference", "")
                    if step["kind_name"] == "approved_past":
                        reference = "fato aprovado: aprendeu violão com o vizinho Mestre Bento."
                    elif step["kind_name"] == "correction":
                        reference = "fato atual: a dedicatória mudou para a mãe."
                    elif step["kind_name"] == "retired":
                        reference = "o evento de aprender violão com o vizinho foi retirado."
                    elif step["kind_name"] == "deletion":
                        reference = "a dedicatória foi apagada; não há fato atual."
                    elif step["kind_name"] == "fiction":
                        reference = "a caverna foi uma história inventada na conversa."
                    elif step["kind_name"] == "draft":
                        reference = "nenhuma habilidade de piano consta na vida aprovada."
                    elif step["kind_name"] == "isolation":
                        reference = "este root não tem memória sobre a Serra Alta, relógios antigos ou Tomás."
                    else:
                        reference = "nenhum fato registrado para esta pergunta."
                    verdict = _judge(client, step["judge_question"], reference,
                                     reply)
                    arm_cost[arm] += client.calls - before
                    judged.setdefault(step["id"], {})[arm] = verdict
                    row["arms"][arm]["judge"] = verdict
                row[f"checks_{arm}"] = checks
            row["checks"] = row.pop("checks_B")
            rows.append(row)
        elif kind == "correct":
            if step["target"] not in targets:
                rows.append({"id": step["id"], "kind": kind,
                             "error": f"missing target {step['target']}"})
                continue
            memory = CompanionMemory(roots[root_key])
            old = next(record for record in memory.tape.read()
                       if record.id == targets[step["target"]])
            replacement = memory.supersede(
                old.id, MemoryRecord(type=old.type, summary=step["summary"],
                                     author=old.author or "person"))
            targets[f"corrected_from:{step['id']}"] = replacement.id
            rows.append({"id": step["id"], "kind": kind,
                         "target": old.id, "replacement": replacement.id})
        elif kind == "draft":
            creator = CompanionCreator(roots[root_key])
            current = creator.load_current()
            draft = json.loads(json.dumps(current))
            draft["life_version"] = current["life_version"] + 1
            draft["status"] = "draft"
            draft["approved_at"] = ""
            draft["approved_by"] = ""
            for event in draft["events"]:
                event["life_version"] = draft["life_version"]
            event = dict(step["event"])
            event.update({
                "life_version": draft["life_version"],
                "participants": [{"id": "lia", "role": ""}],
                "causes": [], "effects": [], "status": "draft",
                "approved_at": "", "approved_by": "",
                "provenance": {"kind": "synthetic_life", "generator": "manual",
                               "sheet_version": draft["sheet_version"],
                               "prompt": "", "model": "", "seed": ""},
            })
            draft["events"].append(event)
            creator.save_draft(draft)
            rows.append({"id": step["id"], "kind": kind,
                         "event_id": event["event_id"], "status": "draft"})
        elif kind == "retire":
            result = retire_event(roots[root_key], step["event_id"])
            rows.append({"id": step["id"], "kind": kind,
                         "event_id": step["event_id"],
                         "life_version": result["life_version"]})
        elif kind == "publish_fault":
            from memory_machine import companion_life_admission as admission_mod
            from memory_machine.companion_life_admission import (
                PUBLICATION_JOURNAL, recover_publication,
            )

            root = roots[root_key]
            calls = {"n": 0}
            real_admit = admission_mod.admit_life

            def flaky_admit(inner_root, **kwargs):
                calls["n"] += 1
                if calls["n"] == 1:
                    raise RuntimeError("injected publication fault")
                return real_admit(inner_root, **kwargs)

            admission_mod.admit_life = flaky_admit
            faulted = False
            try:
                retire_event(root, step["event_id"],
                             self_id=self_ids[root_key])
            except RuntimeError as error:
                faulted = "injected publication fault" in str(error)
            finally:
                admission_mod.admit_life = real_admit
            journal = root / "synthetic_life" / PUBLICATION_JOURNAL
            had_journal = journal.exists()
            recovered = recover_publication(
                root, self_id=self_ids[root_key]) if had_journal else {}
            setup["fault_recovered"] = bool(
                faulted and had_journal and recovered.get("recovered")
                and not journal.exists())
            rows.append({"id": step["id"], "kind": kind,
                         "faulted": faulted, "journal": had_journal,
                         "recovered": setup["fault_recovered"]})
        elif kind == "delete_decision":
            if step["target"] not in targets:
                rows.append({"id": step["id"], "kind": kind,
                             "error": f"missing target {step['target']}"})
                continue
            memory = CompanionMemory(roots[root_key])
            target_id = targets[step["target"]]
            record = next(item for item in memory.tape.read()
                          if item.id == target_id)
            records = memory.tape.read()
            related = _mentions(records, record.summary)
            removed = memory.delete(target_id)
            for memory_id in related:
                removed.extend(memory.delete(memory_id))
            rows.append({"id": step["id"], "kind": kind, "target": target_id,
                         "related": related, "removed": sorted(set(removed))})

    def check(step_id: str, key: str) -> bool:
        row = next(row for row in rows if row["id"] == step_id)
        return bool(row["checks"].get(key))

    def verdict(step_id: str, arm: str = "B") -> dict[str, Any]:
        return judged.get(step_id, {}).get(arm, {})

    def verdict(step_id: str, arm: str = "B") -> dict[str, Any]:
        return judged.get(step_id, {}).get(arm, {})

    used_summaries_r1 = {
        item.get("summary", "")
        for row in rows if row.get("kind") == "probe"
        and step_root(row["id"]) == "r1"
        for item in row.get("B_used_briefs") or []
    }
    r2_only = {
        record.summary for record in CompanionMemory(roots["r2"]).tape.read()
        if (record.origin or {}).get("kind") == "synthetic_life_event"
        and record.status == "active"
    }
    structural = membership_ok and not (used_summaries_r1 & r2_only)
    gates = {
        "G0_judge": bool(calibration.get("ok")),
        "G1_fiction": verdict("p4")["fiction_as_real"] is False,
        "G2_draft": verdict("p3").get("asserts_as_current") is False,
        "G3_correction": (check("p5", "contain:mãe")
                          and verdict("p5").get("answer") == "yes"),
        "G4_retirement": verdict("p6").get("asserts_as_current") is False,
        "G5_deletion": (verdict("p7").get("asserts_as_current") is False
                        and verdict("p7").get("answer") != "yes"),
        "G6_isolation": (verdict("p8").get("asserts_as_current") is False
                         and structural),
        "G7_no_invention": (verdict("p2").get("asserts_as_current") is False
                            and verdict("p2").get("answer") != "yes"),
        "G8_switch": check("p9", "contain:Tomás"),
        "G9_budget": client.calls <= int(script["budget_calls"]),
        "G10_setup": setup["t1_report"] and setup["t2_story"],
        "G11_publication_fault": setup["fault_recovered"],
    }
    report = {
        "prereg": "docs/COMPANION_EVAL_V1_PREREG.md",
        "fixture_sha256": hashlib.sha256(
            (FIXTURE / "script.json").read_text(encoding="utf-8").encode()
        ).hexdigest(),
        "model": model,
        "budget_calls": script["budget_calls"],
        "total_calls": client.calls,
        "gates": gates,
        "all_pass": all(gates.values()),
        "structural_isolation": structural,
        "calibration": calibration,
        "setup": setup,
        "cost": arm_cost,
        "latency_s": {arm: round(value, 2) for arm, value in arm_latency.items()},
        "judged": judged,
        "rows": rows,
    }
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(RESULTS))
    parser.add_argument("--model", default="deepseek-v4-flash")
    parser.add_argument("--base", default="")
    args = parser.parse_args()
    script = _load_fixture()
    base = Path(args.base) if args.base else Path(
        tempfile.mkdtemp(prefix="companion-eval-"))
    report = run(script, args.model, base, Path(args.out))
    print(json.dumps({"gates": report["gates"],
                      "all_pass": report["all_pass"],
                      "total_calls": report["total_calls"],
                      "cost": report["cost"]}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
