#!/usr/bin/env python3
r"""E0 — evidence cards instrument (deterministic, provenance-first).

Contract frozen before E1 (see docs/COMPOSITION_V1.md §E0):

- **Selection purity**: ``build_cards`` reads ONLY the question and the
  candidate memories' verbatim text. It must never read reference answers,
  gold atoms/spans or verdicts (guard 3). The caller decides which memories
  are candidates: E1 (ceiling) passes the gold memories by design; E2 (real
  arm) passes exactly the frozen ``payload_ids`` of the control arm.
- **Exact atoms**: every card text is an exact substring of the source field
  (``why``, fallback ``summary``) and carries reversible offsets
  ``(memory_id, field, start, end)`` — ``record[field][start:end] == text``
  (guard 2). Normalization or paraphrase is forbidden: the card renders the
  source bytes verbatim, offsets included.
- **Budget**: the whole rendered card block never exceeds ``CARD_BUDGET``
  (4000 chars, identical to the frozen payload baseline §12.5). Atoms are
  never truncated to fit: a card that does not fit is skipped.
- **Determinism**: pure function of ``(question, sources, constants)``; two
  runs are byte-identical.

Frozen rules v1 (any change after the E0 commit = new pre-registration):

  segmentation  payload._segments, verbatim substrings with recovered offsets
  scoring       score = |question_tokens ∩ segment_tokens| + 0.5 × has_fact
                (question/segment tokens via retrieval.tokenize: lowercase,
                len>2, stopwords removed; has_fact = number|date|interval)
  drop          segments with score ≤ 0
  ordering      memories in input order; segments by (-score, index)
  packing       round-robin passes over the memories, up to 3 segments each,
                first-fit by remaining budget, never truncating atoms
  render        "[M#### | field a:b] <verbatim text>" joined by newlines

Fact kinds (deterministic classifiers, used by scoring and reporting):

  number     \b\d+(?:[.,]\d+)?\s*%?            (1,000 -> one match)
  date       years (19|20)\d{2}, month names
  interval   \b\d+\s*(day|week|month|year)s?\b
  negation   not|no|never|without|n't contractions
  comparison more|less|fewer|higher|lower|increase(d)|decrease(d)|difference|
             between|before|after|than
  update     now|currently|updated|changed|used to|no longer|latest

Report (E0 evidence, no LLM):

    PYTHONPATH=src python3 eval/evidence_cards.py --report \
        --fixture eval/fixtures/composition_u4 \
        --out eval/results/composition_u4_e0
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "src"))

from memory_machine.payload import _segments  # noqa: E402
from memory_machine.retrieval import tokenize  # noqa: E402

CARD_BUDGET = 4000
FACT_BONUS = 0.5
MAX_SEGMENTS_PER_MEMORY = 3
SOURCE_FIELDS = ("why", "summary")

NUMBER_RE = re.compile(r"\b\d+(?:[.,]\d+)?\s*%?")
DATE_RE = re.compile(
    r"\b(?:19|20)\d{2}\b|\b(?:january|february|march|april|may|june|july|august|"
    r"september|october|november|december)\b",
    re.I,
)
INTERVAL_RE = re.compile(r"\b\d+\s*(?:day|week|month|year)s?\b", re.I)
NEGATION_RE = re.compile(r"\b(?:not|no|never|without)\b|\b\w+n['’]t\b", re.I)
COMPARISON_RE = re.compile(
    r"\b(?:more|less|fewer|higher|lower|increased?|decreased?|difference|between|"
    r"before|after|than)\b",
    re.I,
)
UPDATE_RE = re.compile(
    r"\b(?:now|currently|updated?|changed|used to|no longer|latest)\b", re.I
)

FACT_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("number", NUMBER_RE),
    ("date", DATE_RE),
    ("interval", INTERVAL_RE),
    ("negation", NEGATION_RE),
    ("comparison", COMPARISON_RE),
    ("update", UPDATE_RE),
)


def fact_kinds(text: str) -> set[str]:
    return {name for name, pattern in FACT_PATTERNS if pattern.search(text)}


def has_hard_fact(text: str) -> bool:
    """number|date|interval — the frozen scoring bonus, never negation etc."""
    return bool(NUMBER_RE.search(text) or DATE_RE.search(text) or INTERVAL_RE.search(text))


def canonical_source(record: dict[str, Any]) -> tuple[str, str]:
    """The verbatim source field of a record: ``why`` when present, else ``summary``."""
    why = str(record.get("why") or "")
    if why:
        return "why", why
    return "summary", str(record.get("summary") or "")


def segments_with_spans(text: str) -> list[tuple[int, int, str]]:
    """Segments as verbatim substrings with recovered offsets (sequential find).

    ``_segments`` only trims/splits the source, so every part is an exact
    substring; the sequential scan keeps offsets monotonic.
    """
    out: list[tuple[int, int, str]] = []
    pos = 0
    for seg in _segments(text):
        start = text.find(seg, pos)
        if start < 0:  # cannot happen for a split of this very text
            continue
        end = start + len(seg)
        out.append((start, end, seg))
        pos = end
    return out


@dataclass(frozen=True)
class EvidenceAtom:
    """One verbatim fragment with reversible offsets."""

    memory_id: str
    field: str
    start: int
    end: int
    text: str
    fact_kinds: tuple[str, ...] = ()
    score: float = 0.0

    def header(self) -> str:
        return f"[{self.memory_id} | {self.field} {self.start}:{self.end}]"

    def render(self) -> str:
        return f"{self.header()} {self.text}"


# Backwards-friendly alias: in E0/E1/E2 every card carries exactly one atom
# (the atom *is* the card); multi-atom cards only appear in E3.
EvidenceCard = EvidenceAtom


def decode_card(card: EvidenceAtom) -> tuple[str, str, int, int]:
    return card.memory_id, card.field, card.start, card.end


def validate_card(card: EvidenceAtom, text: str) -> bool:
    """Offsets reversible and text exact; else provenance is invalid."""
    return 0 <= card.start < card.end <= len(text) and text[card.start : card.end] == card.text


def _score_segment(question_tokens: set[str], segment: str) -> float:
    seg_tokens = set(tokenize(segment))
    score = float(len(question_tokens & seg_tokens))
    if has_hard_fact(segment):
        score += FACT_BONUS
    return score


def build_cards(
    question: str,
    sources: Sequence[tuple[str, str, str]],
    *,
    budget: int = CARD_BUDGET,
    max_segments_per_memory: int = MAX_SEGMENTS_PER_MEMORY,
) -> list[EvidenceCard]:
    """Deterministic cards over ``sources`` = [(memory_id, field, text)].

    Selection purity (guard 3): the only inputs are the question and the
    candidate texts, in caller-provided order.
    """
    qtokens = set(tokenize(question))
    per_memory: list[list[EvidenceAtom]] = []
    for memory_id, field, text in sources:
        ranked: list[EvidenceAtom] = []
        for start, end, seg in segments_with_spans(text):
            score = _score_segment(qtokens, seg)
            if score <= 0:
                continue
            ranked.append(
                EvidenceAtom(
                    memory_id=memory_id,
                    field=field,
                    start=start,
                    end=end,
                    text=seg,
                    fact_kinds=tuple(sorted(fact_kinds(seg))),
                    score=score,
                )
            )
        ranked.sort(key=lambda a: (-a.score, a.start))
        per_memory.append(ranked[:max_segments_per_memory])

    cards: list[EvidenceCard] = []
    used = 0
    for pass_index in range(max_segments_per_memory):
        for ranked in per_memory:
            if pass_index >= len(ranked):
                continue
            card = ranked[pass_index]
            add = len(card.render()) + (1 if cards else 0)
            if used + add > budget:
                continue
            cards.append(card)
            used += add
    return cards


def render_cards(cards: Iterable[EvidenceCard]) -> str:
    return "\n".join(card.render() for card in cards)


def cards_sha1(cards: Iterable[EvidenceCard]) -> str:
    blob = render_cards(cards).encode("utf-8")
    return hashlib.sha1(blob).hexdigest()


# ---------------------------------------------------------------------------
# E0 report — no LLM, no outcome knowledge


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


def _sources_for(
    ids: Sequence[str], records: dict[tuple[int, str], dict[str, Any]], case: int
) -> list[tuple[str, str, str]]:
    out = []
    for memory_id in ids:
        record = records.get((case, memory_id))
        if record is None:
            raise KeyError(f"case {case}: record {memory_id} missing from fixture")
        field, text = canonical_source(record)
        out.append((memory_id, field, text))
    return out


def report(fixtures: Path, out_dir: Path | None) -> dict[str, Any]:
    cases, records = load_fixture(fixtures)
    manifest = json.loads((fixtures / "manifest.json").read_text(encoding="utf-8"))
    result: dict[str, Any] = {
        "fixture": str(fixtures),
        "fixture_manifest_sha1": manifest.get("sha1"),
        "cases": len(cases),
        "records": len(records),
        "budget": CARD_BUDGET,
        "modes": {},
    }
    for mode, key in (("gold", "required_ids"), ("payloads", "payload_ids")):
        per_case = []
        no_cards: list[int] = []
        validation_failures: list[str] = []
        total_cards = 0
        total_chars = 0
        chars_max = 0
        no_card_memories = 0
        fact_hist: dict[str, int] = {}
        for case in cases:
            ids = list(case[key])
            sources = _sources_for(ids, records, case["case"])
            texts = {memory_id: text for memory_id, _field, text in sources}
            cards = build_cards(case["question"], sources)
            cards_again = build_cards(case["question"], sources)
            if cards_sha1(cards) != cards_sha1(cards_again):
                validation_failures.append(f"case {case['case']}: nondeterministic build")
            for card in cards:
                if not validate_card(card, texts[card.memory_id]):
                    validation_failures.append(
                        f"case {case['case']}: invalid span {card.memory_id} "
                        f"{card.field} {card.start}:{card.end}"
                    )
                for kind in card.fact_kinds:
                    fact_hist[kind] = fact_hist.get(kind, 0) + 1
            chars = len(render_cards(cards))
            covered = {card.memory_id for card in cards}
            missing = [memory_id for memory_id in ids if memory_id not in covered]
            no_card_memories += len(missing)
            if not cards:
                no_cards.append(case["case"])
            if chars > CARD_BUDGET:
                validation_failures.append(f"case {case['case']}: budget exceeded ({chars})")
            total_cards += len(cards)
            total_chars += chars
            chars_max = max(chars_max, chars)
            per_case.append(
                {
                    "case": case["case"],
                    "block": case["block"],
                    "cat": case["cat"],
                    "candidates": len(ids),
                    "cards": len(cards),
                    "chars": chars,
                    "sha1": cards_sha1(cards),
                    "fact_kinds": sorted(
                        {k for card in cards for k in card.fact_kinds}
                    ),
                    "card_ids": [card.memory_id for card in cards],
                    "ids_no_cards": missing,
                }
            )
        result["modes"][mode] = {
            "cases": len(cases),
            "cards": total_cards,
            "cards_avg": round(total_cards / len(cases), 2),
            "chars_total": total_chars,
            "chars_avg": round(total_chars / len(cases)),
            "chars_max": chars_max,
            "memories_no_cards": no_card_memories,
            "fact_kinds": dict(sorted(fact_hist.items())),
            "no_cards_cases": no_cards,
            "validation_failures": validation_failures,
            "validation_ok": not validation_failures,
            "deterministic": not any("nondeterministic" in f for f in validation_failures),
            "per_case_sha1": {row["case"]: row["sha1"] for row in per_case},
            "per_case": per_case,
        }
    if out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "e0_report.json").write_text(
            json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    return result


def print_report(result: dict[str, Any]) -> None:
    print(f"fixture: {result['fixture']} (manifest sha1 {result['fixture_manifest_sha1']})")
    print(f"cases: {result['cases']} | records: {result['records']} | budget: {result['budget']}")
    for mode, data in result["modes"].items():
        print(f"\n== mode: {mode} ==")
        print(f"  cards: {data['cards']} ({data['cards_avg']}/case) | "
              f"chars: {data['chars_total']} ({data['chars_avg']}/case, max {data['chars_max']})")
        print(f"  fact kinds: {data['fact_kinds']}")
        print(f"  memories without cards: {data['memories_no_cards']}")
        print(f"  no-card cases ({len(data['no_cards_cases'])}): {data['no_cards_cases']}")
        print(f"  provenance 100%: {data['validation_ok']} | deterministic: {data['deterministic']}")
        if data["validation_failures"]:
            for failure in data["validation_failures"]:
                print(f"    FAIL {failure}")


def self_check() -> int:
    text = (
        "user: I upgraded my laptop's RAM to 16GB in March.\n"
        "assistant: Nice, that is a solid boost.\n"
        "user: The battery life got worse after the update.\n"
    )
    sources = [("M0001", "why", text)]
    question = "How much RAM did I upgrade my laptop to?"
    cards = build_cards(question, sources)
    assert cards, "self-check expected at least one card"
    for card in cards:
        assert validate_card(card, text), "self-check: invalid span"
        assert decode_card(card) == (card.memory_id, card.field, card.start, card.end)
    repeat = build_cards(question, sources)
    assert cards_sha1(cards) == cards_sha1(repeat), "self-check: nondeterministic"
    assert len(render_cards(cards)) <= CARD_BUDGET, "self-check: budget"
    assert any("number" in c.fact_kinds for c in cards), "self-check: expected number atom"
    print(f"self-check ok: {len(cards)} cards, sha1 {cards_sha1(cards)}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="E0 evidence cards instrument")
    parser.add_argument("--self-check", action="store_true")
    parser.add_argument("--report", action="store_true")
    parser.add_argument("--fixture", default="eval/fixtures/composition_u4")
    parser.add_argument("--out", default="")
    args = parser.parse_args()
    if args.self_check:
        return self_check()
    if args.report:
        result = report(Path(args.fixture), Path(args.out) if args.out else None)
        print_report(result)
        return 0 if all(
            data["validation_ok"] and data["deterministic"]
            for data in result["modes"].values()
        ) else 1
    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
