"""The main chatbot: consumes the whiteboard and continues the task.

The main chatbot is the consumer of working memory. It reads the whiteboard
(subject, objective, context, pending and the agents' annotations) and
produces the next step of the work. Durable facts it produces are returned as
structured memories for the coordinator to append to the tape.
"""

from __future__ import annotations

import json
import re
from typing import Any

from .llm import extract_json_object
from .tape import MemoryRecord
from .whiteboard import Whiteboard

MAIN_SYSTEM_PROMPT = """You are the main assistant working on a long-running project. \
You are given a whiteboard representing the current work: the subject, the \
objective, the context, pending items, and "Remembered" notes contributed by \
memory agents.

Use the remembered information to continue the task accurately. Do not ignore \
relevant memories; do not contradict a settled decision unless the new work \
clearly supersedes it.

You MAY also receive external context (relevant documents and web search \
results). Use it to answer accurately, but it is NOT part of long-term memory: \
do not treat it as a settled decision unless you explicitly turn a durable \
fact into a memory.

After your reply, if you produced durable facts worth remembering (a decision, \
lesson, preference, bugfix, or build note), append a JSON block on its own line:

{"memories":[{"type":"decision","summary":"...","why":"...","files":["..."]}]}

If nothing durable was produced, omit the JSON entirely. Never include API \
keys or secrets."""

MEMORIES_RE = re.compile(r'\{\s*"memories"\s*:\s*', re.S)


TEMPORAL_SECTION = """## Temporal computation

Before answering, resolve the question's time reference explicitly:

1. List the relevant timestamps and the memory each one comes from.
2. Resolve relative expressions spoken inside a memory ("today", "yesterday", "a week ago") against THAT memory's session timestamp.
3. Use the question date (given in the task) as "now".
4. Compute the interval or ordering step by step.
5. Verify the computation, then answer with the result."""


MAIN_SYSTEM_PROMPT_MEMORY = """You are the main assistant working on a long-running project. \
You are given a whiteboard representing the current work: the subject, the \
objective, the context, pending items, and "Remembered" notes contributed by \
memory agents.

Use the remembered information to continue the task accurately. Do not ignore \
relevant memories; do not contradict a settled decision unless the new work \
clearly supersedes it.

You may also receive "Recalled memory evidence": factual excerpts recovered \
from the user's persistent memory. Treat it as records of the conversation's \
history, including for questions about past events, decisions, states and \
facts. Use the date and provenance in each item to distinguish past state from \
current state. When the question asks about the past, do not discard a memory \
just because it describes an earlier state, and do not assume that a more \
recent memory supersedes an older one.

You MAY also receive external context (relevant documents and web search \
results). Use it to answer accurately, but it is NOT part of long-term memory: \
do not treat it as a settled decision unless you explicitly turn a durable \
fact into a memory.

After your reply, if you produced durable facts worth remembering (a decision, \
lesson, preference, bugfix, or build note), append a JSON block on its own line:

{"memories":[{"type":"decision","summary":"...","why":"...","files":["..."]}]}

If nothing durable was produced, omit the JSON entirely. Never include API \
keys or secrets."""


OBSERVER_SYSTEM = """\
You are the conversation observer of a long-running assistant. You never
answer the user. You keep the conversation's understanding: what is being
worked on, what was decided, open threads, corrections and what the next
answer must respect. Keep the understanding compact (<= 1200 characters) and
give short, concrete guidance for the answerer.

Return ONLY a JSON object:
{"understanding": "<compact state of the conversation>", "guidance": ["...", "..."]}
"""


def observer_pass(client: Any, whiteboard: Whiteboard, conversation: str,
                  task: str, previous_understanding: str = "", *,
                  temperature: float = 0.0) -> tuple[str, list[str]]:
    """One observer call: refresh the conversation understanding + guidance."""
    prompt = (
        "[Understanding atual]\n" + (previous_understanding or "(vazio)") +
        "\n\n[Conversa]\n" + (conversation or "(vazia)") +
        "\n\n[Quadro]\n" + whiteboard.render(include_annotations=False) +
        "\n\n[Tarefa]\n" + task)
    try:
        content = _complete(client, [
            {"role": "system", "content": OBSERVER_SYSTEM},
            {"role": "user", "content": prompt},
        ], temperature)
    except Exception:
        return previous_understanding, []
    obj = extract_json_object(content)
    understanding = str(obj.get("understanding") or "").strip()
    raw_guidance = obj.get("guidance")
    guidance: list[str] = []
    if isinstance(raw_guidance, list):
        guidance = [str(item).strip() for item in raw_guidance
                    if str(item).strip()]
    elif isinstance(raw_guidance, str) and raw_guidance.strip():
        guidance = [raw_guidance.strip()]
    if not understanding:
        understanding = previous_understanding
    return understanding[:1200], guidance[:8]


def _complete(client: Any, messages: list[dict[str, str]],
              temperature: float) -> str:
    cwr = getattr(client, "complete_with_reasoning", None)
    if cwr is not None:
        content, _reasoning = cwr(messages, temperature=temperature)
        return content
    return client.complete(messages, temperature=temperature)


def main_user_prompt(
    whiteboard: Whiteboard,
    task: str,
    history: str = "",
    extra_context: str = "",
    *,
    evidence_label: str = "External context",
    temporal_instruction: bool = False,
    whiteboard_budget: int = 0,
    observer_guidance: str = "",
) -> str:
    parts = []
    if history:
        parts.append(history)
    if observer_guidance:
        parts.append("## Observador da conversa\n\n" + observer_guidance)
    board = whiteboard.render()
    if whiteboard_budget > 0 and len(board) > whiteboard_budget:
        board = board[: max(0, whiteboard_budget - 14)] + "\n… (trimmed)"
    parts.append("## Whiteboard\n\n" + board)
    if extra_context:
        parts.append(f"## {evidence_label}\n\n" + extra_context)
    if temporal_instruction:
        parts.append(TEMPORAL_SECTION)
    parts.append("## Task\n\n" + task)
    return "\n\n".join(parts)


def extract_memories(content: str) -> tuple[str, list[dict[str, Any]]]:
    """Split raw memories JSON out of a reply. Returns (clean_text, memories)."""
    memories: list[dict[str, Any]] = []
    clean = content
    for m in MEMORIES_RE.finditer(content):
        start = m.start()
        decoder = json.JSONDecoder()
        try:
            obj, end = decoder.raw_decode(content[start:])
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and "memories" in obj:
            for mem in obj.get("memories") or []:
                if isinstance(mem, dict):
                    memories.append(mem)
            clean = clean.replace(content[start : start + end], "", 1)
    return clean.strip(), memories


def memory_from_spec(spec: dict[str, Any]) -> MemoryRecord | None:
    mtype = str(spec.get("type") or "").strip()
    summary = str(spec.get("summary") or "").strip()
    if not mtype or not summary:
        return None
    files = spec.get("files") or []
    if isinstance(files, str):
        files = [f.strip() for f in files.split(",") if f.strip()]
    return MemoryRecord(
        type=mtype,
        summary=summary,
        why=str(spec.get("why") or ""),
        files=list(files),
    )


def run_main_chatbot(
    client: Any,
    whiteboard: Whiteboard,
    task: str,
    *,
    history: str = "",
    extra_context: str = "",
    memory_aware: bool = False,
    temporal_instruction: bool = False,
    temperature: float = 0.0,
    on_token: Any = None,
    whiteboard_budget: int = 0,
    observer_guidance: str = "",
) -> tuple[str, list[MemoryRecord], str]:
    """Run the main chatbot. Returns ``(reply, durable_memories, reasoning)``.

    ``on_token`` is an optional callback ``(content_delta, reasoning_delta)``
    called as output is produced (streaming). The trailing memories JSON is
    stripped from the streamed content.
    """
    messages = [
        {
            "role": "system",
            "content": MAIN_SYSTEM_PROMPT_MEMORY if memory_aware else MAIN_SYSTEM_PROMPT,
        },
        {
            "role": "user",
            "content": main_user_prompt(
                whiteboard,
                task,
                history=history,
                extra_context=extra_context,
                evidence_label=(
                    "Recalled memory evidence" if memory_aware else "External context"
                ),
                temporal_instruction=temporal_instruction,
                whiteboard_budget=whiteboard_budget,
                observer_guidance=observer_guidance,
            ),
        },
    ]
    reasoning = ""
    content = ""

    if on_token is not None and hasattr(client, "stream"):
        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        visible_len = 0
        for c_delta, r_delta in client.stream(messages, temperature=temperature):
            if r_delta:
                reasoning_parts.append(r_delta)
            if c_delta:
                content_parts.append(c_delta)
                acc = "".join(content_parts)
                m = MEMORIES_RE.search(acc)
                visible = acc if m is None else acc[: m.start()]
                if len(visible) > visible_len:
                    on_token(visible[visible_len:], r_delta)
                    visible_len = len(visible)
                else:
                    on_token("", r_delta)
            else:
                on_token("", r_delta)
        content = "".join(content_parts)
        reasoning = "".join(reasoning_parts)
    else:
        cwr = getattr(client, "complete_with_reasoning", None)
        if cwr is not None:
            content, reasoning = cwr(messages, temperature=temperature)
        else:
            content = client.complete(messages, temperature=temperature)
        if on_token is not None:
            on_token(content, reasoning)

    clean, specs = extract_memories(content)
    memories: list[MemoryRecord] = []
    for spec in specs:
        rec = memory_from_spec(spec)
        if rec is not None:
            memories.append(rec)
    return clean, memories, reasoning
