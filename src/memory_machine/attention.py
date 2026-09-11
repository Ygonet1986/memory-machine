"""Persistent attention state: a recency-weighted structural prior over views.

Attention is session/working memory (``Whiteboard.attention``), not stable
knowledge about a view: it says where the conversation is looking right now.
Weights are global and independent in ``[0, 1]`` (they are strengths, not a
probability distribution), decayed by neglect and reinforced by use and by
finding evidence.

The prior lets a follow-up turn ("and why did we change that?") keep looking at
the previously active regions without rediscovering them from scratch, while
the decay keeps attention from sticking after a topic change.
"""

from __future__ import annotations

import re
from typing import Any

# Pronoun/demonstrative markers of an anaphoric follow-up.
ANAPHORA_WORDS = {
    "isso", "isto", "aquilo", "ele", "ela", "eles", "elas", "esse", "essa",
    "este", "esta", "aquele", "aquela", "mesmo", "mesma", "it", "that",
    "this", "those", "these", "them", "they", "there", "which",
}


def decay_reinforce(
    weights: dict[str, float],
    selected: list[str] | set[str] | tuple[str, ...] = (),
    found: list[str] | set[str] | tuple[str, ...] = (),
    *,
    decay: float = 0.6,
    boost: float = 0.8,
    found_boost: float = 0.3,
) -> dict[str, float]:
    """Decay every weight, then reinforce selected and found views.

    Reinforcement saturates (``+= boost * (1 - w)``), so an already active view
    grows less than a cold one, and every weight is clamped to ``[0, 1]``.
    """
    out = {view: min(1.0, max(0.0, w * decay)) for view, w in weights.items()}
    for view in dict.fromkeys(selected):
        out[view] = min(1.0, out.get(view, 0.0) + boost * (1.0 - out.get(view, 0.0)))
    for view in dict.fromkeys(found):
        out[view] = min(1.0, out.get(view, 0.0) + found_boost * (1.0 - out.get(view, 0.0)))
    return out


def normalize(scores: dict[str, float]) -> dict[str, float]:
    """Divide by the top score so router scores are comparable across turns."""
    top = max(scores.values()) if scores else 0.0
    if top <= 0:
        return {view: 0.0 for view in scores}
    return {view: score / top for view, score in scores.items()}


def blend(
    router_scores: dict[str, float],
    attention: dict[str, float],
    weight: float,
) -> dict[str, float]:
    """Final score = normalized router score + weight * attention."""
    router_norm = normalize(router_scores)
    views = set(router_norm) | set(attention)
    return {
        view: router_norm.get(view, 0.0) + weight * attention.get(view, 0.0)
        for view in views
    }


def is_anaphoric(query: str, *, view_names: tuple[str, ...] | list[str] = ()) -> bool:
    """A short/pronoun query that does not point at any view by itself."""
    q = (query or "").lower()
    tokens = [t for t in re.findall(r"[a-zà-ÿ0-9_]+", q) if len(t) > 1]
    if not tokens:
        return False
    if not any(t in ANAPHORA_WORDS for t in tokens):
        return False
    view_words: set[str] = set()
    for view in view_names:
        view_words |= set(re.split(r"[/_\-]", view.lower()))
    return not (set(tokens) & view_words)


def confidence(weights: dict[str, float]) -> tuple[float, float]:
    """Return ``(top1, margin)`` of the attention distribution."""
    values = sorted((w for w in weights.values() if w > 0), reverse=True)
    if not values:
        return 0.0, 0.0
    top1 = values[0]
    margin = top1 - (values[1] if len(values) > 1 else 0.0)
    return top1, margin


def classify(
    router_score: float,
    attention_score: float,
    *,
    attention_min: float = 0.05,
) -> str:
    """Why a view was selected: ``router`` | ``attention`` | ``both`` | ``none``."""
    router_signal = router_score > 0
    attention_signal = attention_score >= attention_min
    if router_signal and attention_signal:
        return "both"
    if router_signal:
        return "router"
    if attention_signal:
        return "attention"
    return "none"


def contribution_summary(view_scores: dict[str, dict[str, Any]]) -> dict[str, int]:
    """Count selected views by contribution kind (for the benchmark)."""
    out = {"router": 0, "attention": 0, "both": 0, "none": 0}
    for scores in view_scores.values():
        kind = str(scores.get("contribution") or "none")
        out[kind] = out.get(kind, 0) + 1
    return out
