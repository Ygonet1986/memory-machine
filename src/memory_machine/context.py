"""The main chatbot's own conversation context and its consolidation.

The main chatbot keeps a bounded conversation context (past tasks and replies).
This context is consolidated on its own schedule — independently of the
whiteboard — whenever it approaches its budget. Consolidation summarizes the
accumulated turns into a compact narrative so the chatbot can keep working
without carrying the whole history in a single context.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_MAX_SUMMARY = 4000
ANSWERER_TURN_CAP = 320
ANSWERER_WHITEBOARD_FLOOR = 800

CONTEXT_CONSOLIDATOR_PROMPT = """You are the context consolidator for the main \
assistant. Below is the assistant's recent conversation history with a user \
working on a long-running project. Summarize it into a compact narrative that \
preserves: the goals, the decisions made, the lessons learned, and any open \
items. Be terse and structured. Do not invent facts.

History:

{history}"""


@dataclass
class Turn:
    task: str
    reply: str
    subject: str = ""
    ts: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Turn":
        return cls(
            task=str(data.get("task") or ""),
            reply=str(data.get("reply") or ""),
            subject=str(data.get("subject") or ""),
            ts=str(data.get("ts") or ""),
        )

    def render(self) -> str:
        return f"Task: {self.task}\nReply: {self.reply}"


@dataclass
class ChatContext:
    summary: str = ""
    turns: list[Turn] = field(default_factory=list)
    consolidated_from: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "turns": [t.to_dict() for t in self.turns],
            "consolidated_from": self.consolidated_from,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ChatContext":
        return cls(
            summary=str(data.get("summary") or ""),
            turns=[Turn.from_dict(t) for t in (data.get("turns") or [])],
            consolidated_from=str(data.get("consolidated_from") or ""),
        )

    def render(self) -> str:
        parts: list[str] = []
        if self.summary:
            parts.append("## Prior context (consolidated)\n" + self.summary)
        for t in self.turns:
            parts.append(t.render())
        return "\n\n".join(parts) if parts else ""

    def turns_chars(self) -> int:
        return sum(len(t.render()) + 2 for t in self.turns)

    def total_chars(self) -> int:
        return len(self.summary) + self.turns_chars()

    def render_recent(self, limit: int = 10, *,
                      turn_cap: int = ANSWERER_TURN_CAP,
                      max_chars: int = 0) -> str:
        """The answerer's conversation block: summary + the last ``limit`` turns.

        Each side of a turn is trimmed to ``turn_cap`` characters; when
        ``max_chars`` is set the block keeps its most recent tail.
        """
        if limit <= 0:
            return ""
        parts: list[str] = []
        if self.summary:
            parts.append("## Prior context (consolidated)\n" + self.summary)
        for turn in self.turns[-limit:]:
            task = " ".join(turn.task.split())
            reply = " ".join(turn.reply.split())
            if turn_cap > 0:
                if len(task) > turn_cap:
                    task = task[: turn_cap - 1] + "…"
                if len(reply) > turn_cap:
                    reply = reply[: turn_cap - 1] + "…"
            parts.append(f"Task: {task}\nReply: {reply}")
        block = "\n\n".join(parts)
        if max_chars > 0 and len(block) > max_chars:
            block = "…" + block[-(max_chars - 1):]
        return block


def split_answerer_budget(total: int, history_chars: int, *,
                          floor: int = ANSWERER_WHITEBOARD_FLOOR
                          ) -> tuple[int, int]:
    """Return ``(history_cap, whiteboard_budget)`` for the answerer context.

    The conversation block has priority inside ``total``; the whiteboard fills
    whatever remains, never below ``floor`` (or ``total`` when it is smaller).
    """
    total = max(0, int(total))
    floor = min(max(0, int(floor)), total)
    history_cap = max(0, total - floor)
    whiteboard = max(floor, total - max(0, int(history_chars)))
    return history_cap, whiteboard


def load_context(path: Path) -> ChatContext:
    if path.exists():
        try:
            return ChatContext.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            pass
    return ChatContext()


def save_context(context: ChatContext, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(context.to_dict(), indent=2) + "\n", encoding="utf-8")


def append_turn(context: ChatContext, task: str, reply: str, subject: str = "") -> None:
    context.turns.append(
        Turn(
            task=task,
            reply=reply,
            subject=subject,
            ts=datetime.now(timezone.utc).isoformat(),
        )
    )


def needs_consolidation(context: ChatContext, threshold: int) -> bool:
    return context.turns_chars() > threshold


def _history_dump(context: ChatContext) -> str:
    return "\n\n".join(t.render() for t in context.turns)


def _merge(summary: str, narrative: str, max_summary: int) -> str:
    merged = (summary + "\n\n" + narrative).strip() if summary else narrative.strip()
    return merged[-max_summary:]


def consolidate_context(
    context: ChatContext,
    *,
    client: Any = None,
    max_summary: int = DEFAULT_MAX_SUMMARY,
    temperature: float = 0.0,
) -> dict[str, Any]:
    """Fold recent turns into the summary, clearing them. Returns a summary dict."""
    history = _history_dump(context)
    if not history:
        return {"ok": True, "summary": context.summary, "consolidated": False}

    if client is not None:
        messages = [
            {"role": "system", "content": CONTEXT_CONSOLIDATOR_PROMPT},
            {"role": "user", "content": history},
        ]
        narrative = client.complete(messages, temperature=temperature).strip()
    else:
        narrative = history

    context.summary = _merge(context.summary, narrative, max_summary)
    context.turns = []
    context.consolidated_from = datetime.now(timezone.utc).isoformat()
    return {"ok": True, "summary": context.summary, "consolidated": True}
