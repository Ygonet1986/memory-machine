"""Memory router: choose which tape partitions to consult.

The router is deterministic (no LLM): it ranks each group's digest against the
current query with BM25 and returns the top-K groups. This bounds the per-turn
cost to O(K) agent calls instead of O(N / capacity).

If nothing matches, it falls back to a full sweep (default) so a relevant
partition is never silently skipped.
"""

from __future__ import annotations

from .agents import deterministic_digest
from .groups import Group, Manifest
from .retrieval import rank
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
) -> list[Group]:
    """Return the groups to consult for ``query`` (top-K, or a fallback)."""
    groups = list(manifest.groups)
    if not groups:
        return []

    by_num = _active_by_num(tape)
    docs: list[str] = []
    for g in groups:
        records = group_records_by_num(by_num, g)
        docs.append(group_digest(manifest, g, records))

    hits = rank(query, docs, limit=max(1, top_k))
    if not hits:
        if fallback == "recent":
            return sorted(groups, key=lambda g: g.end, reverse=True)[:top_k]
        return groups  # full sweep
    return [groups[i] for i, _score in hits]
