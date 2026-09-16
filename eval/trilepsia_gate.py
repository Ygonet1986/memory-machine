#!/usr/bin/env python3
"""B2 vs B2+ gate runner — frozen by docs/TRILEPSIA_GATE_V1.md (a0bf60d).

Arms (same questions, order, prompts, model, judge, batch; only context
assembly differs):

  B2   graph recall (`augment_guarded`, question gate OFF) -> budgeted precise
       payload (4000 chars). No Trilepsia. (This fresh fixture has no agent
       side, so B2 = graph annotations only; both arms share this base.)
  B2+  B2 context + Trilepsia augment: up to 3 units whose `derived_from`
       intersects the B2 candidate ids, rendered as exact-quote typed blocks
       within ONE global 4000-char budget; overflow units are dropped and
       counted.

Measures: paired strict delta (primary), qualification accuracy on the 16
epistemic cases (secondary, state token vs gold), atom retention guard on the
factual cases, provenance re-check of every rendered unit claim, determinism.
N=5 replicates per case-arm; the identical-context pair flip rate is measured
on the same replicates; effective floor = max(0.07, measured).

Dry-run (no LLM):  PYTHONPATH=src python3 eval/trilepsia_gate.py --dry-run
Live:              PYTHONPATH=src python3 eval/trilepsia_gate.py \
                       --out eval/results/trilepsia_gate_v1
"""

from __future__ import annotations

import argparse
import hashlib
import json
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

from composition_e1 import load_dotenv_key  # noqa: E402

ARMS = ("b2", "b2plus")
N = 5
MODEL = "deepseek-v4-flash"
JUDGE_MODEL = "deepseek-v4-flash"
MODEL_BASE = "https://api.deepseek.com"
BUDGET = 4000
MAX_UNITS = 3
STATE_TOKENS = ("reported", "observed", "contested", "refuted", "supported",
                "superseded", "unknown")
NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)?")


def sha1(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def load_fixture(root: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in (root / "cases.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


# ---------------------------------------------------------------------------
# Context arms


def b2_context(root: Path, question: str) -> tuple[str, list[str]]:
    """Graph recall + budgeted payload; returns (context, payload_ids)."""
    from memory_machine.coordinator import Machine
    from memory_machine.graph import GraphStore
    from memory_machine.graph_recall import GraphRecall, guard_evidence
    from memory_machine.payload import build_evidence_payload, payload_as_context
    from memory_machine.tape import Tape
    from memory_machine.whiteboard import Annotation, merge_annotations

    from graph_replay_shared import variant_config

    cfg = variant_config("graph_augment_precise")
    store = GraphStore(root / "graph")
    recall = GraphRecall(
        store.index(), depth=cfg.graph_depth, top_k=cfg.graph_top_k,
        hub_degree=cfg.graph_augment_hub_degree,
    )
    evidence = guard_evidence(
        recall.recall(question).evidence,
        min_score=cfg.graph_augment_min_score,
        max_items=cfg.graph_augment_max_items,
    )
    records = {r.id: r for r in Tape(root / "tape.jsonl").read()}
    active = {r.id for r in records.values() if r.status == "active"}
    annotations = [
        Annotation(
            memory_id=item.memory_id,
            note=item.label or "graph evidence",
            relevance=max(0.05, float(item.score)),
            agent_id="graph",
        )
        for item in evidence
        if item.memory_id in active
    ]
    machine = Machine(
        Path(tempfile.mkdtemp(prefix="mm-gate-wb-")), config=cfg, client=None
    )
    machine.whiteboard.subject = question
    kept = merge_annotations(machine.whiteboard, annotations,
                             budget=cfg.whiteboard_budget)
    payload = build_evidence_payload(
        records, kept, budget=cfg.evidence_payload_budget,
        min_item_chars=cfg.evidence_payload_min_item,
    )
    return payload_as_context(payload), [item["memory_id"] for item in payload]


def render_unit(unit: Any) -> str:
    envelope = unit.trilepsia or {}
    raw = envelope.get("raw") or {}
    schema = str(envelope.get("schema_version") or "")
    scope = str((envelope.get("V") or {}).get("scope") or "")
    lines = [f"[{unit.id} | {schema} | {scope}]"]
    for item in raw.get("observations") or []:
        content = str(item.get("content") or "").strip()
        if content:
            lines.append(f'({item.get("kind") or "reported"}) "{content}"')
    for item in raw.get("hypotheses") or []:
        statement = str(item.get("statement") or "").strip()
        if statement:
            lines.append(f"({item.get('state') or 'open'}) {statement}")
    for item in raw.get("qualifications") or []:
        attr = str(item.get("attr") or "").strip()
        if attr:
            lines.append(
                f"{attr}={item.get('value')} "
                f"(evaluated={bool(item.get('evaluated'))})"
            )
    for item in raw.get("unknowns") or []:
        lines.append(f"unknown: {item}")
    return "\n".join(lines)


def b2plus_context(
    root: Path, question: str, candidates: list[str], base: str
) -> tuple[str, dict[str, Any]]:
    """B2 context + Trilepsia augment under one global budget."""
    from memory_machine.tape import Tape

    units = [r for r in Tape(root / "tape.jsonl").read() if r.type == "trilepsia_unit"]
    ranked = []
    for unit in units:
        overlap = len(set(unit.derived_from) & set(candidates))
        if overlap:
            ranked.append((-overlap, unit.id, unit))
    ranked.sort(key=lambda row: (row[0], row[1]))
    used = len(base)
    blocks: list[str] = []
    dropped = 0
    for _neg, _uid, unit in ranked:
        if len(blocks) >= MAX_UNITS:
            dropped += 1
            continue
        block = render_unit(unit)
        add = len(block) + 2
        if used + add > BUDGET:
            dropped += 1
            continue
        blocks.append(block)
        used += add
    context = base
    if blocks:
        context = base + ("\n\n" if base else "") + "\n\n".join(blocks)
    return context, {"units_considered": len(ranked), "units_used": len(blocks),
                     "units_dropped": dropped, "chars": len(context)}


def unit_provenance_failures(root: Path, unit: Any) -> list[str]:
    """Every rendered observation quote must be exact in the preserved original."""
    envelope = unit.trilepsia or {}
    raw = envelope.get("raw") or {}
    doc_name = str(unit.source or "").split("#", 1)[0]
    original_path = root / "documents" / doc_name
    if not original_path.exists():
        return [f"{unit.id}: original missing for {doc_name}"]
    original = original_path.read_text(encoding="utf-8", errors="replace").strip()
    failures: list[str] = []
    for item in raw.get("observations") or []:
        span = item.get("evidence_span")
        content = str(item.get("content") or "")
        if not content or not span:
            continue
        start, end = int(span[0]), int(span[1])
        if not (0 <= start < end <= len(original)) or original[start:end] != content:
            failures.append(f"{unit.id}: quote not exact at {span}")
    return failures


def required_atoms(gold: str) -> list[str]:
    values = []
    for match in NUMBER_RE.finditer(gold.replace(",", "")):
        value = match.group(0)
        if value not in values:
            values.append(value)
    return values


# ---------------------------------------------------------------------------
# LLM sweep


def state_prompt(question: str, answer: str) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": (
            "You classify the epistemic status of an answer. Reply with ONE "
            f"token from: {', '.join(STATE_TOKENS)}. Use 'unknown' when the "
            "answer says the datum is indeterminate or causation is not "
            "established. Reply with the token only."
        )},
        {"role": "user", "content": f"Question: {question}\nAnswer: {answer}"},
    ]


def run_sweep(root: Path, cases: list[dict[str, Any]], out: Path, api_key: str) -> None:
    from memory_machine.coordinator import Machine
    from memory_machine.llm import LLMClient

    from e2e_bench import answer_with, judge
    from graph_replay_shared import variant_config
    from view_router_bench import CountingClient

    agent_client = CountingClient(
        LLMClient(MODEL_BASE, api_key, MODEL, timeout=300, retries=1, backoff=0.5))
    judge_client = CountingClient(
        LLMClient(MODEL_BASE, api_key, JUDGE_MODEL, timeout=300, retries=1, backoff=0.5))
    cfg = variant_config("graph_augment_precise")
    answers_path = out / "answers.jsonl"
    done: set[tuple[str, str, int]] = set()
    if answers_path.exists():
        for line in answers_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                done.add((row["case_id"], row["arm"], int(row["replicate"])))
        print(f"resuming: {len(done)} rows", flush=True)

    work_root = Path(tempfile.mkdtemp(prefix="mm-gate-"))
    for case in cases:
        question = case["question"]
        base, candidates = b2_context(root, question)
        plus, plus_meta = b2plus_context(root, question, candidates, base)
        contexts = {"b2": base, "b2plus": plus}
        for arm in ARMS:
            context = contexts[arm]
            machine = Machine(
                work_root / f"{case['case_id']}_{arm}", config=cfg, client=None)
            machine.whiteboard.annotations = []
            machine.whiteboard.subject = question
            have = sorted(r for (c, a, r) in done
                          if c == case["case_id"] and a == arm)
            for replicate in [r for r in range(1, N + 1) if r not in have]:
                answer = ""
                verdict = ""
                reason = ""
                state = ""
                for attempt in range(5):
                    try:
                        answer = answer_with(agent_client, machine, question,
                                             extra_context=context)
                        verdict, reason = judge(
                            judge_client, question, case["gold_answer"], answer)
                        if case["class"] == "epistemic":
                            raw_state = judge_client.complete(
                                state_prompt(question, answer), temperature=0.0)
                            token = str(raw_state or "").strip().lower()
                            state = token if token in STATE_TOKENS else ""
                        break
                    except Exception as exc:
                        if attempt == 4:
                            raise
                        print(f"  retry {case['case_id']} {arm} {replicate}: "
                              f"{type(exc).__name__}: {exc}", flush=True)
                        time.sleep(3 + 3 * attempt)
                with answers_path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps({
                        "case_id": case["case_id"], "class": case["class"],
                        "type": case["type"], "arm": arm,
                        "replicate": replicate, "question": question,
                        "answer": answer, "verdict": verdict, "reason": reason,
                        "state": state, "gold_state": case["gold_state"],
                        "context_sha1": sha1(context),
                        "context_chars": len(context),
                        "plus_meta": plus_meta if arm == "b2plus" else {},
                    }, ensure_ascii=False) + "\n")
                print(f"{case['case_id']} {arm:<7} rep {replicate} "
                      f"verdict={verdict} state={state}", flush=True)
    print(f"work root: {work_root}")


# ---------------------------------------------------------------------------
# Report


def write_report(out: Path, cases: list[dict[str, Any]], meta: dict[str, Any]) -> dict[str, Any]:
    rows = [
        json.loads(line)
        for line in (out / "answers.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    verdicts: dict[tuple[str, str], list[str]] = {}
    states: dict[tuple[str, str], list[str]] = {}
    for row in rows:
        verdicts.setdefault((row["case_id"], row["arm"]), []).append(row["verdict"])
        if row["class"] == "epistemic":
            states.setdefault((row["case_id"], row["arm"]), []).append(row["state"])
    modal = {key: Counter(v).most_common(1)[0][0] for key, v in verdicts.items()}

    ledger = []
    counts: Counter = Counter()
    net = 0
    for case in cases:
        cid = case["case_id"]
        a = modal.get((cid, "b2"), "")
        b = modal.get((cid, "b2plus"), "")
        a_ok, b_ok = a == "correct", b == "correct"
        cls = ("stayed_correct" if a_ok and b_ok else "regressed" if a_ok
               else "repaired" if b_ok else "stayed_incorrect")
        counts[cls] += 1
        net += {"repaired": 1, "regressed": -1}.get(cls, 0)
        ledger.append({"case_id": cid, "class": case["class"], "type": case["type"],
                       "b2": a, "b2plus": b, "cls": cls,
                       "net": {"repaired": 1, "regressed": -1}.get(cls, 0)})

    def qualification_accuracy(arm: str) -> float:
        total = hits = 0
        for case in cases:
            if case["class"] != "epistemic":
                continue
            for token in states.get((case["case_id"], arm), []):
                total += 1
                hits += int(token == case["gold_state"])
        return hits / total if total else 0.0

    def within_arm_flips(arm: str) -> float:
        flips = sum(1 for case in cases
                    if len(set(verdicts.get((case["case_id"], arm), []))) > 1)
        return flips / len(cases) if cases else 0.0

    measured_floor = max(within_arm_flips("b2"), within_arm_flips("b2plus"))
    eff_floor = max(0.07, measured_floor)
    qa_b2 = qualification_accuracy("b2")
    qa_plus = qualification_accuracy("b2plus")
    gate = {
        "net": net, "cases": len(cases),
        "net_rate": round(net / len(cases), 4) if cases else 0.0,
        "measured_floor": round(measured_floor, 4),
        "effective_floor": round(eff_floor, 4),
        "primary_pass": net >= 3 and net > eff_floor * len(cases),
        "qualification_b2": round(qa_b2, 4),
        "qualification_b2plus": round(qa_plus, 4),
        "secondary_pass": qa_plus > qa_b2,
        "atom_guard_pass": meta["atoms"]["plus"] >= meta["atoms"]["b2"] - 0.05,
        "provenance_failures": meta["provenance_failures"],
        "deterministic": meta["deterministic"],
        "budget_ok": meta["budget_ok"],
    }
    gate["promote"] = bool(
        gate["primary_pass"] and gate["secondary_pass"] and gate["atom_guard_pass"]
        and not gate["provenance_failures"] and gate["deterministic"]
        and gate["budget_ok"])
    gate["verdict"] = ("promote B2+ (analytical contribution)"
                       if gate["promote"] else
                       "provenance layer only (no demonstrated analytical gain) — T3 blocked")

    result = {"fixture": meta["fixture"], "fixture_sha1": meta["fixture_sha1"],
              "arms": list(ARMS), "n": N, "model": MODEL, "judge_model": JUDGE_MODEL,
              "accuracy": {"counts": dict(counts), "ledger": ledger},
              "qualification": {"b2": qa_b2, "b2plus": qa_plus},
              "gate": gate}
    (out / "e4_summary.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (out / "paired_ledger.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in ledger) + "\n",
        encoding="utf-8")
    lines = [
        "# Gate B2 vs B2+ — summary",
        "",
        f"- fixture sha1 `{meta['fixture_sha1']}` · N={N} · model/judge `{MODEL}`",
        f"- classes: {dict(counts)}",
        f"- net (paired strict): **{net:+d}** ({gate['net_rate']:+.4f})",
        f"- measured identical-context floor: {gate['measured_floor']:.4f} "
        f"(effective max(0.07, measured) = {gate['effective_floor']:.4f})",
        f"- qualification accuracy: B2 {qa_b2:.4f} vs B2+ {qa_plus:.4f}",
        f"- atoms: b2 {meta['atoms']['b2']:.3f} vs b2plus {meta['atoms']['plus']:.3f}",
        f"- provenance failures: {gate['provenance_failures']} · "
        f"deterministic: {gate['deterministic']} · budget_ok: {gate['budget_ok']}",
        "",
        f"**verdict: {gate['verdict']}**",
    ]
    (out / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", default="eval/fixtures/trilepsia_gate_v1")
    parser.add_argument("--out", default="eval/results/trilepsia_gate_v1")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--api-key", default="")
    args = parser.parse_args()

    root = Path(args.fixture)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    cases = load_fixture(root)
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))

    # deterministic contexts + guards
    from memory_machine.tape import Tape

    tape_records = {r.id: r for r in Tape(root / "tape.jsonl").read()}
    contexts: dict[str, dict[str, str]] = {}
    atoms = {"b2": [], "plus": []}
    for case in cases:
        base, candidates = b2_context(root, case["question"])
        plus, _meta = b2plus_context(root, case["question"], candidates, base)
        contexts[case["case_id"]] = {"b2": base, "b2plus": plus}
        if case["class"] == "factual":
            gold_atoms = list(case.get("required_atoms") or [])
            if gold_atoms:
                for arm, context in (("b2", base), ("plus", plus)):
                    atoms[arm].append(
                        sum(1 for value in gold_atoms if value in context)
                        / len(gold_atoms))
    provenance_failures = sum(
        len(unit_provenance_failures(root, unit))
        for unit in tape_records.values() if unit.type == "trilepsia_unit")
    rebuilt = [b2_context(root, case["question"])[0] for case in cases]
    deterministic = all(
        sha1(rebuilt[i]) == sha1(contexts[case["case_id"]]["b2"])
        for i, case in enumerate(cases))
    atom_means = {arm: (sum(values) / len(values) if values else 1.0)
                  for arm, values in atoms.items()}
    budget_ok = all(len(context) <= BUDGET for pair in contexts.values()
                    for context in pair.values())
    meta = {
        "fixture": str(root),
        "fixture_sha1": manifest["sha1"],
        "atoms": {"b2": atom_means["b2"], "plus": atom_means["plus"]},
        "provenance_failures": provenance_failures,
        "deterministic": deterministic,
        "budget_ok": budget_ok,
    }

    if args.dry_run:
        print(f"dry-run: {len(cases)} cases")
        print(f"  atoms (factual) b2={atom_means['b2']:.3f} plus={atom_means['plus']:.3f}")
        print(f"  provenance failures: {provenance_failures} | "
              f"deterministic: {deterministic} | budget_ok: {budget_ok}")
        return 0

    api_key = args.api_key or load_dotenv_key()
    if not api_key:
        raise SystemExit("set DEEPSEEK_API_KEY (env or .env)")
    with (out / "contexts.jsonl").open("w", encoding="utf-8") as handle:
        for cid, pair in contexts.items():
            handle.write(json.dumps(
                {"case_id": cid, "contexts": pair,
                 "sha1": {a: sha1(c) for a, c in pair.items()}},
                ensure_ascii=False) + "\n")
    run_sweep(root, cases, out, api_key)
    result = write_report(out, cases, meta)
    print(json.dumps(result["gate"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
