"""Shared test doubles."""

from __future__ import annotations

from typing import Any, Callable


class FakeClient:
    """LLM client double whose ``complete`` delegates to a handler."""

    def __init__(self, handler: Callable[[list[dict[str, str]], float], str]):
        self.handler = handler
        self.calls: list[list[dict[str, str]]] = []

    def complete(self, messages: list[dict[str, str]], *, temperature: float = 0.0) -> str:
        self.calls.append(messages)
        return self.handler(messages, temperature)


def text(messages: list[dict[str, str]], role: str) -> str:
    return "\n".join(m.get("content", "") for m in messages if m.get("role") == role)
