#!/usr/bin/env python3
"""E2 — controlled M0042 repair ablation (cards v1 vs cards + no-score fallback).

Authorized 2026-09-16; frozen in docs/COMPOSITION_V1.md §11 before any call.
Hypothesis under test: the case-26 error stems from the representation/selection
of M0042 (a payload candidate with zero scoring segments), and a controlled
repair can improve the answer without degrading the rest.

Arms (both over the SAME candidate memories = frozen ``payload_ids``, order
preserved):
  cards_v1      evidence_cards v1 exactly as frozen in E0/E1 (must rebuild
                byte-identical to the E0 payloads-mode per-case sha1)
  cards_repair  v1 + the registered no-score fallback: for candidate memories
                that emit zero v1 cards, emit their first <=3 segments in
                source order (exact spans, first-fit by the remaining budget)

Everything else is identical to E1: questions, candidate order, budget 4000,
prompts, temperature, model, judge, single batch, N=5 per case-arm (E1 found
17/90 non-unanimous case-arms). Primary metric: strict modal; secondaries:
all-present, item rate, paired ledger. The E1 ledger is frozen at a0edc08 and
is not re-run or re-interpreted here.

Gate (frozen):
  1. case 26 improves in strict modal;
  2. global net strict > 0;
  3. no material drop in item rate or all-present;
  4. the improvement holds in the majority of the five runs (not only the
     modal by a minimal margin).

Dry-run (deterministic, no LLM):

    PYTHONPATH=src python3 eval/composition_e2.py --dry-run

Live run (DEEPSEEK_API_KEY via env/.env):

    PYTHONPATH=src python3 eval/composition_e2.py \
        --out eval/results/composition_u4_e2
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
from typing import Any, Sequence

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "src"))

from evidence_cards import (  # noqa: E402
    CARD_BUDGET,
    EvidenceAtom,
    build_cards,
    canonical_source,
    fact_kinds,
    render_cards,
    segments_with_spans,
    validate_card,
)
from fact_presence import (  # noqa: E402
    COMPOSITION_RE,
    atom_present,
    item_fact_atoms,
    item_span,
    norm,
    relevant_atoms,
)

ARMS = ("cards_v1", "cards_repair")
FALLBACK_SEGMENTS = 3  # same cap as the frozen v1 policy
FIXTURE = HERE / "fixtures" / "composition_u4"
E0_REPORT = HERE / "results" / "composition_u4_e0" / "e0_report.json"
N_REPLICATES = 5
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


def sources_for(
    ids: Sequence[str], records: dict[tuple[int, str], dict[str, Any]], case: int
) -> list[tuple[str, str, str]]:
    out = []
    for memory_id in ids:
        field, text = canonical_source(records[(case, memory_id)])
        out.append((memory_id, field, text))
    return out


def build_cards_repair(
    question: str,
    sources: Sequence[tuple[str, str, str]],
    *,
    budget: int = CARD_BUDGET,
) -> list[EvidenceAtom]:
    """v1 cards plus the registered no-score fallback (exact spans only)."""
    cards = build_cards(question, sources)
    covered = {card.memory_id for card in cards}
    used = len(render_cards(cards))
    out = list(cards)
    for memory_id, field, text in sources:
        if memory_id in covered:
            continue
        added = 0
        for start, end, seg in segments_with_spans(text):
            if added >= FALLBACK_SEGMENTS:
                break
            atom = EvidenceAtom(
                memory_id=memory_id,
                field=field,
                start=start,
                end=end,
                text=seg,
                fact_kinds=tuple(sorted(fact_kinds(seg))),
                score=0.0,
            )
            add = len(atom.render()) + (1 if out else 0)
            if used + add > budget:
                continue
            out.append(atom)
            used += add
            added += 1
    return out


def build_contexts(
    case: dict[str, Any], records: dict[tuple[int, str], dict[str, Any]]
) -> dict[str, str]:
    case_id = int(case["case"])
    sources = sources_for(case["payload_ids"], records, case_id)
    return {
        "cards_v1": render_cards(build_cards(case["question"], sources)),
        "cards_repair": render_cards(build_cards_repair(case["question"], sources)),
    }


def card_span(context: str, memory_id: str) -> tuple[str, bool]:
    parts = [
        match.group(5)
        for line in context.splitlines()
        if (match := CARD_LINE_RE.match(line)) and match.group(1) == memory_id
    ]
    if not parts:
        return "", False
    return " ".join(parts), True


def integrity_failures(
    context: str, records: dict[tuple[int, str], dict[str, Any]], case_id: int
) -> list[str]:
    failures: list[str] = []
    for line in context.splitlines():
        match = CARD_LINE_RE.match(line)
        if match is None:
            continue
        memory_id, field, start, end = (
            match.group(1), match.group(2), int(match.group(3)), int(match.group(4))
        )
        source = str(records[(case_id, memory_id)].get(field) or "")
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
        "question_class": (
            "composition" if COMPOSITION_RE.search(case["question"]) else "other"
        ),
        "arms": {},
    }
    for arm, context in contexts.items():
        items: dict[str, Any] = {}
        for memory_id in case["required_ids"]:
            _field, memory_text = canonical_source(records[(case_id, memory_id)])
            span, delivered = card_span(context, memory_id)
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
        entry["arms"][arm] = {
            "chars": len(context),
            "sha1": sha1(context),
            "all_item_facts_present": bool(items)
            and all(f["item_total"] == f["item_present"] for f in items.values()),
            "items": items,
            "m0042_cards": "M0042" in case["payload_ids"]
            and card_span(context, "M0042")[1],
        }
    entry["integrity_failures"] = {
        arm: integrity_failures(context, records, case_id)
        for arm, context in contexts.items()
    }
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
        print(f"resuming: {len(done)} rows already recorded")

    if not contexts_path.exists():
        with contexts_path.open("w", encoding="utf-8") as handle:
            for case in cases:
                contexts = build_contexts(case, records)
                handle.write(json.dumps(
                    {"case": int(case["case"]), "contexts": contexts,
                     "sha1": {arm: sha1(text) for arm, text in contexts.items()}},
                    ensure_ascii=False) + "\n")

    work_root = Path(tempfile.mkdtemp(prefix="mm-e2-"))
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
            have = sorted(r for (c, a, r) in done if c == case_id and a == arm)
            needed = [r for r in range(1, N_REPLICATES + 1) if r not in have]
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
                    except Exception as exc:
                        if attempt == 4:
                            raise
                        print(f"  retry case {case_id} {arm} rep {replicate}: "
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
                    }, ensure_ascii=False) + "\n")
                print(f"case {case_id:>3} {arm:<12} rep {replicate} verdict={verdict}",
                      flush=True)
    print(f"work root: {work_root}")


def write_report(
    out: Path,
    cases: list[dict[str, Any]],
    audits: list[dict[str, Any]],
    manifest: dict[str, Any],
) -> dict[str, Any]:
    rows = [
        json.loads(line)
        for line in (out / "answers.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    verdicts: dict[tuple[int, str], list[str]] = {}
    for row in rows:
        verdicts.setdefault((int(row["case"]), row["arm"]), []).append(row["verdict"])
    modal = {key: Counter(v).most_common(1)[0][0] for key, v in verdicts.items()}
    atoms = aggregate_atoms(audits)

    ledger = []
    counts: Counter = Counter()
    net = 0
    for case in cases:
        case_id = int(case["case"])
        a = modal.get((case_id, "cards_v1"), "")
        b = modal.get((case_id, "cards_repair"), "")
        a_ok, b_ok = a == "correct", b == "correct"
        if a_ok and b_ok:
            cls = "stayed_correct"
        elif a_ok and not b_ok:
            cls = "regressed"
        elif not a_ok and b_ok:
            cls = "repaired"
        else:
            cls = "stayed_incorrect"
        counts[cls] += 1
        net += {"repaired": 1, "regressed": -1}.get(cls, 0)
        ledger.append({"case": case_id, "block": case["block"], "cards_v1": a,
                       "cards_repair": b, "class": cls,
                       "net": {"repaired": 1, "regressed": -1}.get(cls, 0)})

    c26_v1 = verdicts.get((26, "cards_v1"), [])
    c26_rep = verdicts.get((26, "cards_repair"), [])
    c26_v1_ok = sum(v == "correct" for v in c26_v1)
    c26_rep_ok = sum(v == "correct" for v in c26_rep)
    gate = {
        "1_case26_strict_modal_improves": (
            modal.get((26, "cards_repair")) == "correct"
            and modal.get((26, "cards_v1")) != "correct"
        ),
        "2_global_net_strict_gt_0": net > 0,
        "3_no_material_drop_atoms": (
            atoms["cards_repair"]["item_rate"] >= atoms["cards_v1"]["item_rate"]
            and atoms["cards_repair"]["all_present_cases"]
            >= atoms["cards_v1"]["all_present_cases"]
        ),
        "4_majority_of_runs": c26_rep_ok >= 3 and c26_rep_ok > c26_v1_ok,
        "case26_replicates": {"cards_v1": c26_v1, "cards_repair": c26_rep},
        "case26_correct_counts": {"cards_v1": c26_v1_ok, "cards_repair": c26_rep_ok},
    }
    gate["promote"] = all(gate[k] for k in (
        "1_case26_strict_modal_improves",
        "2_global_net_strict_gt_0",
        "3_no_material_drop_atoms",
        "4_majority_of_runs",
    ))
    gate["verdict"] = (
        "repair promoted" if gate["promote"]
        else "localized repair only (or none): not a general mechanism"
        if gate["1_case26_strict_modal_improves"] or gate["4_majority_of_runs"]
        else "M0042 hypothesis not supported; next target answerer/composition"
    )

    result = {
        "fixture": manifest["fixture"],
        "fixture_sha1": manifest["fixture_sha1"],
        "e1_ledger_frozen_at": "a0edc08",
        "arms": list(ARMS),
        "n": N_REPLICATES,
        "model": manifest["model"],
        "judge_model": manifest["judge_model"],
        "atom_metrics": atoms,
        "accuracy": {"counts": dict(counts), "net_cards_repair_vs_v1": net,
                     "ledger": ledger},
        "gate": gate,
        "case26_M0042": next(
            (e for e in audits if e["case"] == 26), {}
        ),
    }
    (out / "e2_summary.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    lines = [
        "# E2 — controlled M0042 repair (cards v1 vs cards + no-score fallback)",
        "",
        f"- fixture sha1 `{manifest['fixture_sha1']}` · E1 ledger frozen at `a0edc08`",
        f"- model `{manifest['model']}` · judge `{manifest['judge_model']}` · N={N_REPLICATES}",
        "",
        "## Atom coverage (required memories; deterministic)",
        "",
        "| arm | item facts present | rate | all-present cases |",
        "|---|---|---|---|",
    ]
    for arm in ARMS:
        data = atoms[arm]
        lines.append(
            f"| {arm} | {data['item_facts_present']}/{data['item_facts_total']} | "
            f"{data['item_rate']:.3f} | {data['all_present_cases']}/{data['cases']} |")
    lines += [
        "",
        "## Strict accuracy (modal of 5)",
        "",
        f"- classes: {dict(counts)}",
        f"- net cards_repair vs cards_v1: **{net:+d}**",
        f"- case 26 replicates: v1={c26_v1} repair={c26_rep}",
        "",
        "## Gate (frozen)",
        "",
        f"1. case 26 strict modal improves: {gate['1_case26_strict_modal_improves']}",
        f"2. global net strict > 0: {gate['2_global_net_strict_gt_0']} ({net:+d})",
        f"3. no material drop in item rate/all-present: {gate['3_no_material_drop_atoms']}",
        f"4. majority of the five runs: {gate['4_majority_of_runs']} "
        f"({c26_rep_ok}/5 vs {c26_v1_ok}/5)",
        "",
        f"**verdict: {gate['verdict']}**",
    ]
    (out / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (out / "paired_ledger.jsonl").write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in ledger) + "\n",
        encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", default=str(FIXTURE))
    parser.add_argument("--out", default="eval/results/composition_u4_e2")
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
    e0 = json.loads(E0_REPORT.read_text(encoding="utf-8"))

    audits = [atom_audit(case, records, build_contexts(case, records)) for case in cases]
    # v1 arm must rebuild byte-identical to the E0 payloads-mode shas
    v1_shas = {e["case"]: e["arms"]["cards_v1"]["sha1"] for e in audits}
    e0_shas = {int(k): v for k, v in e0["modes"]["payloads"]["per_case_sha1"].items()}
    identity = v1_shas == e0_shas
    diffs = [c for c in v1_shas if v1_shas[c] != e0_shas.get(c)]
    # repair changes only the zero-card memories: exactly case 26 M0042
    changed = [
        e["case"] for e in audits
        if e["arms"]["cards_v1"]["sha1"] != e["arms"]["cards_repair"]["sha1"]
    ]
    integrity = sum(len(f) for e in audits for f in e["integrity_failures"].values())

    run_manifest = {
        "harness": "eval/composition_e2.py",
        "git_commit": os.popen("git rev-parse HEAD 2>/dev/null").read().strip(),
        "fixture": str(fixtures),
        "fixture_sha1": manifest["sha1"],
        "e1_ledger_frozen_at": "a0edc08",
        "policy": {"fallback_segments": FALLBACK_SEGMENTS, "budget": CARD_BUDGET,
                   "arms": list(ARMS), "n": N_REPLICATES},
        "identity": {"v1_matches_e0_payloads": identity, "diffs": diffs,
                     "repair_changed_cases": changed, "integrity_failures": integrity},
        "model": args.model,
        "judge_model": args.judge_model,
        "checksums": {
            "atoms.jsonl": hashlib.sha1(
                json.dumps(audits, ensure_ascii=False, sort_keys=True).encode()
            ).hexdigest(),
        },
    }
    (out / "run_manifest.json").write_text(
        json.dumps(run_manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    with (out / "atoms.jsonl").open("w", encoding="utf-8") as handle:
        for entry in audits:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")

    if args.dry_run:
        atoms = aggregate_atoms(audits)
        print(f"dry-run: {len(cases)} cases | v1==E0 payloads: {identity} "
              f"| repair changed: {changed} | integrity failures: {integrity}")
        for arm in ARMS:
            data = atoms[arm]
            print(f"  {arm:<13} item facts {data['item_facts_present']}/{data['item_facts_total']} "
                  f"({data['item_rate']:.3f}) all-present {data['all_present_cases']}/{data['cases']}")
        return 0

    api_key = args.api_key or load_dotenv_key()
    if not api_key:
        raise SystemExit("set DEEPSEEK_API_KEY (env or .env) or pass --api-key")
    run_sweep(cases, records, out, api_key,
              model=args.model, judge_model=args.judge_model, timeout=args.timeout)
    result = write_report(out, cases, audits, run_manifest)
    print(json.dumps(result["gate"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
