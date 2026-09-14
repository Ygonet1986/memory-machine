"""U4.3 — multi-anchor delivery composition (mechanics first, pre-registered).

Two variants over the frozen U3 precise payloads (budget 4000 unchanged), on
the 30 U3 cases (blocks a+b). The base payload must rebuild byte-identical to
the frozen `graph_augment_precise` context (asserted, else abort); variants
then only re-fill how truncation happens for the top truncated items:

  multi_window  window the two highest-relevance truncated items (each keeps
                header+summary and gets a question-windowed why in the SAME
                allocation; item truncated -> same budget).
  anchor_keep   the highest-relevance truncated item keeps its default head
                (the anchor); only the second-best truncated item is windowed.

Both are deterministic (no LLM) and bounded by each item's existing allocation,
so the 4000-char budget and the locked payload contract are preserved.

The pre-registered primary evaluation is U4.1's delivery metric: do these
policies put more question-relevant facts in the same space, especially on
composition questions? (The U4.2 gate 0.07-0.08 governs any later answer claim.)

Run: PYTHONPATH=src:.:eval python3 eval/u4_composition.py
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "src"))

from memory_machine.payload import build_evidence_payload, payload_as_context  # noqa: E402
from memory_machine.tape import Tape  # noqa: E402
from memory_machine.whiteboard import Annotation, merge_annotations  # noqa: E402

from fact_presence import (  # noqa: E402
    COMPOSITION_RE,
    SINGLE_RE,
    atom_present,
    entity_atoms,
    item_fact_atoms,
    item_span,
    norm,
    relevant_atoms,
    strong_atoms,
    term_atoms,
)
from graph_util_diag import frozen_agent_annotations  # noqa: E402
from memory_machine.graph_recall import guard_evidence, question_gate  # noqa: E402
from memory_machine.graph import GraphStore  # noqa: E402
from memory_machine.graph_recall import GraphRecall  # noqa: E402
from graph_replay_shared import variant_config  # noqa: E402

OUT_DIR = HERE / "graph_out"
TMP = Path("/var/folders/3z/9n8mh2p12ld771wy19z5v7rw0000gn/T")
SLICES = {
    "longmemeval_u3a": {
        "snapshot": "u_diag_longmemeval_u3a.jsonl",
        "root": TMP / "mm-graph-shared-wnps8c6d",
    },
    "longmemeval_u3b": {
        "snapshot": "u_diag_longmemeval_u3b.jsonl",
        "root": TMP / "mm-graph-shared-7ggare_r",
    },
    "longmemeval_lexmiss": {
        "snapshot": "u_diag_longmemeval_lexmiss.jsonl",
        "root": TMP / "mm-graph-shared-r3hyd5my",
    },
}


def precise_evidence(base: Path, cfg: Any, question: str) -> list[Any]:
    store = GraphStore(base / "graph")
    hub = cfg.graph_hub_degree
    if not hub and cfg.graph_recall_mode == "augment_guarded":
        hub = cfg.graph_augment_hub_degree
    recall = GraphRecall(store.index(), depth=cfg.graph_depth, top_k=cfg.graph_top_k, hub_degree=hub)
    evidence = recall.recall(question).evidence
    evidence = guard_evidence(
        evidence,
        min_score=cfg.graph_augment_min_score,
        max_items=cfg.graph_augment_max_items,
    )
    if cfg.graph_augment_question_gate:
        records = {r.id: r for r in Tape(base / "tape.jsonl").read()}
        evidence = question_gate(evidence, records, question, min_cov=cfg.graph_augment_question_min_cov)
    return evidence


def build_base(root: Path, row: dict[str, Any]):
    cfg = variant_config("graph_augment_precise")
    base = root / f"case_{row['case']:02d}"
    records = {r.id: r for r in Tape(base / "tape.jsonl").read()}
    question = row["question"]
    evidence = precise_evidence(base, cfg, question)
    active = {r.id for r in records.values() if r.status == "active"}
    graph_annotations = [
        Annotation(
            memory_id=item.memory_id,
            note=item.label or "graph evidence",
            relevance=max(0.05, float(item.score)),
            agent_id="graph",
        )
        for item in evidence
        if item.memory_id in active
    ]
    by_id = {a.memory_id: a for a in frozen_agent_annotations({"root": root, "case": row["case"], "row": row})}
    for item in graph_annotations:
        current = by_id.get(item.memory_id)
        if current is None:
            by_id[item.memory_id] = item
        elif item.relevance > current.relevance:
            by_id[item.memory_id] = Annotation(
                memory_id=current.memory_id,
                note=current.note or item.note,
                relevance=item.relevance,
                agent_id=current.agent_id or item.agent_id,
            )
    from memory_machine.coordinator import Machine
    import tempfile
    machine = Machine(Path(tempfile.mkdtemp(prefix="mm-u43-wb-")), config=cfg, client=None)
    machine.whiteboard.subject = question
    kept = merge_annotations(machine.whiteboard, list(by_id.values()), budget=cfg.whiteboard_budget)
    payload = build_evidence_payload(
        records, kept, budget=cfg.evidence_payload_budget,
        min_item_chars=cfg.evidence_payload_min_item,
    )
    context = payload_as_context(payload)
    return cfg, records, by_id, kept, payload, context, question


def _window_item(item: dict[str, Any], record: Any, question: str) -> None:
    header = item["evidence"].split("\n", 1)[0]
    summary = record.summary or ""
    room = item["used_chars"] - len(header) - 1
    if summary:
        room -= len(summary) + 1
    from memory_machine.payload import fact_window

    body = fact_window(record.why or "", question, max(0, room))
    if body:
        item["evidence"] = f"{header}\n{summary}\n{body}" if summary else f"{header}\n{body}"
        item["windowed"] = True


def variant_payload(record_by_id: dict[str, Any], payload: list[dict[str, Any]], question: str, variant: str) -> list[dict[str, Any]]:
    out = [dict(item) for item in payload]
    candidates = [i for i in out if i["truncated"]]
    if variant == "multi_window":
        for item in candidates[:2]:
            rec = record_by_id.get(item["memory_id"])
            if rec is not None:
                _window_item(item, rec, question)
    elif variant == "anchor_keep":
        if len(candidates) >= 2:
            rec = record_by_id.get(candidates[1]["memory_id"])
            if rec is not None:
                _window_item(candidates[1], rec, question)
    return out


def main() -> None:
    summary: dict[str, Any] = {"slices": {}, "cases": 0}
    out_rows = []
    for slice_name, spec in SLICES.items():
        rows = [
            json.loads(line)
            for line in (OUT_DIR / spec["snapshot"]).read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        per_arm: dict[str, Counter] = defaultdict(Counter)
        results = []
        for row in rows:
            cfg, records, by_id, kept, payload, base_context, question = build_base(spec["root"], row)
            precise_ctx = row["arms"]["graph_augment_precise"]["context"]
            if base_context != precise_ctx:
                raise RuntimeError(
                    f"case {row['case']}: base precise rebuild differs from the frozen snapshot"
                )
            record_by_id = {r.id: r for r in records.values()}
            variants = {
                "graph_augment_precise": payload,
                "multi_window": variant_payload(record_by_id, payload, question, "multi_window"),
                "anchor_keep": variant_payload(record_by_id, payload, question, "anchor_keep"),
            }
            contexts = {name: payload_as_context(p) for name, p in variants.items()}
            gold_source = row["arms"]["graph_augment_precise"].get("gold") or []
            gold_texts = {g["memory_id"]: g.get("gold_text", "") for g in gold_source}
            reference = str(row["gold"] or "")
            strong = strong_atoms(reference)
            entities = entity_atoms(reference)
            terms = term_atoms(reference)
            question_class = (
                "composition" if COMPOSITION_RE.search(question)
                else "single" if SINGLE_RE.search(question) else "other"
            )
            entry: dict[str, Any] = {
                "slice": slice_name,
                "case": row["case"],
                "question_class": question_class,
                "question": question,
                "reference": reference,
                "arms": {},
            }
            for arm, context in contexts.items():
                flags = {}
                for memory_id in row["required_ids"]:
                    span, delivered = item_span(context, memory_id)
                    span_norm = norm(span)
                    memory_text = gold_texts.get(memory_id, "")
                    item_atoms = relevant_atoms(memory_text, question, reference)
                    all_atoms = item_fact_atoms(memory_text)
                    flags[memory_id] = {
                        "delivered": delivered,
                        "item_total": len(item_atoms),
                        "item_present": sum(atom_present(a, span_norm) for a in item_atoms),
                        "all_total": len(all_atoms),
                        "all_present": sum(atom_present(a, span_norm) for a in all_atoms),
                    }
                    per_arm[arm]["item_total"] += len(item_atoms)
                    per_arm[arm]["item_present"] += sum(atom_present(a, span_norm) for a in item_atoms)
                    per_arm[arm]["gold_items"] += 1
                    per_arm[arm]["gold_delivered"] += int(delivered)
                all_items = all(
                    f["item_total"] == f["item_present"]
                    for f in flags.values()
                ) and bool(flags)
                per_arm[arm]["cases"] += 1
                per_arm[arm][f"class_{question_class}"] += 1
                per_arm[arm]["all_items"] += int(all_items)
                per_arm[arm]["chars"] += len(context) if context else 0
                entry["arms"][arm] = {
                    "chars": len(context) if context else 0,
                    "all_item_facts_present": all_items,
                    "windowed_items": sum(1 for p in variants[arm] if p.get("windowed")),
                    "payload_chars": sum(len(p["evidence"]) for p in variants[arm]),
                    "items": flags,
                }
            results.append(entry)
        out_path = OUT_DIR / "u4_composition.jsonl"
        with out_path.open("w", encoding="utf-8") as handle:
            for item in results:
                handle.write(json.dumps(item, ensure_ascii=False) + "\n")
        out_rows.append((slice_name, results))
        summary["slices"][slice_name] = {
            "n": len(results),
            "per_arm": {k: dict(v) for k, v in per_arm.items()},
        }
        summary["cases"] += len(results)

    lines = ["# U4.3 — multi-anchor composition: delivery mechanics (deterministic)",
             "",
             "Base payload recomputed from frozen roots and verified byte-identical "
             "to the `graph_augment_precise` snapshot context on all cases before the "
             "variant transformations are applied (budget 4000 unchanged).",
             "",
             "| slice | arm | item-facts present | all-present cases | chars delivered |",
             "|---|---|---|---|---|"]
    for slice_name, results in out_rows:
        per_arm: dict[str, Counter] = defaultdict(Counter)
        for r in results:
            for arm, payload in r["arms"].items():
                per_arm[arm]["item_total"] += sum(f["item_total"] for f in payload["items"].values())
                per_arm[arm]["item_present"] += sum(f["item_present"] for f in payload["items"].values())
                per_arm[arm]["all_items"] += int(payload["all_item_facts_present"])
                per_arm[arm]["cases"] += 1
                per_arm[arm]["chars"] += payload["chars"]
                per_arm[arm][f"class_{r['question_class']}"] += 1
        for arm in ("graph_augment_precise", "multi_window", "anchor_keep"):
            d = per_arm[arm]
            rate = d["item_present"] / d["item_total"] if d["item_total"] else 0
            lines.append(
                f"| {slice_name} | {arm} | {d['item_present']}/{d['item_total']} ({rate:.2f}) | "
                f"{d['all_items']}/{d['cases']} | {d['chars']} |"
            )
    lines += ["", "Composition questions only (the U4.1 concern):"]
    for slice_name, results in out_rows:
        lines.append(f"**{slice_name}**")
        for arm in ("graph_augment_precise", "multi_window", "anchor_keep"):
            tot = present = 0
            all_present = 0
            count = 0
            for r in results:
                if r["question_class"] != "composition":
                    continue
                a = r["arms"][arm]
                for f in a["items"].values():
                    tot += f["item_total"]
                    present += f["item_present"]
                all_present += int(a["all_item_facts_present"])
                count += 1
            rate = present / tot if tot else 0
            lines.append(f"- {arm}: {present}/{tot} ({rate:.2f}), all-present cases {all_present}/{count}")
    (OUT_DIR / "u4_composition_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()