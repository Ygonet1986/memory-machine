"""The shared whiteboard: working memory representing the current work.

The whiteboard is a bounded, human-readable state object. Memory agents read
it to judge which of their memories are relevant; the main chatbot consumes it
(plus the annotations agents wrote) to continue the task. It does not replace
the tape — it is only the working view of the present moment.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class Annotation:
    memory_id: str
    note: str
    relevance: float = 0.0
    agent_id: str = ""
    ts: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Annotation":
        return cls(
            memory_id=str(data.get("memory_id") or ""),
            note=str(data.get("note") or ""),
            relevance=float(data.get("relevance") or 0.0),
            agent_id=str(data.get("agent_id") or ""),
            ts=str(data.get("ts") or ""),
        )


@dataclass
class Whiteboard:
    subject: str = ""
    objective: str = ""
    metacognition: str = ""
    checklist: str = ""
    context: list[str] = field(default_factory=list)
    pending: list[str] = field(default_factory=list)
    annotations: list[Annotation] = field(default_factory=list)
    consolidated_from: str = ""
    updated_at: str = ""
    boards: dict[str, "Whiteboard"] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "subject": self.subject,
            "objective": self.objective,
            "metacognition": self.metacognition,
            "checklist": self.checklist,
            "context": self.context,
            "pending": self.pending,
            "annotations": [a.to_dict() for a in self.annotations],
            "consolidated_from": self.consolidated_from,
            "updated_at": self.updated_at,
            "boards": {name: board.to_dict() for name, board in self.boards.items()},
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Whiteboard":
        return cls(
            subject=str(data.get("subject") or ""),
            objective=str(data.get("objective") or ""),
            metacognition=str(data.get("metacognition") or ""),
            checklist=str(data.get("checklist") or ""),
            context=list(data.get("context") or []),
            pending=list(data.get("pending") or []),
            annotations=[Annotation.from_dict(a) for a in (data.get("annotations") or [])],
            consolidated_from=str(data.get("consolidated_from") or ""),
            updated_at=str(data.get("updated_at") or ""),
            boards={
                str(name): cls.from_dict(board)
                for name, board in (data.get("boards") or {}).items()
            },
        )

    def touch(self) -> None:
        self.updated_at = datetime.now(timezone.utc).isoformat()

    def for_dimension(self, dimension: str) -> "Whiteboard":
        """Return (creating if needed) the working board of a dimension.

        Dimension boards inherit the session subject/objective when created,
        then keep their own understanding, checklist and annotations — so each
        dimension maintains a different working memory of the same work.
        """
        board = self.boards.get(dimension)
        if board is None:
            board = Whiteboard(subject=self.subject, objective=self.objective)
            self.boards[dimension] = board
        return board

    def active_boards(self, dimensions: list[str]) -> dict[str, "Whiteboard"]:
        return {d: self.boards[d] for d in dimensions if d in self.boards}

    def render_boards(self, dimensions: list[str] | None = None) -> str:
        """Render the requested dimension boards, each under its own header."""
        names = dimensions if dimensions is not None else list(self.boards)
        parts: list[str] = []
        for name in names:
            board = self.boards.get(name)
            if board is None:
                continue
            parts.append(f"## {name}\n{board.render()}")
        return "\n\n".join(parts)

    def render(self, *, include_annotations: bool = True) -> str:
        """Human-readable representation of the whiteboard."""
        lines: list[str] = []
        if self.subject:
            lines.append(f"Subject: {self.subject}")
        if self.objective:
            lines.append(f"Objective: {self.objective}")
        if self.metacognition:
            lines.append(f"Understanding: {self.metacognition}")
        if self.checklist:
            lines.append("Checklist (must remember):")
            lines.append(self.checklist)
        if self.context:
            lines.append("Context:")
            lines.extend(f"- {c}" for c in self.context)
        if self.pending:
            lines.append("Pending:")
            lines.extend(f"- {p}" for p in self.pending)
        if include_annotations and self.annotations:
            lines.append("Remembered (from memory agents):")
            for a in self.annotations:
                lines.append(f"- {a.memory_id} ({a.relevance:.2f}): {a.note}")
        if self.consolidated_from:
            lines.append(f"(consolidated from {self.consolidated_from})")
        return "\n".join(lines) if lines else "(empty whiteboard)"


def load_whiteboard(path: Path) -> Whiteboard:
    if path.exists():
        try:
            return Whiteboard.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            pass
    return Whiteboard()


def save_whiteboard(whiteboard: Whiteboard, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    whiteboard.touch()
    path.write_text(json.dumps(whiteboard.to_dict(), indent=2) + "\n", encoding="utf-8")


def size_chars(whiteboard: Whiteboard) -> int:
    """Approximate serialized size used to trigger consolidation.

    Dimension boards are excluded: they are bounded by the annotation budget
    and must not force the primary board to consolidate on every turn.
    """
    data = whiteboard.to_dict()
    data.pop("boards", None)
    return len(json.dumps(data))


def needs_consolidation(whiteboard: Whiteboard, threshold: int) -> bool:
    return size_chars(whiteboard) > threshold


def _annotation_cost(a: Annotation) -> int:
    return max(len(a.note) + len(a.memory_id) + 20, 40)


def merge_annotations(
    whiteboard: Whiteboard,
    annotations: list[Annotation],
    *,
    budget: int,
) -> list[Annotation]:
    """Merge new annotations into the whiteboard, deduping by memory id.

    Keeps the highest-relevance annotation per memory id, ranks by relevance,
    and trims to ``budget`` chars. Returns the annotations that fit the budget.
    The whiteboard's ``annotations`` list is updated in place to the merged set.
    """
    by_id: dict[str, Annotation] = {a.memory_id: a for a in whiteboard.annotations}
    for a in annotations:
        if not a.memory_id or not a.note:
            continue
        cur = by_id.get(a.memory_id)
        if cur is None or a.relevance > cur.relevance:
            by_id[a.memory_id] = a

    ranked = sorted(by_id.values(), key=lambda a: (-a.relevance, a.memory_id))

    kept: list[Annotation] = []
    used = 0
    for a in ranked:
        cost = _annotation_cost(a)
        if kept and used + cost > budget:
            break
        kept.append(a)
        used += cost

    whiteboard.annotations = kept
    return kept
