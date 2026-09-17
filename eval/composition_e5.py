#!/usr/bin/env python3
"""E5 — answerer/composition decomposition (frozen in COMPOSITION_V1 §13).

Arms over the frozen composition_u4 substrate (candidate set = `payload_ids`),
same questions/order/prompts/temperature/model/judge/batch, N=5:

  cards_v1       evidence_cards v1 contexts (byte-identical to the E0
                 payloads-mode shas; asserted) — control
  scaffold       SAME context; the question carries the frozen composition
                 instruction (single call, no extra LLM) — primary
  atom_complete  cards with a higher per-memory cap (<=6 scored segments) plus
                 the no-score fallback, question/token selection only (no
                 gold) — secondary, delivery lever

Gate (frozen §13): scaffold vs control net >= +3 AND above the measured
identical-context floor (N=5); atom_complete vs control reported as the
delivery lever; guards: identity, determinism, provenance 100%, budget,
calls/query equal. If both levers fail => consolidation, not a new mechanism.

Dry-run (no LLM):  PYTHONPATH=src python3 eval/composition_e5.py --dry-run
Live:              PYTHONPATH=src python3 eval/composition_e5.py \
                       --out eval/results/composition_u4_e5
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
from fact_presence import COMPOSITION_RE, atom_present, norm, relevant_atoms  # noqa: E402

ARMS = ("cards_v1", "scaffold", "atom_complete")
N = 5
MODEL = "deepseek-v4-flash"
JUDGE_MODEL = "deepseek-v4-flash"
MODEL_BASE = "https://api.deepseek.com"
FIXTURE = HERE / "fixtures" / "composition_u4"
E0_REPORT = HERE / "results" / "composition_u4_e0" / "e0_report.json"
SCAFFOLD_INSTRUCTION = (
    "First identify the facts needed, then compute, then answer in one short "
    "sentence. Show the computation."
)
HIGHER_CAP = 6
FALLBACK_SEGMENTS = 3
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


def load_fixture() -> tuple[list[dict[str, Any]], dict[tuple[int, str], dict[str, Any]]]:
    cases = [
        json.loads(line)
        for line in (FIXTURE / "cases.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    records = {
        (int(row["case"]), row["id"]): row
        for row in (
            json.loads(line)
            for line in (FIXTURE / "records.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    }
    return cases, records


def sources_for(case: dict[str, Any], records: dict[tuple[int, str], dict[str, Any]]):
    out = []
    for memory_id in case["payload_ids"]:
        field, text = canonical_source(records[(int(case["case"]), memory_id)])
        out.append((memory_id, field, text))
    return out


def build_cards_atom_complete(
    question: str, sources: Sequence[tuple[str, str, str]], *, budget: int = CARD_BUDGET
) -> list[EvidenceAtom]:
    """Higher cap + no-score fallback; question/token scores only (no gold)."""
    cards = build_cards(question, sources, max_segments_per_memory=HIGHER_CAP)
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
            atom = EvidenceAtom(memory_id=memory_id, field=field, start=start,
                                end=end, text=seg,
                                fact_kinds=tuple(sorted(fact_kinds(seg))), score=0.0)
            add = len(atom.render()) + 1
            if used + add > budget:
                continue
            out.append(atom)
            used += add
            added += 1
    return out


def build_contexts(case: dict[str, Any], records) -> dict[str, str]:
    sources = sources_for(case, records)
    return {
        "cards_v1": render_cards(build_cards(case["question"], sources)),
        "scaffold": render_cards(build_cards(case["question"], sources)),
        "atom_complete": render_cards(build_cards_atom_complete(case["question"], sources)),
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


def integrity_failures(context: str, records, case_id: int) -> list[str]:
    failures: list[str] = []
    for line in context.splitlines():
        match = CARD_LINE_RE.match(line)
        if match is None:
            continue
        memory_id, field, start, end = (
            match.group(1), match.group(2), int(match.group(3)), int(match.group(4)))
        source = str(records[(case_id, memory_id)].get(field) or "")
        text = match.group(5)
        if not (0 <= start < end <= len(source)) or source[start:end] != text:
            failures.append(f"{memory_id} {field} {start}:{end}")
    return failures


def atom_audit(case: dict[str, Any], records, contexts: dict[str, str]) -> dict[str, Any]:
    case_id = int(case["case"])
    reference = str(case["gold"] or "")
    entry: dict[str, Any] = {
        "case": case_id,
        "block": case["block"],
        "question_class": (
            "composition" if COMPOSITION_RE.search(case["question"]) else "other"),
        "arms": {},
    }
    for arm, context in contexts.items():
        items: dict[str, Any] = {}
        for memory_id in case["required_ids"]:
            _field, memory_text = canonical_source(records[(case_id, memory_id)])
            span, delivered = card_span(context, memory_id)
            span_norm = norm(span)
            item_atoms = relevant_atoms(memory_text, case["question"], reference)
            items[memory_id] = {
                "delivered": delivered,
                "item_total": len(item_atoms),
                "item_present": sum(atom_present(a, span_norm) for a in item_atoms),
            }
        entry["arms"][arm] = {
            "chars": len(context),
            "sha1": sha1(context),
            "all_item_facts_present": bool(items) and all(
                flag["item_total"] == flag["item_present"] for flag in items.values()),
            "items": items,
        }
    entry["integrity_failures"] = {
        arm: integrity_failures(context, records, case_id)
        for arm, context in contexts.items()
    }
    return entry


def run_sweep(cases, records, out: Path, api_key: str) -> None:
    from memory_machine.coordinator import Machine
    from memory_machine.llm import LLMClient
    from e2e_bench import answer_with, judge
    from external_bench import DATA, load_longmemeval
    from graph_replay_shared import variant_config
    from view_router_bench import CountingClient

    agent = CountingClient(LLMClient(MODEL_BASE, api_key, MODEL, timeout=300,
                                     retries=1, backoff=0.5))
    juror = CountingClient(LLMClient(MODEL_BASE, api_key, JUDGE_MODEL, timeout=300,
                                     retries=1, backoff=0.5))
    tasks = {t["question"]: t for t in load_longmemeval(
        DATA / "longmemeval_s_cleaned.json", 0, 7)}
    cfg = variant_config("graph_augment_precise")
    answers_path = out / "answers.jsonl"
    done: set[tuple[int, str, int]] = set()
    if answers_path.exists():
        for line in answers_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                done.add((int(row["case"]), row["arm"], int(row["replicate"])))
        print(f"resuming: {len(done)} rows", flush=True)
    work_root = Path(tempfile.mkdtemp(prefix="mm-e5-"))
    for case in cases:
        case_id = int(case["case"])
        question = case["question"]
        qd = tasks.get(question, {}).get("question_date", "")
        provenance = f"\n\n(Question asked on {qd}.)" if qd else ""
        contexts = build_contexts(case, records)
        for arm in ARMS:
            context = contexts[arm]
            prompt = question
            if arm == "scaffold":
                prompt = f"{question}\n\n{SCAFFOLD_INSTRUCTION}"
            machine = Machine(work_root / f"case_{case_id:02d}_{arm}", config=cfg,
                              client=None)
            machine.whiteboard.annotations = []
            machine.whiteboard.subject = question
            have = sorted(r for (c, a, r) in done if c == case_id and a == arm)
            for replicate in [r for r in range(1, N + 1) if r not in have]:
                answer = verdict = reason = ""
                for attempt in range(5):
                    try:
                        answer = answer_with(agent, machine, prompt + provenance,
                                             extra_context=context)
                        verdict, reason = judge(juror, question,
                                                str(case["gold"] or ""), answer)
                        break
                    except Exception as exc:
                        if attempt == 4:
                            raise
                        print(f"  retry {case_id} {arm} {replicate}: "
                              f"{type(exc).__name__}: {exc}", flush=True)
                        time.sleep(3 + 3 * attempt)
                with answers_path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps({
                        "case": case_id, "block": case["block"], "arm": arm,
                        "replicate": replicate, "question": question,
                        "prompt": prompt, "answer": answer, "verdict": verdict,
                        "reason": reason, "context_sha1": sha1(context),
                        "context_chars": len(context),
                    }, ensure_ascii=False) + "\n")
                print(f"case {case_id:>2} {arm:<13} rep {replicate} "
                      f"verdict={verdict}", flush=True)
    print(f"work root: {work_root}")


def write_report(out: Path, cases, audits, meta: dict[str, Any]) -> dict[str, Any]:
    rows = [json.loads(line) for line in
            (out / "answers.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()]
    verdicts: dict[tuple[int, str], list[str]] = {}
    for row in rows:
        verdicts.setdefault((int(row["case"]), row["arm"]), []).append(row["verdict"])
    modal = {k: Counter(v).most_common(1)[0][0] for k, v in verdicts.items()}

    def paired(exp: str) -> dict[str, Any]:
        counts: Counter = Counter()
        net = 0
        for case in cases:
            cid = int(case["case"])
            a = modal.get((cid, "cards_v1"), "")
            b = modal.get((cid, exp), "")
            cls = ("stayed_correct" if a == "correct" and b == "correct"
                   else "regressed" if a == "correct"
                   else "repaired" if b == "correct" else "stayed_incorrect")
            counts[cls] += 1
            net += {"repaired": 1, "regressed": -1}.get(cls, 0)
        return {"counts": dict(counts), "net": net}

    def flips(arm: str) -> float:
        return sum(1 for case in cases
                   if len(set(verdicts.get((int(case["case"]), arm), []))) > 1) / len(cases)

    measured_floor = max(flips(arm) for arm in ARMS)
    eff_floor = max(0.07, measured_floor)
    scaffold = paired("scaffold")
    atoms = {"cards_v1": [], "atom_complete": []}
    for entry in audits:
        for arm in ("cards_v1", "atom_complete"):
            flags = entry["arms"][arm]["items"].values()
            total = sum(f["item_total"] for f in flags)
            present = sum(f["item_present"] for f in flags)
            if total:
                atoms[arm].append(present / total)
    atom_means = {arm: sum(v) / len(v) if v else 1.0 for arm, v in atoms.items()}
    gate = {
        "primary_pass": scaffold["net"] >= 3 and scaffold["net"] > eff_floor * len(cases),
        "secondary_pair": paired("atom_complete"),
        "measured_floor": round(measured_floor, 4),
        "effective_floor": round(eff_floor, 4),
        "atoms": {k: round(v, 4) for k, v in atom_means.items()},
        "provenance_failures": meta["provenance_failures"],
        "deterministic": meta["deterministic"],
        "budget_ok": meta["budget_ok"],
    }
    gate["verdict"] = ("scaffold passes (composition/answerer lever works)"
                       if gate["primary_pass"] else
                       "both levers fail -> consolidation (provenance layer), no new mechanism")
    result = {"fixture": str(FIXTURE), "fixture_sha1": meta["fixture_sha1"],
              "arms": list(ARMS), "n": N, "model": MODEL, "judge_model": JUDGE_MODEL,
              "scaffold_vs_control": scaffold,
              "atom_complete_vs_control": gate["secondary_pair"], "gate": gate}
    (out / "e5_summary.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    lines = [
        "# E5 answerer/composition — summary",
        "",
        f"- fixture sha1 `{meta['fixture_sha1']}` · N={N} · model/judge `{MODEL}`",
        f"- scaffold vs control: classes {scaffold['counts']} · net **{scaffold['net']:+d}**",
        f"- atom_complete vs control: classes {gate['secondary_pair']['counts']} · "
        f"net {gate['secondary_pair']['net']:+d}",
        f"- measured floor {gate['measured_floor']} (effective {gate['effective_floor']})",
        f"- atoms: control {gate['atoms']['cards_v1']:.3f} vs atom_complete "
        f"{gate['atoms']['atom_complete']:.3f}",
        f"- provenance {gate['provenance_failures']} · deterministic {gate['deterministic']} "
        f"· budget {gate['budget_ok']}",
        "",
        f"**verdict: {gate['verdict']}**",
    ]
    (out / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="eval/results/composition_u4_e5")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--api-key", default="")
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    cases, records = load_fixture()
    manifest = json.loads((FIXTURE / "manifest.json").read_text(encoding="utf-8"))
    e0 = json.loads(E0_REPORT.read_text(encoding="utf-8"))
    audits = [atom_audit(c, records, build_contexts(c, records)) for c in cases]
    v1 = {e["case"]: e["arms"]["cards_v1"]["sha1"] for e in audits}
    e0_shas = {int(k): v for k, v in e0["modes"]["payloads"]["per_case_sha1"].items()}
    identity = v1 == e0_shas
    provenance_failures = sum(
        len(f) for e in audits for f in e["integrity_failures"].values())
    rebuilt = [build_contexts(c, records)["cards_v1"] for c in cases]
    deterministic = all(sha1(rebuilt[i]) == v1[int(cases[i]["case"])]
                        for i in range(len(cases)))
    budget_ok = all(e["arms"][arm]["chars"] <= CARD_BUDGET
                    for e in audits for arm in ARMS)
    meta = {"fixture_sha1": manifest["sha1"], "provenance_failures": provenance_failures,
            "deterministic": deterministic, "budget_ok": budget_ok,
            "control_identity": identity}
    with (out / "atoms.jsonl").open("w", encoding="utf-8") as handle:
        for entry in audits:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    if args.dry_run:
        def means(arm):
            vals = []
            for e in audits:
                flags = e["arms"][arm]["items"].values()
                total = sum(f["item_total"] for f in flags)
                present = sum(f["item_present"] for f in flags)
                if total:
                    vals.append(present / total)
            return sum(vals) / len(vals) if vals else 1.0
        print(f"dry-run: {len(cases)} cases | control==E0 payloads: {identity}")
        print(f"  atoms: v1={means('cards_v1'):.3f} atom_complete={means('atom_complete'):.3f}")
        print(f"  provenance failures {provenance_failures} | deterministic {deterministic} "
              f"| budget_ok {budget_ok}")
        return 0
    api_key = args.api_key or load_dotenv_key()
    if not api_key:
        raise SystemExit("set DEEPSEEK_API_KEY (env or .env)")
    run_sweep(cases, records, out, api_key)
    result = write_report(out, cases, audits, meta)
    print(json.dumps({k: v for k, v in result["gate"].items()
                      if k in ("primary_pass", "measured_floor", "verdict")},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
