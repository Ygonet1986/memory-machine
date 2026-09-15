#!/usr/bin/env python3
"""E1 — composition ceiling test (three arms, one batch, frozen rules).

Frozen by docs/COMPOSITION_V1.md §5 and the E1 authorization (commit ece739f):

  arms        complete | precise | cards, same batch, same model/judge/params
  complete    full text of the required memories (I4-style, no budget)
  precise     the frozen control context from the fixture (sha1 asserted)
  cards       rendered evidence cards over the required memories (budget 4000,
              card rules v1 exactly as committed in eval/evidence_cards.py)
  metrics     reported separately: deterministic atom coverage and strict
              accuracy (no secondary metric may bypass the kill gate)
  kill gate   literal: close Phase E without E2 iff cards ≤ precise on BOTH the
              atom-retention dimension AND the paired answer dimension
  audit       case 26 / M0042 reported explicitly, never repaired here

Nothing is changed after results: card rules, prompts, model, judge, N and
criteria are pinned by the committed doc and this harness. Raw answers, raw
judge reasons, contexts, checksums and the per-case audit are preserved under
``--out`` (resume-safe: finished (case, arm, replicate) rows are skipped).

Dry-run (no LLM — builds contexts, atom audit and checksums):

    PYTHONPATH=src python3 eval/composition_e1.py --dry-run

Live run (needs DEEPSEEK_API_KEY, env or gitignored .env):

    PYTHONPATH=src python3 eval/composition_e1.py \
        --out eval/results/composition_u4_e1
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
from collections import Counter
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "src"))

from evidence_cards import (  # noqa: E402
    build_cards,
    canonical_source,
    render_cards,
)
from fact_presence import (  # noqa: E402
    COMPOSITION_RE,
    atom_present,
    item_fact_atoms,
    item_span,
    norm,
    relevant_atoms,
)

ARMS = ("complete", "precise", "cards")
FIXTURE = HERE / "fixtures" / "composition_u4"
N_SWEEP = 3
N_FLIP = 5
MODEL = "deepseek-v4-flash"
JUDGE_MODEL = "deepseek-v4-flash"
MODEL_BASE = "https://api.deepseek.com"

CARD_LINE_RE = re.compile(r"^\[(M\d+) \| (why|summary) (\d+):(\d+)\] (.*)$")


def sha1(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def load_dotenv_key() -> str:
    env = os.environ.get("DEEPSEEK_API_KEY", "")
    if env:
        return env
    dotenv = HERE.parent / ".env"
    if dotenv.exists():
        for line in dotenv.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("DEEPSEEK_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def load_fixture(fixtures: Path) -> tuple[list[dict[str, Any]], dict[tuple[int, str], dict[str, Any]]]:
    cases = [
        json.loads(line)
        for line in (fixtures / "cases.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    records = {
        (int(row["case"]), row["id"]): row
        for row in (
            json.loads(line)
            for line in (fixtures / "records.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    }
    return cases, records


def full_text(record: dict[str, Any]) -> str:
    return f"[{record['id']}] {record['summary']}\n{record['why']}"


def build_contexts(case: dict[str, Any], records: dict[tuple[int, str], dict[str, Any]]) -> dict[str, str]:
    case_id = int(case["case"])
    required = list(case["required_ids"])
    sources = []
    for memory_id in required:
        record = records[(case_id, memory_id)]
        field, text = canonical_source(record)
        sources.append((memory_id, field, text))
    complete = "\n\n".join(
        full_text(records[(case_id, memory_id)]) for memory_id in required
    )
    precise = case["context"]
    cards = render_cards(build_cards(case["question"], sources))
    return {"complete": complete, "precise": precise, "cards": cards}


def card_span(context: str, memory_id: str) -> tuple[str, bool]:
    """Delivered span of a memory in the cards context (line-based format)."""
    parts = []
    for line in context.splitlines():
        match = CARD_LINE_RE.match(line)
        if match and match.group(1) == memory_id:
            parts.append(match.group(5))
    if not parts:
        return "", False
    return " ".join(parts), True


def cards_integrity(
    context: str, records: dict[tuple[int, str], dict[str, Any]], case_id: int
) -> list[str]:
    """Re-validate every card line against the source text (guard 2 at E1)."""
    failures: list[str] = []
    for line in context.splitlines():
        match = CARD_LINE_RE.match(line)
        if match is None:
            continue
        memory_id, field, start, end = (
            match.group(1), match.group(2), int(match.group(3)), int(match.group(4))
        )
        record = records[(case_id, memory_id)]
        source = str(record.get(field) or "")
        text = match.group(5)
        if not (0 <= start < end <= len(source)) or source[start:end] != text:
            failures.append(f"{memory_id} {field} {start}:{end}")
    return failures


def atom_audit(
    case: dict[str, Any],
    records: dict[tuple[int, str], dict[str, Any]],
    contexts: dict[str, str],
) -> dict[str, Any]:
    case_id = int(case["case"])
    reference = str(case["gold"] or "")
    entry: dict[str, Any] = {
        "case": case_id,
        "block": case["block"],
        "cat": case["cat"],
        "question_class": (
            "composition" if COMPOSITION_RE.search(case["question"]) else "other"
        ),
        "arms": {},
    }
    for arm, context in contexts.items():
        items: dict[str, Any] = {}
        for memory_id in case["required_ids"]:
            record = records[(case_id, memory_id)]
            _field, memory_text = canonical_source(record)
            if arm == "cards":
                span, delivered = card_span(context, memory_id)
            else:
                span, delivered = item_span(context, memory_id)
            span_norm = norm(span)
            item_atoms = relevant_atoms(memory_text, case["question"], reference)
            all_atoms = item_fact_atoms(memory_text)
            items[memory_id] = {
                "delivered": delivered,
                "item_total": len(item_atoms),
                "item_present": sum(atom_present(a, span_norm) for a in item_atoms),
                "all_total": len(all_atoms),
                "all_present": sum(atom_present(a, span_norm) for a in all_atoms),
            }
        all_items = bool(items) and all(
            flag["item_total"] == flag["item_present"] for flag in items.values()
        )
        entry["arms"][arm] = {
            "chars": len(context),
            "sha1": sha1(context),
            "all_item_facts_present": all_items,
            "items": items,
        }
    entry["cards_integrity_failures"] = cards_integrity(contexts["cards"], records, case_id)
    return entry


def aggregate_atoms(audits: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for arm in ARMS:
        total = present = all_present = 0
        for entry in audits:
            data = entry["arms"][arm]
            for flag in data["items"].values():
                total += flag["item_total"]
                present += flag["item_present"]
            all_present += int(data["all_item_facts_present"])
        out[arm] = {
            "item_facts_present": present,
            "item_facts_total": total,
            "item_rate": round(present / total, 4) if total else 0.0,
            "all_present_cases": all_present,
            "cases": len(audits),
        }
    return out


# ---------------------------------------------------------------------------
# LLM sweep


def run_sweep(
    cases: list[dict[str, Any]],
    records: dict[tuple[int, str], dict[str, Any]],
    out: Path,
    api_key: str,
    *,
    model: str = MODEL,
    judge_model: str = JUDGE_MODEL,
    timeout: int = 300,
) -> None:
    from memory_machine.coordinator import Machine  # noqa: E402
    from memory_machine.llm import LLMClient  # noqa: E402

    from e2e_bench import answer_with, judge  # noqa: E402
    from external_bench import DATA, load_longmemeval  # noqa: E402
    from graph_replay_shared import variant_config  # noqa: E402
    from view_router_bench import CountingClient  # noqa: E402

    agent_client = CountingClient(
        LLMClient(MODEL_BASE, api_key, model, timeout=timeout, retries=1, backoff=0.5)
    )
    judge_client = CountingClient(
        LLMClient(MODEL_BASE, api_key, judge_model, timeout=timeout, retries=1, backoff=0.5)
    )
    tasks = {
        t["question"]: t
        for t in load_longmemeval(DATA / "longmemeval_s_cleaned.json", 0, 7)
    }
    cfg = variant_config("graph_augment_precise")
    answers_path = out / "answers.jsonl"
    contexts_path = out / "contexts.jsonl"
    done: set[tuple[int, str, int]] = set()
    if answers_path.exists():
        for line in answers_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                done.add((int(row["case"]), row["arm"], int(row["replicate"])))
        print(f"resuming: {len(done)} (case, arm, replicate) rows already recorded")

    work_root = Path(tempfile.mkdtemp(prefix="mm-e1-"))
    contexts_seen: set[int] = set()
    if contexts_path.exists():
        for line in contexts_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                contexts_seen.add(int(json.loads(line)["case"]))
    with contexts_path.open("a", encoding="utf-8") as handle:
        for case in cases:
            case_id = int(case["case"])
            if case_id in contexts_seen:
                continue
            contexts = build_contexts(case, records)
            handle.write(json.dumps(
                {"case": case_id, "contexts": contexts,
                 "sha1": {arm: sha1(text) for arm, text in contexts.items()}},
                ensure_ascii=False) + "\n")

    for case in cases:
        case_id = int(case["case"])
        question = case["question"]
        question_date = tasks.get(question, {}).get("question_date", "")
        provenance = f"\n\n(Question asked on {question_date}.)" if question_date else ""
        contexts = build_contexts(case, records)
        for arm in ARMS:
            context = contexts[arm]
            machine = Machine(
                work_root / f"case_{case_id:02d}_{arm}", config=cfg, client=None
            )
            machine.whiteboard.annotations = []
            machine.whiteboard.subject = question
            replicates = sorted(r for (c, a, r) in done if c == case_id and a == arm)
            needed = [r for r in range(1, N_SWEEP + 1) if r not in replicates]
            for replicate in needed:
                answer = ""
                verdict = ""
                reason = ""
                for attempt in range(5):
                    try:
                        answer = answer_with(
                            agent_client, machine, question + provenance,
                            extra_context=context,
                        )
                        verdict, reason = judge(
                            judge_client, question, str(case["gold"] or ""), answer
                        )
                        break
                    except Exception as exc:  # transient API/response failures
                        if attempt == 4:
                            raise
                        print(f"  retry case {case_id} {arm} rep {replicate}: "
                              f"{type(exc).__name__}: {exc}", flush=True)
                        time.sleep(3 + 3 * attempt)
                row = {
                    "case": case_id,
                    "block": case["block"],
                    "arm": arm,
                    "replicate": replicate,
                    "question": question,
                    "answer": answer,
                    "verdict": verdict,
                    "reason": reason,
                    "context_sha1": sha1(context),
                    "context_chars": len(context),
                }
                with answers_path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(row, ensure_ascii=False) + "\n")
                print(f"case {case_id:>3} {arm:<8} rep {replicate} verdict={verdict}",
                      flush=True)
    print(f"work root: {work_root}")


def extra_flip_replicates(
    cases: list[dict[str, Any]],
    records: dict[tuple[int, str], dict[str, Any]],
    out: Path,
    api_key: str,
    *,
    timeout: int = 300,
) -> list[int]:
    """Run N_FLIP total replicates on cases that flip precise↔cards (registered)."""
    from memory_machine.coordinator import Machine  # noqa: E402
    from memory_machine.llm import LLMClient  # noqa: E402

    from e2e_bench import answer_with, judge  # noqa: E402
    from external_bench import DATA, load_longmemeval  # noqa: E402
    from graph_replay_shared import variant_config  # noqa: E402
    from view_router_bench import CountingClient  # noqa: E402

    answers_path = out / "answers.jsonl"
    rows = [
        json.loads(line)
        for line in answers_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    modal: dict[tuple[int, str], str] = {}
    for arm in ("precise", "cards"):
        for case in cases:
            case_id = int(case["case"])
            verdicts = [
                row["verdict"] for row in rows
                if int(row["case"]) == case_id and row["arm"] == arm
            ]
            modal[(case_id, arm)] = (
                Counter(verdicts).most_common(1)[0][0] if verdicts else ""
            )
    flips = [
        int(case["case"]) for case in cases
        if modal[(int(case["case"]), "precise")] != modal[(int(case["case"]), "cards")]
    ]
    print(f"flip cases (precise vs cards): {flips}", flush=True)
    if not flips:
        return []

    agent_client = CountingClient(
        LLMClient(MODEL_BASE, api_key, MODEL, timeout=timeout, retries=1, backoff=0.5)
    )
    judge_client = CountingClient(
        LLMClient(MODEL_BASE, api_key, JUDGE_MODEL, timeout=timeout, retries=1, backoff=0.5)
    )
    tasks = {
        t["question"]: t
        for t in load_longmemeval(DATA / "longmemeval_s_cleaned.json", 0, 7)
    }
    cfg = variant_config("graph_augment_precise")
    work_root = Path(tempfile.mkdtemp(prefix="mm-e1-flip-"))
    for case in cases:
        case_id = int(case["case"])
        if case_id not in flips:
            continue
        question = case["question"]
        question_date = tasks.get(question, {}).get("question_date", "")
        provenance = f"\n\n(Question asked on {question_date}.)" if question_date else ""
        contexts = build_contexts(case, records)
        for arm in ("precise", "cards"):
            have = [
                int(row["replicate"]) for row in rows
                if int(row["case"]) == case_id and row["arm"] == arm
            ]
            context = contexts[arm]
            machine = Machine(
                work_root / f"case_{case_id:02d}_{arm}", config=cfg, client=None
            )
            machine.whiteboard.annotations = []
            machine.whiteboard.subject = question
            for replicate in range(max(have) + 1, N_FLIP + 1):
                answer = ""
                verdict = ""
                reason = ""
                for attempt in range(5):
                    try:
                        answer = answer_with(
                            agent_client, machine, question + provenance,
                            extra_context=context,
                        )
                        verdict, reason = judge(
                            judge_client, question, str(case["gold"] or ""), answer
                        )
                        break
                    except Exception as exc:
                        if attempt == 4:
                            raise
                        print(f"  retry flip case {case_id} {arm} rep {replicate}: "
                              f"{type(exc).__name__}: {exc}", flush=True)
                        time.sleep(3 + 3 * attempt)
                with answers_path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps({
                        "case": case_id,
                        "block": case["block"],
                        "arm": arm,
                        "replicate": replicate,
                        "question": question,
                        "answer": answer,
                        "verdict": verdict,
                        "reason": reason,
                        "context_sha1": sha1(context),
                        "context_chars": len(context),
                        "extra_flip": True,
                    }, ensure_ascii=False) + "\n")
                print(f"flip case {case_id:>3} {arm:<8} rep {replicate} verdict={verdict}",
                      flush=True)
    return flips


# ---------------------------------------------------------------------------
# Gate and reporting


def modal_verdicts(out: Path) -> dict[tuple[int, str], str]:
    rows = [
        json.loads(line)
        for line in (out / "answers.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    out_modal: dict[tuple[int, str], str] = {}
    for row in rows:
        key = (int(row["case"]), row["arm"])
        out_modal.setdefault(key, "")
        verdicts = [
            r["verdict"] for r in rows
            if int(r["case"]) == key[0] and r["arm"] == key[1]
        ]
        out_modal[key] = Counter(verdicts).most_common(1)[0][0] if verdicts else ""
    return out_modal


def paired_ledger(
    cases: list[dict[str, Any]], modal: dict[tuple[int, str], str]
) -> list[dict[str, Any]]:
    ledger = []
    for case in cases:
        case_id = int(case["case"])
        precise = modal.get((case_id, "precise"), "")
        cards = modal.get((case_id, "cards"), "")
        p_ok = precise == "correct"
        c_ok = cards == "correct"
        if p_ok and c_ok:
            cls = "stayed_correct"
        elif p_ok and not c_ok:
            cls = "regressed"
        elif not p_ok and c_ok:
            cls = "repaired"
        else:
            cls = "stayed_incorrect"
        ledger.append({
            "case": case_id,
            "block": case["block"],
            "question_class": (
                "composition" if COMPOSITION_RE.search(case["question"]) else "other"
            ),
            "precise": precise,
            "cards": cards,
            "class": cls,
            "net": {"repaired": 1, "regressed": -1}.get(cls, 0),
        })
    return ledger


def write_report(
    out: Path,
    cases: list[dict[str, Any]],
    audits: list[dict[str, Any]],
    manifest: dict[str, Any],
) -> dict[str, Any]:
    atoms = aggregate_atoms(audits)
    modal = modal_verdicts(out)
    ledger = paired_ledger(cases, modal)
    counts = Counter(row["class"] for row in ledger)
    net = sum(row["net"] for row in ledger)
    atom_compare = {
        "cards_rate": atoms["cards"]["item_rate"],
        "precise_rate": atoms["precise"]["item_rate"],
        "cards_all_present": atoms["cards"]["all_present_cases"],
        "precise_all_present": atoms["precise"]["all_present_cases"],
    }
    beat_atoms = (
        atoms["cards"]["item_rate"] >= atoms["precise"]["item_rate"]
        and atoms["cards"]["all_present_cases"] >= atoms["precise"]["all_present_cases"]
        and (
            atoms["cards"]["item_rate"] > atoms["precise"]["item_rate"]
            or atoms["cards"]["all_present_cases"] > atoms["precise"]["all_present_cases"]
        )
    )
    lose_atoms = (
        atoms["cards"]["item_rate"] <= atoms["precise"]["item_rate"]
        and atoms["cards"]["all_present_cases"] <= atoms["precise"]["all_present_cases"]
    )
    beat_answers = net > 0
    kill = lose_atoms and not beat_answers

    result = {
        "fixture": manifest["fixture"],
        "fixture_sha1": manifest["fixture_sha1"],
        "arms": list(ARMS),
        "model": manifest["model"],
        "judge_model": manifest["judge_model"],
        "n_sweep": N_SWEEP,
        "n_flip": N_FLIP,
        "flip_cases": manifest.get("flip_cases", []),
        "atom_metrics": atoms,
        "atom_compare": {**atom_compare, "beat_atoms": beat_atoms, "lose_atoms": lose_atoms},
        "accuracy": {
            "counts": dict(counts),
            "net_cards_vs_precise": net,
            "ledger": ledger,
            "beat_answers": beat_answers,
        },
        "kill_gate": {
            "literal": "close E without E2 iff cards <= precise on atoms AND on answers",
            "lose_atoms": lose_atoms,
            "beat_answers": beat_answers,
            "kill": kill,
            "next": (
                "phase closed without E2" if kill
                else "present paired ledger before any E2 decision"
            ),
        },
        "audit_26_M0042": report_case_26(audits, cases),
    }
    (out / "e1_summary.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    lines = [
        "# E1 composition ceiling — summary (three arms, one batch)",
        "",
        f"- fixture: `{manifest['fixture']}` (sha1 `{manifest['fixture_sha1']}`)",
        f"- model `{manifest['model']}` · judge `{manifest['judge_model']}` · "
        f"N={N_SWEEP} (flips N={N_FLIP}: {manifest.get('flip_cases', [])})",
        "",
        "## Atom coverage (deterministic; separate from accuracy)",
        "",
        "| arm | item facts present | rate | all-present cases | chars range |",
        "|---|---|---|---|---|",
    ]
    for arm in ARMS:
        data = atoms[arm]
        chars = [entry["arms"][arm]["chars"] for entry in audits]
        lines.append(
            f"| {arm} | {data['item_facts_present']}/{data['item_facts_total']} | "
            f"{data['item_rate']:.3f} | {data['all_present_cases']}/{data['cases']} | "
            f"{min(chars)}–{max(chars)} |"
        )
    lines += [
        "",
        "## Strict accuracy (paired; modal of replicates)",
        "",
        f"- classes: {dict(counts)}",
        f"- net cards vs precise: **{net:+d}**",
        "",
        "## Kill gate (literal)",
        "",
        f"- cards ≤ precise on atoms: {lose_atoms}",
        f"- cards beat precise on answers: {beat_answers}",
        f"- **kill: {kill}** ({result['kill_gate']['next']})",
        "",
        "## Case 26 / M0042 audit (no repair in E1)",
        "",
    ]
    lines.append(json.dumps(result["audit_26_M0042"], ensure_ascii=False, indent=2))
    (out / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (out / "paired_ledger.jsonl").write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in ledger) + "\n",
        encoding="utf-8",
    )
    return result


def report_case_26(audits: list[dict[str, Any]], cases: list[dict[str, Any]]) -> dict[str, Any]:
    case = next(c for c in cases if int(c["case"]) == 26)
    entry = next(a for a in audits if a["case"] == 26)
    out: dict[str, Any] = {
        "required_ids": case["required_ids"],
        "payload_ids": case["payload_ids"],
        "m0042_in_required": "M0042" in case["required_ids"],
        "m0042_in_payload_candidates": "M0042" in case["payload_ids"],
        "m0042_note": (
            "E0 payloads-mode gap: M0042 is a control-arm payload candidate with "
            "no scoring segment (no question-token match, no hard fact), so it "
            "emits no card. It is NOT an E1 required memory, so the gap is not "
            "exercised by this ceiling test and is carried unchanged to E2; no "
            "repair is applied in E1."
        ),
        "arms": {},
    }
    for arm in ARMS:
        data = entry["arms"][arm]
        out["arms"][arm] = {
            "chars": data["chars"],
            "all_item_facts_present": data["all_item_facts_present"],
            "items": data["items"],
            "m0042_cards": (
                data["items"].get("M0042", {}).get("delivered")
                if "M0042" in data["items"] else None
            ),
        }
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", default=str(FIXTURE))
    parser.add_argument("--out", default="eval/results/composition_u4_e1")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--api-key", default="")
    parser.add_argument("--model", default=MODEL)
    parser.add_argument("--judge-model", default=JUDGE_MODEL)
    parser.add_argument("--timeout", type=int, default=300)
    args = parser.parse_args()

    fixtures = Path(args.fixture)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    cases, records = load_fixture(fixtures)
    manifest = json.loads((fixtures / "manifest.json").read_text(encoding="utf-8"))

    # deterministic contexts + audit (no LLM)
    audits = [atom_audit(case, records, build_contexts(case, records)) for case in cases]
    for entry in audits:
        for arm, data in entry["arms"].items():
            if arm == "precise":
                case = next(c for c in cases if int(c["case"]) == entry["case"])
                assert data["sha1"] == case["context_sha1"], (
                    f"case {entry['case']}: precise context differs from fixture"
                )
    with (out / "atoms.jsonl").open("w", encoding="utf-8") as handle:
        for entry in audits:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")

    run_manifest = {
        "harness": "eval/composition_e1.py",
        "git_commit": os.popen("git rev-parse HEAD 2>/dev/null").read().strip(),
        "fixture": str(fixtures),
        "fixture_sha1": manifest["sha1"],
        "card_rules": "evidence_cards v1 (docs/COMPOSITION_V1.md §3)",
        "arms": list(ARMS),
        "model": args.model,
        "judge_model": args.judge_model,
        "n_sweep": N_SWEEP,
        "n_flip": N_FLIP,
        "checksums": {
            "atoms.jsonl": hashlib.sha1((out / "atoms.jsonl").read_bytes()).hexdigest(),
            "cards_contexts": {
                entry["case"]: entry["arms"]["cards"]["sha1"] for entry in audits
            },
        },
    }
    (out / "run_manifest.json").write_text(
        json.dumps(run_manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    if args.dry_run:
        atoms = aggregate_atoms(audits)
        print(f"dry-run: {len(cases)} cases")
        for arm in ARMS:
            data = atoms[arm]
            chars = [entry["arms"][arm]["chars"] for entry in audits]
            print(f"  {arm:<8} item facts {data['item_facts_present']}/{data['item_facts_total']} "
                  f"({data['item_rate']:.3f}) | all-present {data['all_present_cases']}/{data['cases']} "
                  f"| chars {min(chars)}–{max(chars)}")
        print("  atoms.jsonl sha1:", run_manifest["checksums"]["atoms.jsonl"])
        return 0

    api_key = args.api_key or load_dotenv_key()
    if not api_key:
        raise SystemExit(
            "set DEEPSEEK_API_KEY (env or gitignored .env) or pass --api-key"
        )
    run_sweep(cases, records, out, api_key,
              model=args.model, judge_model=args.judge_model, timeout=args.timeout)
    flips = extra_flip_replicates(cases, records, out, api_key, timeout=args.timeout)
    run_manifest["flip_cases"] = flips
    (out / "run_manifest.json").write_text(
        json.dumps(run_manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    result = write_report(out, cases, audits, run_manifest)
    print(json.dumps(result["kill_gate"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
