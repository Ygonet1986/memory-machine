"""U4.1 — deterministic fact presence in the delivered context.

Reads the frozen u_diag snapshots (no LLM, no re-runs) and checks, per case
and arm, whether the reference answer's atoms survive in the delivered span of
each required memory. Pre-registered categories:

  strong  numbers (+unit when present) and dates/intervals — low false-positive
  entity  capitalized tokens not at sentence start — medium
  term    content tokens (len>=5) — weak, diagnostic only, never primary

Per the U4 pre-registration: report extractor false positives/negatives
(all-strong-present but wrong; strong-missing but correct) instead of hiding
them, and recompute the U3 causal ledger with presence as the variable:
a repair is strong-presence 0 -> 1, a regression is 1 -> 0.

Outputs: eval/graph_out/fact_presence_<slice>.jsonl and fact_presence_summary.md
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
OUT = HERE / "graph_out"
SLICES = [
    "longmemeval",
    "longmemeval_lexmiss",
    "longmemeval_u3a",
    "longmemeval_u3b",
]

MONTHS = (
    "january|february|march|april|may|june|july|august|september|october|"
    "november|december"
)
UNIT_WORDS = {
    "hour", "hours", "day", "days", "week", "weeks", "month", "months",
    "year", "years", "minute", "minutes", "second", "seconds", "time", "times",
    "percent", "dollar", "dollars", "mile", "miles", "km", "kilometers",
    "kg", "pounds", "people", "person", "doctor", "doctors", "project",
    "projects", "book", "books", "bass", "followers", "hours",
}
SINGLE_RE = re.compile(
    r"\b(how long|how many|how much time|what time|when|where|which|who|name|duration)\b",
    re.I,
)
COMPOSITION_RE = re.compile(
    r"\b(increase|decrease|difference|change|between|total|combined|altogether|times)\b",
    re.I,
)
STOP_WORDS = {
    "the", "and", "for", "with", "that", "this", "from", "have", "has", "had",
    "was", "were", "are", "you", "your", "about", "into", "over", "after",
    "before", "when", "where", "which", "while", "there", "their", "them",
    "they", "then", "than", "some", "most", "much", "many", "more", "less",
    "total", "answer", "reference", "approximately", "around", "about",
    "actually", "record", "records", "memory", "memories", "times", "time",
}
SENTENCE_START = {"the", "a", "an", "i", "you", "he", "she", "it", "we", "they",
                  "there", "this", "that", "these", "those", "in", "on", "at",
                  "by", "for", "with", "from", "after", "before", "during",
                  "your", "my", "our", "according", "based", "yes", "no"}


def norm(text: str) -> str:
    text = text.lower()
    text = re.sub(r"(?<=\d),(?=\d)", "", text)  # 1,000 -> 1000
    return text


def strong_atoms(reference: str) -> list[dict[str, Any]]:
    atoms: list[dict[str, Any]] = []
    for match in re.finditer(r"\b(\d+(?:\.\d+)?)\s*%?", reference):
        number = match.group(1)
        tail = reference[match.end() : match.end() + 16].strip().lower()
        unit = ""
        for candidate in re.findall(r"[a-z]+", tail)[:2]:
            if candidate in UNIT_WORDS:
                unit = candidate
                break
        atoms.append({"kind": "number", "value": number, "unit": unit})
    for match in re.finditer(rf"\b(?:19|20)\d{{2}}\b|\b(?:{MONTHS})\b", reference, re.I):
        atoms.append({"kind": "date", "value": match.group(0).lower(), "unit": ""})
    for match in re.finditer(r"\b\d+\s*(?:day|week|month|year)s?\b", reference, re.I):
        atoms.append({"kind": "interval", "value": norm(match.group(0)).replace(" ", ""), "unit": ""})
    # dedupe identical atoms
    seen = set()
    unique = []
    for atom in atoms:
        key = (atom["kind"], atom["value"], atom["unit"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(atom)
    return unique


def item_fact_atoms(gold_text: str) -> list[dict[str, Any]]:
    """Atoms from the MEMORY itself (numbers/entities/dates), not the reference.

    These measure how much of this memory's fact-bearing content survived in
    the delivered span, which is the delivery question and works for both
    single-fact and composition answers (the latter derive counts, so the
    reference number is a conclusion rather than a fact on the tape).
    """
    atoms: list[dict[str, Any]] = []
    for match in re.finditer(r"\b(\d+(?:\.\d+)?)\s*%?", gold_text):
        number = match.group(1)
        if len(number) == 4 and number[:2] in {"19", "20"}:
            atoms.append({"kind": "date", "value": number, "unit": ""})
            continue
        atoms.append({"kind": "number", "value": number, "unit": ""})
    for match in re.finditer(rf"\b(?:19|20)\d{{2}}\b|\b(?:{MONTHS})\b", gold_text, re.I):
        atoms.append({"kind": "date", "value": match.group(0).lower(), "unit": ""})
    for word in entity_atoms(gold_text):
        atoms.append({"kind": "entity", "value": word.lower(), "unit": ""})
    seen = set()
    unique = []
    for atom in atoms:
        key = (atom["kind"], atom["value"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(atom)
    return unique


def entity_atoms(reference: str) -> list[str]:
    words = re.findall(r"\b[A-Z][a-zA-Z]{2,}\b", reference)
    return sorted({w for w in words if w.lower() not in SENTENCE_START})


def term_atoms(reference: str) -> list[str]:
    words = re.findall(r"\b[a-z]{5,}\b", norm(reference))
    return sorted({w for w in words if w not in STOP_WORDS})


def _content_tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z]{4,}", norm(text)) if t not in STOP_WORDS}


def relevant_atoms(gold_text: str, question: str, reference: str) -> list[dict[str, Any]]:
    """Atoms from the sentences of THIS memory that match question/reference.

    The global item-fact rate counts every number in a long session and does
    not predict verdicts (calibration, U4.1); the needed fact is the one in the
    question-matched sentence. This restricts the atoms to the best-matching
    sentence window (up to ~400 chars).
    """
    sentences = re.split(r"(?<=[.!?])\s+|\n+", gold_text)
    if not sentences:
        return []
    qtokens = _content_tokens(question)
    rtokens = _content_tokens(reference)
    scored = []
    for index, sentence in enumerate(sentences):
        tokens = _content_tokens(sentence)
        score = len(tokens & qtokens) * 2 + len(tokens & rtokens)
        scored.append((score, index))
    scored.sort(key=lambda item: (-item[0], item[1]))
    top = [index for score, index in scored[:2] if score > 0] or [0]
    window = " ".join(sentences[i] for i in sorted(top))[:400]
    atoms: list[dict[str, Any]] = []
    for match in re.finditer(r"\b(\d+(?:\.\d+)?)\s*%?", window):
        number = match.group(1)
        kind = "date" if len(number) == 4 and number[:2] in {"19", "20"} else "number"
        atoms.append({"kind": kind, "value": number, "unit": ""})
    for match in re.finditer(rf"\b(?:19|20)\d{{2}}\b|\b(?:{MONTHS})\b", window, re.I):
        atoms.append({"kind": "date", "value": match.group(0).lower(), "unit": ""})
    for word in entity_atoms(window):
        atoms.append({"kind": "entity", "value": word.lower(), "unit": ""})
    seen = set()
    unique = []
    for atom in atoms:
        key = (atom["kind"], atom["value"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(atom)
    return unique


def atom_present(atom: dict[str, Any], span_norm: str) -> bool:
    value = norm(atom["value"])
    if atom["kind"] == "interval":
        return value in span_norm
    if atom["kind"] == "entity":
        stem = value[:-1] if value.endswith("s") else value
        return stem in span_norm
    if not re.search(rf"(?<![\d.]){re.escape(value)}(?![\d])", span_norm):
        return False
    if atom["unit"]:
        unit = atom["unit"]
        singular = unit[:-1] if unit.endswith("s") else unit
        return singular in span_norm
    return True


def item_span(context: str, memory_id: str) -> tuple[str, bool]:
    match = re.search(rf"\[{memory_id}(?=[\s|\]])", context)
    if match is None:
        return "", False
    rest = context[match.start() :]
    end = rest.find("\n\n[")
    return (rest[:end] if end != -1 else rest), True


def main() -> None:
    summary_lines = ["# U4.1 — deterministic fact presence (pre-registered)", ""]
    for slice_name in SLICES:
        path = OUT / f"u_diag_{slice_name}.jsonl"
        if not path.exists():
            continue
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        per_arm: dict[str, Counter[str]] = defaultdict(Counter)
        results = []
        for row in rows:
            arms = row["arms"]
            if "graph_augment_precise" not in arms:
                continue
            gold_source = arms["graph_augment_precise"].get("gold") or []
            gold_texts = {g["memory_id"]: g.get("gold_text", "") for g in gold_source}
            required = list(row["required_ids"])
            question_class = (
                "composition" if COMPOSITION_RE.search(row["question"])
                else "single" if SINGLE_RE.search(row["question"]) else "other"
            )
            case_entry: dict[str, Any] = {
                "case": row["case"],
                "cat": row["cat"],
                "question_class": question_class,
                "required": required,
                "question": row["question"],
                "reference": row["gold"],
                "arms": {},
            }
            reference = str(row["gold"] or "")
            case_entry["reference"] = reference
            strong = strong_atoms(reference)
            entities = entity_atoms(reference)
            terms = term_atoms(reference)
            for arm, payload in arms.items():
                context = payload.get("context") or ""
                if not context:
                    continue
                item_flags = {}
                for memory_id in required:
                    span, delivered = item_span(context, memory_id)
                    span_norm = norm(span)
                    strong_hits = [atom_present(a, span_norm) for a in strong]
                    memory_text = gold_texts.get(memory_id, "")
                    item_atoms = relevant_atoms(memory_text, row["question"], reference)
                    item_hits = [atom_present(a, span_norm) for a in item_atoms]
                    all_atoms = item_fact_atoms(memory_text)
                    all_hits = [atom_present(a, span_norm) for a in all_atoms]
                    term_hits = [t in span_norm for t in terms]
                    item_flags[memory_id] = {
                        "delivered": delivered,
                        "strong": {
                            "total": len(strong),
                            "present": sum(strong_hits),
                            "atoms": [
                                {**atom, "present": hit}
                                for atom, hit in zip(strong, strong_hits)
                            ],
                        },
                        "item_facts": {
                            "total": len(item_atoms),
                            "present": sum(item_hits),
                            "atoms": [
                                {**atom, "present": hit}
                                for atom, hit in zip(item_atoms, item_hits)
                            ],
                        },
                        "item_facts_all": {
                            "total": len(all_atoms),
                            "present": sum(all_hits),
                        },
                        "term_present": sum(term_hits),
                    }
                    per_arm[arm]["strong_total"] += len(strong)
                    per_arm[arm]["strong_present"] += sum(strong_hits)
                    per_arm[arm]["item_total"] += len(item_atoms)
                    per_arm[arm]["item_present"] += sum(item_hits)
                    per_arm[arm]["gold_items"] += 1
                    per_arm[arm]["gold_delivered"] += int(delivered)
                all_strong = all(
                    flag["strong"]["total"] == flag["strong"]["present"]
                    for flag in item_flags.values()
                ) and bool(item_flags)
                all_items = all(
                    flag["item_facts"]["total"] == flag["item_facts"]["present"]
                    for flag in item_flags.values()
                ) and bool(item_flags)
                verdict = payload.get("verdict")
                per_arm[arm]["cases"] += 1
                per_arm[arm][f"class_{question_class}"] += 1
                per_arm[arm]["all_present"] += int(all_strong)
                per_arm[arm]["all_items"] += int(all_items)
                per_arm[arm]["correct"] += int(verdict == "correct")
                if verdict:
                    per_arm[arm]["verdicts"] += 1
                    if all_items and verdict != "correct":
                        per_arm[arm]["metric_present_but_wrong"] += 1
                    if not all_items and verdict == "correct":
                        per_arm[arm]["metric_absent_but_correct"] += 1
                case_entry["arms"][arm] = {
                    "verdict": verdict,
                    "all_strong_present": all_strong,
                    "all_item_facts_present": all_items,
                    "items": item_flags,
                }
            results.append(case_entry)
        out_path = OUT / f"fact_presence_{slice_name}.jsonl"
        with out_path.open("w", encoding="utf-8") as handle:
            for item in results:
                handle.write(json.dumps(item, ensure_ascii=False) + "\n")

        summary_lines += [f"## {slice_name} (n={len(results)})", "",
                          "| arm | item facts present | all-item-facts cases | ref atoms present | correct | item-FP | item-FN |",
                          "|---|---|---|---|---|---|---|"]
        for arm in sorted(per_arm):
            data = per_arm[arm]
            item_rate = (
                f"{data['item_present']}/{data['item_total']}"
                f" ({data['item_present']/data['item_total']:.2f})"
                if data["item_total"]
                else "-"
            )
            ref_rate = f"{data['strong_present']}/{data['strong_total']}" if data["strong_total"] else "-"
            summary_lines.append(
                f"| {arm} | {item_rate} | {data['all_items']}/{data['cases']} | {ref_rate} | "
                f"{data['correct']}/{data['cases']} | {data['metric_present_but_wrong']} | "
                f"{data['metric_absent_but_correct']} |"
            )
        by_class: dict[str, Counter[str]] = defaultdict(Counter)
        for entry in results:
            cls = entry["question_class"]
            for arm, data in entry["arms"].items():
                if not data.get("items"):
                    continue
                total = sum(f["item_facts"]["total"] for f in data["items"].values())
                present = sum(f["item_facts"]["present"] for f in data["items"].values())
                by_class[cls][f"{arm}_total"] += total
                by_class[cls][f"{arm}_present"] += present
        summary_lines.append("")
        summary_lines.append("### by question class (item-fact presence rate)")
        summary_lines.append("")
        summary_lines.append("| class | arm | rate |")
        summary_lines.append("|---|---|---|")
        for cls in sorted(by_class):
            for arm in sorted(per_arm):
                total = by_class[cls].get(f"{arm}_total", 0)
                present = by_class[cls].get(f"{arm}_present", 0)
                if total:
                    summary_lines.append(f"| {cls} | {arm} | {present}/{total} ({present/total:.2f}) |")

        # causal ledger for the window contender slices (precise -> arm)
        if any(slice_name.startswith("longmemeval_u3") for _ in [0]):
            pass
        summary_lines.append("")
        print(f"{slice_name}: wrote {out_path.name}")
        for arm in sorted(per_arm):
            data = per_arm[arm]
            print(
                f"  {arm:<24} item_facts={data['item_present']}/{data['item_total']} "
                f"all_items={data['all_items']}/{data['cases']} ref_atoms={data['strong_present']}/{data['strong_total']} "
                f"correct={data['correct']}/{data['cases']} FP={data['metric_present_but_wrong']} FN={data['metric_absent_but_correct']}"
            )
    (OUT / "fact_presence_summary.md").write_text("\n".join(summary_lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
