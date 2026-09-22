"""N8 conformance: exact-span evidence cards, inside the pytest suite/CI.

Covers the normative invariant "spans exatos com offsets reversíveis" of
docs/NORMATIVE_SPEC_V1.md (N8) and the E0 card rules: exact substring, budget
bound, determinism, and the provenance rejection of paraphrase.
"""

from __future__ import annotations

import sys
from pathlib import Path


EVAL = Path(__file__).resolve().parents[1] / "eval"
if str(EVAL) not in sys.path:
    sys.path.insert(0, str(EVAL))

from evidence_cards import (  # noqa: E402
    CARD_BUDGET,
    build_cards,
    cards_sha1,
    decode_card,
    render_cards,
    validate_card,
)

TEXT = (
    "Alpha beta gamma. The value is 42. The user reported the value changed.\n\n"
    "A second paragraph mentions that the measurement used a thermometer.\n"
)


def _sources():
    return [("M0001", "why", TEXT)]


def test_atoms_are_exact_substrings_with_reversible_offsets():
    cards = build_cards("value changed", _sources())
    assert cards
    for card in cards:
        assert validate_card(card, TEXT)
        memory_id, field, start, end = decode_card(card)
        assert (memory_id, field) == ("M0001", "why")
        assert TEXT[start:end] == card.text
        assert card.header() == f"[M0001 | why {start}:{end}]"


def test_paraphrase_or_wrong_offsets_invalidate_provenance():
    card = build_cards("value changed", _sources())[0]
    assert not validate_card(card, TEXT.replace("42", "forty-two"))
    broken = type(card)(
        memory_id=card.memory_id, field=card.field, start=card.start,
        end=card.end + 1, text=card.text, fact_kinds=card.fact_kinds,
        score=card.score,
    )
    assert not validate_card(broken, TEXT)


def test_budget_is_respected_including_headers():
    long_text = " ".join(f"Sentence {i} value {i}." for i in range(400))
    cards = build_cards("value", [("M0001", "why", long_text)])
    rendered = render_cards(cards)
    assert len(rendered) <= CARD_BUDGET


def test_cards_are_deterministic():
    first = build_cards("value changed", _sources())
    second = build_cards("value changed", _sources())
    assert cards_sha1(first) == cards_sha1(second)


def test_no_scoring_segment_yields_no_card():
    plain = "Alpha beta gamma delta."
    cards = build_cards("quantum chromodynamics", [("M0001", "why", plain)])
    assert cards == []
