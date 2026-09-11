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
from dataclasses import dataclass, field
from typing import Any

from .groups import Agent, Group, Manifest, group_records
from .llm import extract_json_object
from .tape import MemoryRecord, Tape
from .views import records_in_views
from .whiteboard import Annotation, Whiteboard


@dataclass
class CoverageSignal:
    """Recall-local telemetry: is this agent's set enough for this question?

    Deliberately NOT persisted on the agent: it answers a question about the
    current recall, not about what the agent must keep remembering.
    """

    agent_id: str = ""
    coverage: str = ""  # complete | partial | uncertain
    missing: list[str] = field(default_factory=list)


@dataclass
class RecallRun:
    """Result of one agent sweep: annotations plus recall-local coverage."""

    annotations: list[Annotation] = field(default_factory=list)
    coverage: list[CoverageSignal] = field(default_factory=list)


AGENT_INSTRUCTIONS = """You are a memory agent ({agent_id}). You watch group {group_id} \
of the persistent memory tape (records {start}..{end}).

Your memories (only these; never invent others):

{records}

{checklist_section}

The shared whiteboard below describes the work happening right now.

Do four things in one response:

1. Write a short digest (1-2 sentences) of what this group covers, so a router \
can decide later whether this group is worth consulting. Keep it topical and \
stable.

2. Update your checklist of the things you must NOT forget to remind the \
assistant about (based on your memories and the current work). Keep it \
dynamic: drop no-longer-relevant items, sharpen and keep relevant ones, add \
new ones. Be concise.

3. Identify which of YOUR memories MUST be remembered for the current work \
and annotate them.

4. Judge, from what you can see, whether YOUR memories are sufficient for the \
current work: "coverage" is "complete" (they cover what the work needs), \
"partial" (something relevant is missing) or "uncertain" (you cannot tell), \
and "missing" lists what is missing (empty when complete).

Return ONLY a JSON object, nothing else:

{{"digest":"<what this group covers>","checklist":["...","..."],"annotations":[{{"memory_id":"M0001","note":"<why this matters now>","relevance":0.0}}],"coverage":"complete","missing":[]}}

Rules:
- Only annotate memory ids that appear in YOUR list above.
- relevance is a number from 0.0 (marginal) to 1.0 (critical).
- If nothing must be remembered, return "annotations":[].
- coverage/missing are telemetry about THIS question only, never memories.
- Do not invent memory ids or facts outside your group."""


AGENT_INSTRUCTIONS_NO_CHECKLIST = """You are a memory agent ({agent_id}). You watch group {group_id} \
of the persistent memory tape (records {start}..{end}).

Your memories (only these; never invent others):

{records}

The shared whiteboard below describes the work happening right now.

Do three things in one response:

1. Write a short digest (1-2 sentences) of what this group covers, so a router \
can decide later whether this group is worth consulting.

2. Identify which of YOUR memories MUST be remembered for the current work \
and annotate them.

3. Judge, from what you can see, whether YOUR memories are sufficient for the \
current work: "coverage" is "complete" (they cover what the work needs), \
"partial" (something relevant is missing) or "uncertain" (you cannot tell), \
and "missing" lists what is missing (empty when complete).

Return ONLY a JSON object, nothing else:

{{"digest":"<what this group covers>","annotations":[{{"memory_id":"M0001","note":"<why this matters now>","relevance":0.0}}],"coverage":"complete","missing":[]}}

Rules:
- Only annotate memory ids that appear in YOUR list above.
- relevance is a number from 0.0 (marginal) to 1.0 (critical).
- If nothing must be remembered, return "annotations":[].
- coverage/missing are telemetry about THIS question only, never memories.
- Do not invent memory ids or facts outside your group."""


def agent_system_prompt(
    agent: Agent,
    group: Group,
    records: list[MemoryRecord],
    *,
    include_checklist: bool = True,
) -> str:
    body = "\n".join(r.text() for r in records) if records else "(no memories in this group)"
    if not include_checklist:
        return AGENT_INSTRUCTIONS_NO_CHECKLIST.format(
            agent_id=agent.id,
            group_id=group.id,
            start=group.start,
            end=group.end,
            records=body,
        )
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


def _digest_from_obj(obj: dict[str, Any]) -> str:
    digest = obj.get("digest")
    return digest.strip() if isinstance(digest, str) else ""


# ---------------------------------------------------------------- view agents
# A view agent watches a *region* of the memory (a view) instead of a
# chronological group. The same memory can be examined by several perspectives
# without being duplicated: a topic agent looks for domain facts and decisions,
# a temporal agent for evolution and sequence, a structural agent for kinds.

VIEW_PERSPECTIVES = {
    "semantic": "Look for facts, decisions, relations and constraints in this domain.",
    "temporal": "Look for evolution, sequence, changes, versions and earlier decisions.",
    "structural": "Look for items of this kind and where they came from.",
}

VIEW_AGENT_INSTRUCTIONS = """You are a {dimension} memory agent watching the view \
`{view}` of the memory tape. {perspective}

Your memories (only these; never invent others):

{records}

{checklist_section}

The shared whiteboard below describes the work happening right now.

Do four things in one response:

1. Write a short digest of what this view covers, so the router can decide later \
whether this view is worth consulting. Keep it topical and stable.

2. Update your checklist of the things you must NOT forget to remind the \
assistant about (based on your memories and the current work). Keep it \
dynamic: drop no-longer-relevant items, sharpen and keep relevant ones, add \
new ones. Be concise.

3. Identify which of YOUR memories MUST be remembered for the current work \
and annotate them.

4. Judge whether YOUR view is sufficient for the current work: "coverage" is \
"complete" (it covers what the work needs), "partial" (something relevant is \
missing) or "uncertain" (you cannot tell), and "missing" lists what is missing \
(empty when complete).

Return ONLY a JSON object, nothing else:

{{"digest":"<what this view covers>","checklist":["...","..."],"annotations":[{{"memory_id":"M0001","note":"<why this matters now>","relevance":0.0}}],"coverage":"complete","missing":[]}}

Rules:
- Only annotate memory ids that appear in YOUR list above.
- relevance is a number from 0.0 (marginal) to 1.0 (critical).
- If nothing must be remembered, return "annotations":[].
- coverage/missing are telemetry about THIS question only, never memories.
- Do not invent memory ids or facts outside your view."""


def view_agent_prompt(
    view: str,
    records: list[MemoryRecord],
    view_agent: Any = None,
) -> str:
    """System prompt for a view agent, with a perspective per dimension."""
    from .routing import dimension_of

    dimension = dimension_of(view) or "semantic"
    body = "\n".join(r.text() for r in records) if records else "(no memories in this view)"
    checklist = getattr(view_agent, "checklist", "") if view_agent is not None else ""
    if checklist:
        checklist_section = (
            "\nYour previous checklist (refine it, do not just repeat it):\n" + checklist
        )
    else:
        checklist_section = "\nYour previous checklist: (none yet)"
    return VIEW_AGENT_INSTRUCTIONS.format(
        dimension=dimension,
        view=view,
        perspective=VIEW_PERSPECTIVES.get(dimension, VIEW_PERSPECTIVES["semantic"]),
        records=body,
        checklist_section=checklist_section,
    )


def _run_view_one(
    view: str,
    records: list[MemoryRecord],
    whiteboard: Whiteboard,
    client: Any,
    view_agent: Any,
    *,
    temperature: float,
) -> tuple[list[Annotation], CoverageSignal]:
    messages = [
        {"role": "system", "content": view_agent_prompt(view, records, view_agent)},
        {"role": "user", "content": agent_user_prompt(whiteboard)},
    ]
    content = client.complete(messages, temperature=temperature)
    obj = extract_json_object(content)
    checklist = _checklist_from_obj(obj) or _deterministic_checklist(records)
    view_agent.checklist = checklist[:1500]
    view_agent.checklist_records = len(records)
    digest = _digest_from_obj(obj) or deterministic_digest(records)
    view_agent.digest = digest[:600]
    view_agent.digest_records = len(records)
    signal = _coverage_from_obj(obj, f"view:{view}")
    view_agent.coverage = signal.coverage
    return _annotations_from_obj(obj, f"view:{view}"), signal


def run_view_agents(
    tape: Tape,
    manifest: Manifest,
    whiteboard: Whiteboard,
    client: Any,
    *,
    views: list[str],
    temperature: float = 0.0,
    max_workers: int | None = None,
    on_error: str = "skip",
) -> RecallRun:
    """Dispatch one perspective agent per selected view, in parallel.

    Unlike group agents (which see a chronological partition), a view agent
    sees every active memory in its view, so several agents can examine the
    same memory from different perspectives without duplicating it. Each view
    keeps its own persistent digest and checklist in the manifest.
    """
    tasks: list[tuple[str, list[MemoryRecord], Any]] = []
    for view in dict.fromkeys(views):
        records = records_in_views(tape, [view])
        if records:
            tasks.append((view, records, manifest.view_agent(view)))

    if not tasks:
        return RecallRun()

    def work(item: tuple[str, list[MemoryRecord], Any]) -> tuple[list[Annotation], CoverageSignal]:
        view, records, view_agent = item
        return _run_view_one(
            view, records, whiteboard, client, view_agent, temperature=temperature
        )

    run = RecallRun()
    with ThreadPoolExecutor(max_workers=max_workers or len(tasks)) as pool:
        futures = [pool.submit(work, t) for t in tasks]
        for fut in futures:
            try:
                annotations, coverage = fut.result()
            except Exception:
                if on_error == "raise":
                    raise
                continue
            run.annotations.extend(annotations)
            run.coverage.append(coverage)
    return run


def _coverage_from_obj(obj: dict[str, Any], agent_id: str) -> CoverageSignal:
    level = str(obj.get("coverage") or "").strip().lower()
    if level not in {"complete", "partial", "uncertain"}:
        level = "uncertain"
    raw_missing = obj.get("missing")
    missing: list[str] = []
    if isinstance(raw_missing, list):
        missing = [str(m).strip() for m in raw_missing if str(m).strip()]
    elif isinstance(raw_missing, str) and raw_missing.strip():
        missing = [raw_missing.strip()]
    return CoverageSignal(agent_id=agent_id, coverage=level, missing=missing)


def deterministic_digest(records: list[MemoryRecord], max_items: int = 10) -> str:
    return " | ".join(r.summary for r in records[:max_items] if r.summary)


def _run_one(
    agent: Agent,
    group: Group,
    records: list[MemoryRecord],
    whiteboard: Whiteboard,
    client: Any,
    *,
    temperature: float,
    include_checklist: bool = True,
) -> tuple[list[Annotation], CoverageSignal]:
    messages = [
        {
            "role": "system",
            "content": agent_system_prompt(
                agent, group, records, include_checklist=include_checklist
            ),
        },
        {"role": "user", "content": agent_user_prompt(whiteboard)},
    ]
    content = client.complete(messages, temperature=temperature)
    obj = extract_json_object(content)
    if include_checklist:
        checklist = _checklist_from_obj(obj) or _deterministic_checklist(records)
        agent.checklist = checklist[:1500]
        agent.checklist_records = len(records)
    digest = _digest_from_obj(obj) or deterministic_digest(records)
    agent.digest = digest[:600]
    agent.digest_records = len(records)
    return _annotations_from_obj(obj, agent.id), _coverage_from_obj(obj, agent.id)


def run_agents(
    tape: Tape,
    manifest: Manifest,
    whiteboard: Whiteboard,
    client: Any,
    *,
    groups: list[Group] | None = None,
    views_filter: set[str] | None = None,
    ids_filter: set[str] | None = None,
    temperature: float = 0.0,
    max_workers: int | None = None,
    on_error: str = "skip",
    include_checklist: bool = True,
) -> RecallRun:
    """Dispatch one LLM call per (group, agent) pair, in parallel.

    When ``groups`` is given, only those partitions are consulted (the memory
    router's selection). ``views_filter`` keeps records that belong to any of
    the given views; ``ids_filter`` keeps only the given record ids (used for
    dimension intersections). Each call updates the agent's checklist and
    digest in place and returns its annotations plus recall-local coverage.
    ``on_error`` controls failure handling: ``"skip"`` ignores a failed agent,
    ``"raise"`` propagates the exception.
    """
    selected_ids = {g.id for g in groups} if groups is not None else None
    tasks: list[tuple[Agent, Group, list[MemoryRecord]]] = []
    for agent in manifest.agents:
        group = next((g for g in manifest.groups if g.id == agent.group_id), None)
        if group is None:
            continue
        if selected_ids is not None and group.id not in selected_ids:
            continue
        records = group_records(tape, group)
        if views_filter:
            records = [r for r in records if set(r.views) & views_filter]
        if ids_filter is not None:
            records = [r for r in records if r.id in ids_filter]
        if not records:
            continue
        tasks.append((agent, group, records))

    if not tasks:
        return RecallRun()

    def work(item: tuple[Agent, Group, list[MemoryRecord]]) -> tuple[list[Annotation], CoverageSignal]:
        agent, group, records = item
        return _run_one(
            agent,
            group,
            records,
            whiteboard,
            client,
            temperature=temperature,
            include_checklist=include_checklist,
        )

    run = RecallRun()
    with ThreadPoolExecutor(max_workers=max_workers or len(tasks)) as pool:
        futures = [pool.submit(work, t) for t in tasks]
        for fut in futures:
            try:
                annotations, coverage = fut.result()
            except Exception:
                if on_error == "raise":
                    raise
                continue
            run.annotations.extend(annotations)
            run.coverage.append(coverage)
    return run
