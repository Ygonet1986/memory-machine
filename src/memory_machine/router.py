"""Memory router: choose which tape partitions to consult.

The router is deterministic (no LLM): it ranks each group's digest against the
current query with BM25 and returns the top-K groups. This bounds the per-turn
cost to O(K) agent calls instead of O(N / capacity).

If nothing matches, it falls back to a full sweep (default) so a relevant
partition is never silently skipped.
"""

from __future__ import annotations

from typing import Any

from .agents import deterministic_digest
from .groups import Group, Manifest
from .llm import extract_json_object
from .retrieval import Embedder, rank, rank_semantic
from .tape import MemoryRecord, Tape, parse_id


def _active_by_num(tape: Tape) -> dict[int, MemoryRecord]:
    out: dict[int, MemoryRecord] = {}
    for r in tape.read():
        if r.status != "active" or not r.id:
            continue
        try:
            out[parse_id(r.id)] = r
        except ValueError:
            continue
    return out


def group_records_by_num(by_num: dict[int, MemoryRecord], group: Group) -> list[MemoryRecord]:
    return [by_num[n] for n in range(group.start, group.end + 1) if n in by_num]


def group_digest(
    manifest: Manifest,
    group: Group,
    records: list[MemoryRecord],
) -> str:
    """The agent's digest if current, else a deterministic digest of the records."""
    agent = manifest.agent_for_group(group.id)
    if agent is not None and agent.digest and agent.digest_records == len(records):
        return agent.digest
    return deterministic_digest(records)


def select_groups(
    tape: Tape,
    manifest: Manifest,
    query: str,
    *,
    top_k: int = 5,
    fallback: str = "full",
    embedder: Embedder | None = None,
) -> list[Group]:
    """Return the groups to consult for ``query`` (top-K, or a fallback).

    With an ``embedder`` the selection is semantic; otherwise it is lexical
    (BM25). Lexical routing can miss partitions whose vocabulary does not
    overlap the query, which is why it is opt-in.
    """
    groups = list(manifest.groups)
    if not groups:
        return []

    by_num = _active_by_num(tape)
    docs: list[str] = []
    for g in groups:
        records = group_records_by_num(by_num, g)
        docs.append(group_digest(manifest, g, records))

    if embedder is not None:
        hits = rank_semantic(query, docs, embedder, limit=max(1, top_k))
    else:
        hits = rank(query, docs, limit=max(1, top_k))

    if not hits:
        if fallback == "recent":
            return sorted(groups, key=lambda g: g.end, reverse=True)[:top_k]
        return groups  # full sweep
    return [groups[i] for i, _score in hits]


ROUTER_PROMPT = """You route a query to the memory partitions that may hold \
memories relevant to it. Partitions and what they cover:

{partitions}

Query: {query}

Return ONLY JSON, nothing else:
{{"groups":["G1","G3"]}}

Choose up to {top_k} partition ids whose memories are most likely relevant to \
the query, even if the wording differs (match by meaning, not just words). If \
none could be relevant, return {{"groups":[]}}."""


def select_groups_llm(
    tape: Tape,
    manifest: Manifest,
    query: str,
    client: Any,
    *,
    top_k: int = 5,
    temperature: float = 0.0,
) -> list[Group] | None:
    """Semantic routing via one LLM call over the partition digests.

    Returns the selected groups, or ``None`` on failure (caller falls back).
    """
    groups = list(manifest.groups)
    if not groups or client is None:
        return None

    by_num = _active_by_num(tape)
    lines: list[str] = []
    for g in groups:
        records = group_records_by_num(by_num, g)
        digest = group_digest(manifest, g, records)[:300] or "(no digest)"
        lines.append(f"{g.id}: {digest}")

    messages = [
        {
            "role": "system",
            "content": ROUTER_PROMPT.format(
                partitions="\n".join(lines), query=query, top_k=top_k
            ),
        },
        {"role": "user", "content": query},
    ]
    try:
        content = client.complete(messages, temperature=temperature)
    except Exception:
        return None

    ids = extract_json_object(content).get("groups") or []
    by_id = {g.id: g for g in groups}
    selected = [by_id[i] for i in ids if isinstance(i, str) and i in by_id][:top_k]
    return selected or None
