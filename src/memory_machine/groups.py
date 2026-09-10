"""Groups and memory agents over the tape.

The tape grows by appending records. A ``Group`` is a contiguous range of
record ids; each group is watched by exactly one memory ``Agent``. When the
current group reaches capacity, a new group and a new agent are created to
follow the next range of records.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

from .tape import MemoryRecord, Tape, parse_id


@dataclass
class Group:
    id: str
    start: int
    end: int
    agent_id: str = ""

    def contains(self, id_num: int) -> bool:
        return self.start <= id_num <= self.end

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Group":
        return cls(
            id=str(data.get("id") or ""),
            start=int(data.get("start") or 0),
            end=int(data.get("end") or 0),
            agent_id=str(data.get("agent_id") or ""),
        )


@dataclass
class Agent:
    id: str
    group_id: str
    model: str = ""
    checklist: str = ""
    checklist_records: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Agent":
        return cls(
            id=str(data.get("id") or ""),
            group_id=str(data.get("group_id") or ""),
            model=str(data.get("model") or ""),
            checklist=str(data.get("checklist") or ""),
            checklist_records=int(data.get("checklist_records") or 0),
        )


@dataclass
class Manifest:
    version: int = 1
    capacity: int = 50
    groups: list[Group] = field(default_factory=list)
    agents: list[Agent] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "capacity": self.capacity,
            "groups": [g.to_dict() for g in self.groups],
            "agents": [a.to_dict() for a in self.agents],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Manifest":
        return cls(
            version=int(data.get("version") or 1),
            capacity=int(data.get("capacity") or 50),
            groups=[Group.from_dict(g) for g in (data.get("groups") or [])],
            agents=[Agent.from_dict(a) for a in (data.get("agents") or [])],
        )

    def group_for_id(self, id_num: int) -> Group | None:
        for g in self.groups:
            if g.contains(id_num):
                return g
        return None

    def next_group_num(self) -> int:
        return len(self.groups) + 1

    def next_agent_num(self) -> int:
        return len(self.agents) + 1

    def last_end(self) -> int:
        return max((g.end for g in self.groups), default=0)

    def agent_for_group(self, group_id: str) -> Agent | None:
        for a in self.agents:
            if a.group_id == group_id:
                return a
        return None


def load_manifest(path: Path, capacity: int | None = None) -> Manifest:
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            manifest = Manifest.from_dict(data)
            if capacity is not None:
                manifest.capacity = capacity
            return manifest
        except (json.JSONDecodeError, OSError):
            pass
    return Manifest(capacity=capacity or 50)


def save_manifest(manifest: Manifest, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest.to_dict(), indent=2) + "\n", encoding="utf-8")


def ensure_group(manifest: Manifest, id_num: int, model: str = "") -> tuple[Manifest, Group, Agent, bool]:
    """Return the group covering ``id_num``, creating a new group + agent if needed.

    Returns ``(manifest, group, agent, created)`` where ``created`` is True when
    a new group (and agent) was spawned.
    """
    existing = manifest.group_for_id(id_num)
    if existing is not None:
        agent = manifest.agent_for_group(existing.id)
        return manifest, existing, agent or Agent(id="", group_id=existing.id), False

    start = manifest.last_end() + 1
    if start == 1 and id_num > 1:
        # Tape pre-populated before manifest: cover from the first id onward.
        start = 1
    end = start + manifest.capacity - 1

    gid = f"G{manifest.next_group_num()}"
    aid = f"A{manifest.next_agent_num()}"
    group = Group(id=gid, start=start, end=end, agent_id=aid)
    agent = Agent(id=aid, group_id=gid, model=model)
    manifest.groups.append(group)
    manifest.agents.append(agent)
    return manifest, group, agent, True


def add_memory(
    tape: Tape,
    manifest: Manifest,
    record: MemoryRecord,
    model: str = "",
) -> tuple[MemoryRecord, Group, Agent, bool]:
    """Append a record to the tape and ensure a group/agent covers it.

    Returns ``(record, group, agent, created)``.
    """
    record = tape.append(record)
    id_num = parse_id(record.id)
    manifest, group, agent, created = ensure_group(manifest, id_num, model=model)
    return record, group, agent, created


def group_records(tape: Tape, group: Group) -> list[MemoryRecord]:
    """Return the active records belonging to a group (clamped to the tape)."""
    return [r for r in tape.read_range(group.start, group.end) if r.status == "active"]
