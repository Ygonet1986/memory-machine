"""Memory agents: per-group LLM calls that update their checklist AND annotate.

Each memory agent is a single LLM call whose system prompt embeds the full
content of its group's records plus its previous checklist, and whose user
prompt carries the current whiteboard. In one pass the agent:

  1. refines its dynamic checklist of what it must not forget to remind the
     assistant about (its own metacognition), and
  2. annotates the memories that are relevant to the current work.

This keeps the checklist fresh every turn without a separate LLM call.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any

from .groups import Agent, Group, Manifest, group_records
from .llm import extract_json_object
from .tape import MemoryRecord, Tape
from .whiteboard import Annotation, Whiteboard

AGENT_INSTRUCTIONS = """You are a memory agent ({agent_id}). You watch group {group_id} \
of the persistent memory tape (records {start}..{end}).

Your memories (only these; never invent others):

{records}

{checklist_section}

The shared whiteboard below describes the work happening right now.

Do two things in one response:

1. Update your checklist of the things you must NOT forget to remind the \
assistant about (based on your memories and the current work). Keep it \
dynamic: drop no-longer-relevant items, sharpen and keep relevant ones, add \
new ones. Be concise.

2. Identify which of YOUR memories MUST be remembered for the current work \
and annotate them.

Return ONLY a JSON object, nothing else:

{{"checklist":["...","..."],"annotations":[{{"memory_id":"M0001","note":"<why this matters now>","relevance":0.0}}]}}

Rules:
- Only annotate memory ids that appear in YOUR list above.
- relevance is a number from 0.0 (marginal) to 1.0 (critical).
- If nothing must be remembered, return "annotations":[].
- Do not invent memory ids or facts outside your group."""


def agent_system_prompt(
    agent: Agent,
    group: Group,
    records: list[MemoryRecord],
) -> str:
    body = "\n".join(r.text() for r in records) if records else "(no memories in this group)"
    if agent.checklist:
        checklist_section = (
            "\nYour previous checklist (refine it, do not just repeat it):\n" + agent.checklist
        )
    else:
        checklist_section = "\nYour previous checklist: (none yet)"
    return AGENT_INSTRUCTIONS.format(
        agent_id=agent.id,
        group_id=group.id,
        start=group.start,
        end=group.end,
        records=body,
        checklist_section=checklist_section,
    )


def agent_user_prompt(whiteboard: Whiteboard) -> str:
    return "## Whiteboard\n\n" + whiteboard.render(include_annotations=False)


def _annotations_from_obj(obj: dict[str, Any], agent_id: str) -> list[Annotation]:
    out: list[Annotation] = []
    for item in obj.get("annotations") or []:
        if not isinstance(item, dict):
            continue
        memory_id = str(item.get("memory_id") or "").strip()
        note = str(item.get("note") or "").strip()
        if not memory_id or not note:
            continue
        try:
            relevance = float(item.get("relevance") or 0.0)
        except (TypeError, ValueError):
            relevance = 0.0
        relevance = max(0.0, min(1.0, relevance))
        out.append(Annotation(memory_id=memory_id, note=note, relevance=relevance, agent_id=agent_id))
    return out


def parse_annotations(text: str, *, agent_id: str = "") -> list[Annotation]:
    return _annotations_from_obj(extract_json_object(text), agent_id)


def _checklist_from_obj(obj: dict[str, Any]) -> str:
    cl = obj.get("checklist")
    if isinstance(cl, list):
        return "\n".join(f"- {str(x).strip()}" for x in cl if str(x).strip())
    if isinstance(cl, str):
        return cl.strip()
    return ""


def _deterministic_checklist(records: list[MemoryRecord], max_items: int = 8) -> str:
    items = [f"- {r.summary}" for r in records[:max_items] if r.summary]
    return "\n".join(items)


def _run_one(
    agent: Agent,
    group: Group,
    records: list[MemoryRecord],
    whiteboard: Whiteboard,
    client: Any,
    *,
    temperature: float,
) -> list[Annotation]:
    messages = [
        {"role": "system", "content": agent_system_prompt(agent, group, records)},
        {"role": "user", "content": agent_user_prompt(whiteboard)},
    ]
    content = client.complete(messages, temperature=temperature)
    obj = extract_json_object(content)
    checklist = _checklist_from_obj(obj) or _deterministic_checklist(records)
    agent.checklist = checklist[:1500]
    agent.checklist_records = len(records)
    return _annotations_from_obj(obj, agent.id)


def run_agents(
    tape: Tape,
    manifest: Manifest,
    whiteboard: Whiteboard,
    client: Any,
    *,
    temperature: float = 0.0,
    max_workers: int | None = None,
    on_error: str = "skip",
) -> list[Annotation]:
    """Dispatch one LLM call per (group, agent) pair, in parallel.

    Each call updates the agent's checklist in place and returns its
    annotations. ``on_error`` controls failure handling: ``"skip"`` ignores a
    failed agent, ``"raise"`` propagates the exception.
    """
    tasks: list[tuple[Agent, Group, list[MemoryRecord]]] = []
    for agent in manifest.agents:
        group = next((g for g in manifest.groups if g.id == agent.group_id), None)
        if group is None:
            continue
        records = group_records(tape, group)
        if not records:
            continue
        tasks.append((agent, group, records))

    if not tasks:
        return []

    def work(item: tuple[Agent, Group, list[MemoryRecord]]) -> list[Annotation]:
        agent, group, records = item
        return _run_one(agent, group, records, whiteboard, client, temperature=temperature)

    results: list[Annotation] = []
    with ThreadPoolExecutor(max_workers=max_workers or len(tasks)) as pool:
        futures = [pool.submit(work, t) for t in tasks]
        for fut in futures:
            try:
                results.extend(fut.result())
            except Exception:
                if on_error == "raise":
                    raise
                continue
    return results
