"""Metacognitive layer: keep an up-to-date understanding and a checklist.

The whiteboard carries two metacognitive artifacts, refreshed after every turn:

- ``metacognition`` — what the subject is about, what is happening now, key
  facts and open items;
- ``checklist`` — a dynamic list of the things the assistant must NOT forget
  (decisions, constraints, open items), refined each turn.

Both are produced by a single metacognitive LLM call (with a deterministic
fallback) so the assistant always starts each turn already oriented.
"""

from __future__ import annotations

from typing import Any

from .llm import extract_json_object
from .whiteboard import Whiteboard

MAX_CHARS = 800
MAX_CHECKLIST_CHARS = 800

METACOGNITION_PROMPT = """You are the metacognitive layer of a long-running \
assistant. Maintain a short, up-to-date understanding of the current work AND \
a checklist of the things the assistant must not forget.

Update using: the previous understanding, the previous checklist, the current \
subject, and the latest exchange (the user's task and the assistant's reply).

Return ONLY a JSON object, nothing else:
{{"understanding":"...","checklist":["...","..."]}}

- "understanding": what the subject is about, what is happening now, key \
  settled facts, and open items (concise, at most ~120 words).
- "checklist": a short list of the things the assistant must NOT forget \
  (decisions, constraints, open items). Refine it dynamically each turn: drop \
  what no longer matters, keep and sharpen what still does, add what is new.
Do not invent facts beyond what is given."""


def _deterministic(subject: str, reply: str, max_chars: int) -> str:
    parts: list[str] = []
    if subject:
        parts.append(f"Subject: {subject}")
    if reply:
        parts.append(f"Latest: {reply[:400]}")
    return " | ".join(parts)[:max_chars]


def update_metacognition(
    whiteboard: Whiteboard,
    client: Any,
    *,
    task: str = "",
    reply: str = "",
    subject: str = "",
    temperature: float = 0.0,
    max_chars: int = MAX_CHARS,
) -> str:
    """Refresh ``whiteboard.metacognition`` and ``whiteboard.checklist``.

    Falls back to a deterministic summary when ``client`` is None or fails, so
    the metacognitive update never breaks the run.
    """
    subject = subject or whiteboard.subject
    prev_understanding = whiteboard.metacognition
    prev_checklist = whiteboard.checklist

    understanding = whiteboard.metacognition
    checklist = whiteboard.checklist

    if client is not None:
        user = (
            f"Previous understanding: {prev_understanding or '(none)'}\n"
            f"Previous checklist: {prev_checklist or '(none)'}\n"
            f"Subject: {subject or '(none)'}\n"
            f"Task: {task}\n"
            f"Reply: {reply[:1500]}"
        )
        messages = [
            {"role": "system", "content": METACOGNITION_PROMPT},
            {"role": "user", "content": user},
        ]
        try:
            content = client.complete(messages, temperature=temperature)
            obj = extract_json_object(content)
            if isinstance(obj.get("understanding"), str) and obj["understanding"].strip():
                understanding = obj["understanding"].strip()
            cl = obj.get("checklist")
            if isinstance(cl, list):
                checklist = "\n".join(f"- {str(x).strip()}" for x in cl if str(x).strip())
            elif isinstance(cl, str) and cl.strip():
                checklist = cl.strip()
        except Exception:
            pass

    if not understanding:
        understanding = _deterministic(subject, reply, max_chars)

    whiteboard.metacognition = understanding[:max_chars]
    whiteboard.checklist = checklist[:MAX_CHECKLIST_CHARS]
    whiteboard.touch()
    return whiteboard.metacognition
