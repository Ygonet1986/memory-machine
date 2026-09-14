"""Graph projection over the canonical tape (Graph Memory Machine, F1).

The tape is the single source of truth; the graph is a **rebuildable
projection** derived from it, exactly like the views (``views.py``). Nothing
here writes to the tape: every entity, relation, alias and mention carries the
``memory_id`` that produced it, so ``graph explain`` walks any edge back to the
original memory text.

Layout (all append-only JSONL, under ``<root>/graph`` by default):

    entities.jsonl   E0001: name/type/first memory
    relations.jsonl  R0001: source -> relation -> target, with memory_id
    aliases.jsonl    entity aliases seen in the tape (resolution is additive)
    mentions.jsonl   memory_id -> entity_id (memories are things too)
    extracted.jsonl  one line per memory processed (idempotence marker)
    failed.jsonl     extractor failures (retried on the next build)
    meta.json        extractor name/version, counts, last built at

``pending`` is derived (durable records with no extraction marker for the
current extractor), so there is no second source of truth.

F1 ships the store, indices, traversal, rebuild and the CLI
(``graph build/status/explain``) with an injectable extractor; the LLM
extractor, resolver bands and graph recall arrive in F2/F3.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

GRAPH_EXTRACTOR_VERSION = "v1"
GRAPH_SCHEMA_VERSION = 1
GRAPH_RESOLVER_VERSION = "1.0"

# Epistemological/resolution edges are metadata, not domain knowledge: recall
# traversal never follows them unless explicitly asked.
RESOLUTION_KINDS = {"resolution", "hypothesis"}

DURABLE_TYPES = ("decision", "lesson", "preference", "bugfix", "build")

MAX_ENTITIES = 20
MAX_RELATIONS = 30
MAX_ALIASES = 8
MAX_ATTEMPTS = 3


class ExtractionError(Exception):
    """Extraction failed schema validation (retried up to the policy)."""


class TransientExtractionError(ExtractionError):
    """LLM/API failure (timeout, empty completion); retried up to the policy."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_name(name: str) -> str:
    """Case/accents/punctuation-insensitive key used for entity resolution."""
    text = unicodedata.normalize("NFKD", str(name or "").strip().lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[\W_]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def parse_types(raw: Any) -> set[str]:
    """Parse a comma-separated extract-types config into a set."""
    if isinstance(raw, (list, tuple, set)):
        return {str(x).strip().lower() for x in raw if str(x).strip()}
    return {t.strip().lower() for t in str(raw or "").split(",") if t.strip()}


@dataclass
class GraphEntity:
    id: str
    name: str
    type: str = "unknown"
    memory_id: str = ""
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GraphEntity":
        return cls(
            id=str(data.get("id") or ""),
            name=str(data.get("name") or ""),
            type=str(data.get("type") or "unknown"),
            memory_id=str(data.get("memory_id") or ""),
            created_at=str(data.get("created_at") or ""),
        )


@dataclass
class GraphRelation:
    id: str
    source: str
    relation: str
    target: str
    memory_id: str = ""
    confidence: float = 0.8
    kind: str = ""
    extractor: str = ""
    extractor_version: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GraphRelation":
        try:
            confidence = float(data.get("confidence") or 0.8)
        except (TypeError, ValueError):
            confidence = 0.8
        return cls(
            id=str(data.get("id") or ""),
            source=str(data.get("source") or ""),
            relation=str(data.get("relation") or ""),
            target=str(data.get("target") or ""),
            memory_id=str(data.get("memory_id") or ""),
            confidence=max(0.0, min(1.0, confidence)),
            kind=str(data.get("kind") or ""),
            extractor=str(data.get("extractor") or ""),
            extractor_version=str(data.get("extractor_version") or ""),
        )


@dataclass
class GraphAlias:
    entity_id: str
    alias: str
    memory_id: str = ""
    confidence: float = 0.8
    method: str = ""
    extractor: str = ""
    extractor_version: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class GraphMention:
    memory_id: str
    entity_id: str
    confidence: float = 0.8

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ExtractedEntity:
    ref: str
    name: str
    type: str = "unknown"
    confidence: float = 0.8
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExtractedEvent:
    ref: str
    action: str
    agent: str = ""
    object: str = ""
    confidence: float = 0.8
    kind: str = "event"


@dataclass(frozen=True)
class ExtractedRelation:
    source: str
    relation: str
    target: str
    confidence: float = 0.8
    kind: str = ""


@dataclass(frozen=True)
class Extraction:
    """Validated, immutable extractor output (semantic refs, never E/R ids).

    Parsing happens entirely before any graph mutation: the resolver turns
    ``e1``/``ev1`` refs into ``E####`` and only then does the store change.
    """

    entities: tuple[ExtractedEntity, ...] = ()
    events: tuple[ExtractedEvent, ...] = ()
    relations: tuple[ExtractedRelation, ...] = ()
    mentions: tuple[str, ...] = ()
    confidence: float = 0.8
    kind: str = ""
    memory_id: str = ""
    extractor: str = ""
    extractor_version: str = ""

    @classmethod
    def from_obj(
        cls,
        obj: Any,
        *,
        memory_id: str = "",
        extractor: str = "",
        extractor_version: str = "",
    ) -> "Extraction":
        """Lenient validation of an extractor payload (invalid items dropped)."""
        if not isinstance(obj, dict):
            return cls(memory_id=memory_id, extractor=extractor, extractor_version=extractor_version)
        entities: list[ExtractedEntity] = []
        for i, raw in enumerate((obj.get("entities") or [])[:MAX_ENTITIES], start=1):
            if not isinstance(raw, dict):
                continue
            name = str(raw.get("name") or "").strip()
            if not name:
                continue
            aliases = tuple(
                str(a).strip()
                for a in (raw.get("aliases") or [])[:MAX_ALIASES]
                if str(a).strip()
            )
            entities.append(
                ExtractedEntity(
                    ref=str(raw.get("ref") or f"e{i}").strip() or f"e{i}",
                    name=name[:120],
                    type=str(raw.get("type") or "unknown").strip().lower()[:40] or "unknown",
                    confidence=_clamp(raw.get("confidence"), 0.8),
                    aliases=aliases,
                )
            )
        events: list[ExtractedEvent] = []
        for i, raw in enumerate((obj.get("events") or [])[:MAX_RELATIONS], start=1):
            if not isinstance(raw, dict):
                continue
            action = str(raw.get("action") or "").strip()
            if not action:
                continue
            events.append(
                ExtractedEvent(
                    ref=str(raw.get("ref") or f"ev{i}").strip() or f"ev{i}",
                    action=action[:60],
                    agent=str(raw.get("agent") or "").strip()[:120],
                    object=str(raw.get("object") or "").strip()[:120],
                    confidence=_clamp(raw.get("confidence"), 0.8),
                    kind=str(raw.get("kind") or "event").strip().lower()[:40] or "event",
                )
            )
        relations: list[ExtractedRelation] = []
        for raw in (obj.get("relations") or [])[:MAX_RELATIONS]:
            if not isinstance(raw, dict):
                continue
            source = str(raw.get("source") or "").strip()
            relation = str(raw.get("relation") or "").strip()
            target = str(raw.get("target") or "").strip()
            if not (source and relation and target):
                continue
            relations.append(
                ExtractedRelation(
                    source=source[:120],
                    relation=relation[:60],
                    target=target[:120],
                    confidence=_clamp(raw.get("confidence"), 0.8),
                    kind=str(raw.get("kind") or "").strip().lower()[:40],
                )
            )
        mentions = tuple(
            str(m).strip()
            for m in (obj.get("mentions") or [])[:MAX_ENTITIES]
            if str(m).strip()
        )
        return cls(
            entities=tuple(entities),
            events=tuple(events),
            relations=tuple(relations),
            mentions=mentions,
            confidence=_clamp(obj.get("confidence"), 0.8),
            kind=str(obj.get("kind") or "").strip().lower()[:40],
            memory_id=memory_id,
            extractor=extractor,
            extractor_version=extractor_version,
        )


def _clamp(value: Any, default: float) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return default


Extractor = Callable[[Any], dict[str, Any]]


def noop_extractor(record: Any) -> dict[str, Any]:
    """Diagnostic extractor: exercises the pipeline without inventing facts."""
    return {"entities": [], "relations": []}


@dataclass(frozen=True)
class ExtractorSpec:
    fn: Extractor
    version: str = GRAPH_EXTRACTOR_VERSION


EXTRACTORS: dict[str, ExtractorSpec] = {"noop": ExtractorSpec(noop_extractor)}


class GraphIndex:
    """Read-only indices over a loaded graph (names, aliases, adjacency)."""

    def __init__(self) -> None:
        self.entities: dict[str, GraphEntity] = {}
        self.relations: dict[str, GraphRelation] = {}
        self.by_norm: dict[str, str] = {}
        self.alias_map: dict[str, str] = {}
        self.out_edges: dict[str, list[GraphRelation]] = {}
        self.in_edges: dict[str, list[GraphRelation]] = {}
        self.memory_entities: dict[str, set[str]] = {}
        self.entity_memories: dict[str, set[str]] = {}
        self.mention_confidence: dict[tuple[str, str], float] = {}
        self.merged: dict[str, str] = {}  # accepted review merges (source -> target)

    @classmethod
    def load(cls, store: "GraphStore") -> "GraphIndex":
        index = cls()
        for entity in store.entities():
            index.add_entity(entity)
        for alias in store.aliases():
            index.alias_map.setdefault(normalize_name(alias.alias), alias.entity_id)
            if alias.method == "merge" and alias.alias in index.entities:
                index.merged.setdefault(alias.alias, alias.entity_id)
        for pair, decision in store.reviewed_pairs().items():
            if decision != "accept":
                continue
            source = index.by_norm.get(pair[0]) or index.alias_map.get(pair[0])
            target = index.by_norm.get(pair[1]) or index.alias_map.get(pair[1])
            if source and target and source != target:
                index.merged.setdefault(source, target)
        for relation in store.relations():
            index.add_relation(relation)
        for mention in store.mentions():
            index.memory_entities.setdefault(mention.memory_id, set()).add(mention.entity_id)
            index.entity_memories.setdefault(mention.entity_id, set()).add(mention.memory_id)
            index.mention_confidence[(mention.memory_id, mention.entity_id)] = mention.confidence
        return index

    @property
    def max_entity_num(self) -> int:
        return max((self._num(e, "E") for e in self.entities), default=0)

    @property
    def max_relation_num(self) -> int:
        return max((self._num(r, "R") for r in self.relations), default=0)

    @staticmethod
    def _num(entity_id: str, prefix: str) -> int:
        m = re.match(rf"^{prefix}(\d+)$", str(entity_id or ""))
        return int(m.group(1)) if m else 0

    def add_entity(self, entity: GraphEntity) -> None:
        self.entities[entity.id] = entity
        self.by_norm.setdefault(normalize_name(entity.name), entity.id)

    def add_relation(self, relation: GraphRelation) -> None:
        self.relations[relation.id] = relation
        self.out_edges.setdefault(relation.source, []).append(relation)
        self.in_edges.setdefault(relation.target, []).append(relation)

    def resolve(self, name: str) -> str:
        key = normalize_name(name)
        entity_id = self.by_norm.get(key) or self.alias_map.get(key) or ""
        return self.canonical(entity_id) if entity_id else ""

    def canonical(self, entity_id: str) -> str:
        """Follow accepted review merges (append-only redirects)."""
        seen: set[str] = set()
        while entity_id in self.merged and entity_id not in seen:
            seen.add(entity_id)
            entity_id = self.merged[entity_id]
        return entity_id

    def edges_of(
        self,
        entity_id: str,
        *,
        direction: str = "both",
        kinds: Iterable[str] | None = None,
        include_resolution: bool = False,
    ) -> list[GraphRelation]:
        want = {str(k).strip().lower() for k in kinds} if kinds else None
        edges = []
        if direction in {"both", "out"}:
            edges.extend(self.out_edges.get(entity_id, []))
        if direction in {"both", "in"}:
            edges.extend(self.in_edges.get(entity_id, []))
        if want:
            edges = [r for r in edges if r.kind in want or r.relation in want]
        elif not include_resolution:
            edges = [r for r in edges if r.kind not in RESOLUTION_KINDS]
        return edges

    def neighbors(
        self,
        entity_id: str,
        *,
        depth: int = 1,
        min_confidence: float = 0.0,
        direction: str = "both",
        kinds: Iterable[str] | None = None,
        include_resolution: bool = False,
    ) -> list[tuple[GraphRelation, str, float]]:
        """BFS over edges; returns ``(relation, other_entity, path_confidence)``.

        The path confidence is the bottleneck (minimum edge confidence) along
        the path that reached the entity. Resolution edges are skipped unless
        ``include_resolution`` is set.
        """
        frontier = [(entity_id, 1.0)]
        seen = {entity_id: 1.0}
        out: list[tuple[GraphRelation, str, float]] = []
        for _ in range(max(1, depth)):
            nxt: list[tuple[str, float]] = []
            for current, path_conf in frontier:
                for relation in self.edges_of(
                    current,
                    direction=direction,
                    kinds=kinds,
                    include_resolution=include_resolution,
                ):
                    if relation.confidence < min_confidence:
                        continue
                    other = relation.target if relation.source == current else relation.source
                    confidence = min(path_conf, relation.confidence)
                    if other not in seen or confidence > seen[other]:
                        seen[other] = confidence
                        nxt.append((other, confidence))
                        out.append((relation, other, confidence))
            frontier = nxt
            if not frontier:
                break
        return out

    def path(
        self,
        source_id: str,
        target_id: str,
        *,
        max_depth: int = 3,
        min_confidence: float = 0.0,
        kinds: Iterable[str] | None = None,
    ) -> list[GraphRelation] | None:
        """Shortest path (BFS) between two entities, or ``None``."""
        if source_id == target_id:
            return []
        queue: deque[tuple[str, list[GraphRelation]]] = deque([(source_id, [])])
        seen = {source_id}
        while queue:
            current, trail = queue.popleft()
            if len(trail) >= max(1, max_depth):
                continue
            for relation in self.edges_of(current, direction="both", kinds=kinds):
                if relation.confidence < min_confidence:
                    continue
                other = relation.target if relation.source == current else relation.source
                if other in seen:
                    continue
                new_trail = trail + [relation]
                if other == target_id:
                    return new_trail
                seen.add(other)
                queue.append((other, new_trail))
        return None

    def evidence_ids(
        self,
        entity_ids: Iterable[str],
        *,
        depth: int = 1,
        min_confidence: float = 0.0,
    ) -> dict[str, float]:
        """Memory ids reachable from the entities, scored by path confidence."""
        scores: dict[str, float] = {}
        for entity_id in entity_ids:
            for relation, _other, confidence in self.neighbors(
                entity_id, depth=depth, min_confidence=min_confidence
            ):
                if relation.memory_id:
                    scores[relation.memory_id] = max(
                        scores.get(relation.memory_id, 0.0), confidence
                    )
        return scores

    def memories_for_entity(self, entity_id: str) -> list[tuple[str, float]]:
        """Memories that mention the entity, with mention confidence."""
        return [
            (memory_id, self.mention_confidence.get((memory_id, entity_id), 0.8))
            for memory_id in sorted(self.entity_memories.get(entity_id, set()))
        ]

    def paths(
        self,
        source_id: str,
        target_id: str,
        *,
        max_depth: int = 3,
        limit: int = 5,
        min_confidence: float = 0.0,
        kinds: Iterable[str] | None = None,
    ) -> list[list[GraphRelation]]:
        """Up to ``limit`` simple paths between two entities, best first.

        Paths are scored by the bottleneck edge confidence (times the depth
        penalty); the result is stable for identical graphs.
        """
        if source_id == target_id:
            return [[]]
        found: list[tuple[float, list[GraphRelation]]] = []

        def walk(current: str, trail: list[GraphRelation], seen: set[str]) -> None:
            if len(trail) >= max(1, max_depth) or len(found) >= limit * 4:
                return
            for relation in self.edges_of(current, direction="both", kinds=kinds):
                if relation.confidence < min_confidence:
                    continue
                other = relation.target if relation.source == current else relation.source
                if other in seen:
                    continue
                new_trail = trail + [relation]
                if other == target_id:
                    bottleneck = min(r.confidence for r in new_trail)
                    score = bottleneck * (0.85 ** (len(new_trail) - 1))
                    found.append((score, new_trail))
                    continue
                walk(other, new_trail, seen | {other})

        walk(source_id, [], {source_id})
        found.sort(key=lambda pair: (-pair[0], [r.id for r in pair[1]]))
        return [trail for _score, trail in found[:limit]]


class GraphStore:
    """Append-only storage of the graph projection (never touches the tape)."""

    FILES = (
        "entities.jsonl",
        "relations.jsonl",
        "aliases.jsonl",
        "mentions.jsonl",
        "extracted.jsonl",
        "failed.jsonl",
        "pending.jsonl",
        "hypotheses.jsonl",
    )
    REVIEW_FILE = "reviews.jsonl"  # human decisions: preserved across rebuilds

    def __init__(self, directory: Path | str) -> None:
        self.directory = Path(directory)

    def _path(self, name: str) -> Path:
        return self.directory / name

    def _append(self, name: str, obj: dict[str, Any]) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        with self._path(name).open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(obj, ensure_ascii=False) + "\n")

    def _load(self, name: str) -> list[dict[str, Any]]:
        path = self._path(name)
        if not path.exists():
            return []
        out: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict):
                out.append(data)
        return out

    # ------------------------------------------------------------- append

    def add_entity(
        self,
        name: str,
        entity_type: str,
        memory_id: str,
        *,
        entity_id: str = "",
    ) -> GraphEntity:
        if not entity_id:
            entity_id = f"E{self.index().max_entity_num + 1:04d}"
        entity = GraphEntity(
            id=entity_id,
            name=str(name).strip(),
            type=str(entity_type or "unknown").strip() or "unknown",
            memory_id=memory_id,
            created_at=_now(),
        )
        self._append("entities.jsonl", entity.to_dict())
        return entity

    def add_relation(
        self,
        source: str,
        relation: str,
        target: str,
        memory_id: str,
        confidence: float,
        *,
        kind: str = "",
        relation_id: str = "",
        extractor: str = "",
        extractor_version: str = "",
    ) -> GraphRelation:
        if not relation_id:
            relation_id = f"R{self.index().max_relation_num + 1:04d}"
        item = GraphRelation(
            id=relation_id,
            source=source,
            relation=relation,
            target=target,
            memory_id=memory_id,
            confidence=max(0.0, min(1.0, float(confidence))),
            kind=kind,
            extractor=extractor,
            extractor_version=extractor_version,
        )
        self._append("relations.jsonl", item.to_dict())
        return item

    def add_alias(
        self,
        entity_id: str,
        alias: str,
        memory_id: str,
        confidence: float = 0.8,
        method: str = "extractor",
        *,
        extractor: str = "",
        extractor_version: str = "",
    ) -> GraphAlias:
        item = GraphAlias(
            entity_id=entity_id,
            alias=str(alias).strip(),
            memory_id=memory_id,
            confidence=max(0.0, min(1.0, float(confidence))),
            method=method,
            extractor=extractor,
            extractor_version=extractor_version,
        )
        self._append("aliases.jsonl", item.to_dict())
        return item

    def add_mention(self, memory_id: str, entity_id: str, confidence: float = 0.8) -> None:
        self._append(
            "mentions.jsonl",
            {"memory_id": memory_id, "entity_id": entity_id, "confidence": confidence},
        )

    def mark_extracted(
        self,
        memory_id: str,
        entities: int,
        relations: int,
        *,
        extractor: str = "",
    ) -> None:
        self._append(
            "extracted.jsonl",
            {
                "memory_id": memory_id,
                "entities": entities,
                "relations": relations,
                "extractor": extractor,
                "at": _now(),
            },
        )

    def mark_failed(self, memory_id: str, error: str, *, extractor: str = "") -> None:
        self._append(
            "failed.jsonl",
            {"memory_id": memory_id, "error": str(error)[:400], "extractor": extractor, "at": _now()},
        )

    def mark_pending(
        self, memory_id: str, error: str, *, extractor: str = "", attempts: int = 1
    ) -> None:
        self._append(
            "pending.jsonl",
            {
                "memory_id": memory_id,
                "error": str(error)[:400],
                "extractor": extractor,
                "attempts": max(1, int(attempts)),
                "at": _now(),
            },
        )

    def pending_rows(self, extractor: str = "") -> list[dict[str, Any]]:
        """Latest pending row per memory id (the queue, not the history)."""
        latest: dict[str, dict[str, Any]] = {}
        for row in self._load("pending.jsonl"):
            memory_id = str(row.get("memory_id") or "")
            if not memory_id:
                continue
            if extractor and row.get("extractor") != extractor:
                continue
            latest[memory_id] = row
        return list(latest.values())

    def pending_attempts(self, memory_id: str, *, extractor: str = "") -> int:
        for row in self.pending_rows(extractor):
            if row.get("memory_id") == memory_id:
                try:
                    return int(row.get("attempts") or 0)
                except (TypeError, ValueError):
                    return 0
        return 0

    def drop_pending(self, memory_id: str) -> None:
        """Remove a memory from the pending queue (operational, not history)."""
        path = self._path("pending.jsonl")
        if not path.exists():
            return
        keep = [
            json.dumps(row, ensure_ascii=False)
            for row in self._load("pending.jsonl")
            if str(row.get("memory_id") or "") != memory_id
        ]
        path.write_text("\n".join(keep) + ("\n" if keep else ""), encoding="utf-8")

    # ----------------------------------------------------------- hypotheses

    def add_hypothesis(
        self,
        *,
        kind: str,
        source_entity: str,
        target_entity: str,
        confidence: float,
        memory_id: str,
        source_name: str = "",
        target_name: str = "",
        resolver_version: str = GRAPH_RESOLVER_VERSION,
        relation_id: str = "",
        hypothesis_id: str = "",
    ) -> dict[str, Any]:
        if not hypothesis_id:
            hypothesis_id = f"H{self.next_hypothesis_num():04d}"
        row = {
            "id": hypothesis_id,
            "kind": kind,
            "source_entity": source_entity,
            "target_entity": target_entity,
            "source_name": source_name,
            "target_name": target_name,
            "confidence": max(0.0, min(1.0, float(confidence))),
            "memory_id": memory_id,
            "relation_id": relation_id,
            "resolver_version": resolver_version,
            "status": "open",
            "created_at": _now(),
        }
        self._append("hypotheses.jsonl", row)
        return row

    def next_hypothesis_num(self) -> int:
        numbers = []
        for row in self._load("hypotheses.jsonl"):
            match = re.match(r"^H(\d+)$", str(row.get("id") or ""))
            if match:
                numbers.append(int(match.group(1)))
        return max(numbers, default=0) + 1

    def hypotheses(self) -> list[dict[str, Any]]:
        """Latest state per hypothesis id (append-only decision rows)."""
        latest: dict[str, dict[str, Any]] = {}
        for row in self._load("hypotheses.jsonl"):
            hypothesis_id = str(row.get("id") or "")
            if not hypothesis_id:
                continue
            current = latest.get(hypothesis_id)
            if current is None:
                latest[hypothesis_id] = dict(row)
            else:
                merged = dict(current)
                merged.update(row)
                latest[hypothesis_id] = merged
        return list(latest.values())

    def reviewed_pairs(self) -> dict[tuple[str, str], str]:
        """Latest human decision per name pair (accept/reject/skip)."""
        decisions: dict[tuple[str, str], str] = {}
        for row in self._load(self.REVIEW_FILE):
            source = normalize_name(str(row.get("source_name") or ""))
            target = normalize_name(str(row.get("target_name") or ""))
            if not source or not target:
                continue
            decision = str(row.get("decision") or "skip")
            decisions[(source, target)] = decision
        return decisions

    def open_hypotheses(self) -> list[dict[str, Any]]:
        reviewed = self.reviewed_pairs()
        out = []
        for row in self.hypotheses():
            pair = (
                normalize_name(str(row.get("source_name") or "")),
                normalize_name(str(row.get("target_name") or "")),
            )
            if reviewed.get(pair) in {"accept", "reject"}:
                continue
            out.append(row)
        return out

    def add_review(
        self,
        source_name: str,
        target_name: str,
        decision: str,
        *,
        hypothesis_id: str = "",
        confidence: float = 0.0,
    ) -> dict[str, Any]:
        decision = decision if decision in {"accept", "reject", "skip"} else "skip"
        row = {
            "kind": "possibly_same_as",
            "source_name": source_name,
            "target_name": target_name,
            "decision": decision,
            "hypothesis_id": hypothesis_id,
            "confidence": max(0.0, min(1.0, float(confidence))),
            "reviewed_at": _now(),
        }
        self._append(self.REVIEW_FILE, row)
        return row

    def decide_hypothesis(self, hypothesis_id: str, decision: str) -> dict[str, Any]:
        """Append a human review decision; never rewrites the hypothesis rows."""
        row = next(
            (item for item in self.hypotheses() if item.get("id") == hypothesis_id), None
        ) or {}
        return self.add_review(
            str(row.get("source_name") or row.get("source_entity") or ""),
            str(row.get("target_name") or row.get("target_entity") or ""),
            decision,
            hypothesis_id=hypothesis_id,
            confidence=float(row.get("confidence") or 0.0),
        )

    def rejected_pairs(self) -> set[tuple[str, str]]:
        """Rejected identity pairs keyed by normalized names (stable across rebuilds)."""
        return {
            pair for pair, decision in self.reviewed_pairs().items() if decision == "reject"
        }

    # --------------------------------------------------------------- load

    def entities(self) -> list[GraphEntity]:
        return [GraphEntity.from_dict(d) for d in self._load("entities.jsonl")]

    def relations(self) -> list[GraphRelation]:
        return [GraphRelation.from_dict(d) for d in self._load("relations.jsonl")]

    def aliases(self) -> list[GraphAlias]:
        return [GraphAlias(**d) for d in self._load("aliases.jsonl")]

    def mentions(self) -> list[GraphMention]:
        return [GraphMention(**d) for d in self._load("mentions.jsonl")]

    def extracted_ids(self, extractor: str = "") -> set[str]:
        rows = self._load("extracted.jsonl")
        if extractor:
            rows = [r for r in rows if r.get("extractor") == extractor]
        return {str(r.get("memory_id") or "") for r in rows if r.get("memory_id")}

    def failed_rows(self) -> list[dict[str, Any]]:
        return self._load("failed.jsonl")

    def meta(self) -> dict[str, Any]:
        path = self._path("meta.json")
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, OSError):
            return {}

    def write_meta(self, meta: dict[str, Any]) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        self._path("meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    def counts(self) -> dict[str, int]:
        return {
            "entities": len(self.entities()),
            "relations": len(self.relations()),
            "aliases": len(self.aliases()),
            "mentions": len(self.mentions()),
            "extracted": len(self.extracted_ids()),
            "failed": len(self.failed_rows()),
            "pending": len(self.pending_rows()),
        }

    def exists(self) -> bool:
        return any(self._path(name).exists() for name in self.FILES)

    def index(self) -> GraphIndex:
        return GraphIndex.load(self)

    def clear(self) -> None:
        """Remove the projection files. Human reviews are preserved."""
        for name in (*self.FILES, "meta.json"):
            try:
                self._path(name).unlink(missing_ok=True)
            except OSError:
                continue

    def copy_reviews_from(self, other: "GraphStore") -> int:
        """Carry human review decisions into a fresh projection."""
        import shutil

        source = other._path(self.REVIEW_FILE)
        if not source.exists():
            return 0
        self.directory.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, self._path(self.REVIEW_FILE))
        return 1


def _ensure_entity(
    store: GraphStore,
    index: GraphIndex,
    name: str,
    entity_type: str,
    memory_id: str,
    *,
    created: list[str],
) -> str:
    entity_id = index.resolve(name)
    if entity_id:
        return entity_id
    entity_id = f"E{index.max_entity_num + 1:04d}"
    entity = store.add_entity(name, entity_type, memory_id, entity_id=entity_id)
    index.add_entity(entity)
    created.append(entity_id)
    return entity_id


def _resolve_with_resolver(
    store: GraphStore,
    index: GraphIndex,
    resolver: Any,
    name: str,
    entity_type: str,
    record: Any,
    *,
    created: list[str],
    extractor_name: str,
    extractor_version: str,
    resolver_version: str = "",
) -> str:
    """Resolve/create one entity, honouring the resolver's confidence bands."""
    resolution = None
    if resolver is not None:
        try:
            resolution = resolver.resolve({"name": name, "type": entity_type})
        except Exception:
            resolution = None
    if isinstance(resolution, str) and resolution:
        return resolution
    entity_id = str(getattr(resolution, "entity_id", "") or "") if resolution is not None else ""
    if entity_id:
        method = str(getattr(resolution, "method", "") or "")
        confidence = float(getattr(resolution, "confidence", 0.8) or 0.8)
        if method in {"alias", "embedding", "llm"}:
            store.add_alias(
                entity_id, name, record.id, confidence, method,
                extractor=extractor_name, extractor_version=extractor_version,
            )
            index.alias_map.setdefault(normalize_name(name), entity_id)
        return entity_id

    entity_id = _ensure_entity(
        store, index, name, entity_type, record.id, created=created
    )
    if resolution is not None and getattr(resolution, "hypothesis", False):
        other_id = str(getattr(resolution, "other_id", "") or "")
        other = index.entities.get(other_id)
        pair = (normalize_name(name), normalize_name(other.name if other else other_id))
        if other_id and pair not in store.rejected_pairs():
            confidence = float(getattr(resolution, "confidence", 0.6) or 0.6)
            relation = store.add_relation(
                entity_id,
                "possibly_same_as",
                other_id,
                record.id,
                confidence,
                kind="resolution",
                extractor=extractor_name,
                extractor_version=extractor_version,
            )
            index.add_relation(relation)
            store.add_hypothesis(
                kind="possibly_same_as",
                source_entity=entity_id,
                target_entity=other_id,
                source_name=name,
                target_name=other.name if other else "",
                confidence=confidence,
                memory_id=record.id,
                resolver_version=resolver_version or GRAPH_RESOLVER_VERSION,
                relation_id=relation.id,
            )
    return entity_id


def project_extraction(
    store: GraphStore,
    index: GraphIndex,
    record: Any,
    extraction: Extraction,
    *,
    tag: str,
    resolver: Any = None,
    extractor_name: str = "",
    extractor_version: str = "",
    resolver_version: str = "",
) -> dict[str, int]:
    """Mutate the projection from a fully validated ``Extraction``.

    The resolver maps semantic refs (``e1``/``ev1``) to ``E####``; the LLM
    never chooses graph ids. Events become ``type=event`` entities with
    ``agent``/``action``/``object`` edges, each relation carrying provenance.
    """
    if resolver is not None and hasattr(resolver, "bind"):
        resolver.bind(index)

    local: dict[str, str] = {}
    refs: dict[str, str] = {}
    mentioned: set[str] = set()
    created: list[str] = []
    relation_count = 0

    for item in extraction.entities:
        entity_id = _resolve_with_resolver(
            store, index, resolver, item.name, item.type, record,
            created=created, extractor_name=extractor_name,
            extractor_version=extractor_version,
            resolver_version=resolver_version,
        )
        local[normalize_name(item.name)] = entity_id
        refs.setdefault(item.ref, entity_id)
        mentioned.add(entity_id)
        for alias in item.aliases:
            store.add_alias(
                entity_id, alias, record.id, item.confidence, "extractor",
                extractor=extractor_name, extractor_version=extractor_version,
            )
            index.alias_map.setdefault(normalize_name(alias), entity_id)

    action_entities: dict[str, str] = {}

    def resolve_endpoint(raw: str) -> str:
        return refs.get(raw) or local.get(normalize_name(raw)) or index.resolve(raw)

    for event in extraction.events:
        event_entity = store.add_entity(
            f"{event.action} ({record.id})", "event", record.id
        )
        index.add_entity(event_entity)
        created.append(event_entity.id)
        refs.setdefault(event.ref, event_entity.id)
        mentioned.add(event_entity.id)

        action_entity = action_entities.get(event.action)
        if not action_entity:
            action_entity = _ensure_entity(
                store, index, event.action, "action", record.id, created=created
            )
            action_entities[event.action] = action_entity
        mentioned.add(action_entity)

        edges: list[tuple[str, str]] = [("action", action_entity)]
        for role, ref in (("agent", event.agent), ("object", event.object)):
            if not ref:
                continue
            target = resolve_endpoint(ref)
            if not target:
                target = _ensure_entity(
                    store, index, ref, "unknown", record.id, created=created
                )
            edges.append((role, target))
        for role, target in edges:
            relation = store.add_relation(
                event_entity.id, role, target, record.id, event.confidence,
                kind="event", extractor=extractor_name,
                extractor_version=extractor_version,
            )
            index.add_relation(relation)
            mentioned.add(target)
            relation_count += 1

    for item in extraction.relations:
        source = resolve_endpoint(item.source)
        if not source:
            source = _ensure_entity(
                store, index, item.source, "unknown", record.id, created=created
            )
        target = resolve_endpoint(item.target)
        if not target:
            target = _ensure_entity(
                store, index, item.target, "unknown", record.id, created=created
            )
        relation = store.add_relation(
            source, item.relation, target, record.id, item.confidence,
            kind=item.kind, extractor=extractor_name,
            extractor_version=extractor_version,
        )
        index.add_relation(relation)
        mentioned.add(source)
        mentioned.add(target)
        relation_count += 1

    for raw in extraction.mentions:
        entity_id = resolve_endpoint(raw)
        if not entity_id:
            entity_id = _ensure_entity(
                store, index, raw, "unknown", record.id, created=created
            )
        mentioned.add(entity_id)

    for entity_id in sorted(mentioned):
        store.add_mention(record.id, entity_id)

    return {
        "entities": len(mentioned),
        "relations": relation_count,
        "created_entities": len(created),
        "empty": int(not extraction.entities and not extraction.events and not extraction.relations),
    }


def _retry_or_fail(
    store: GraphStore,
    memory_id: str,
    error: str,
    *,
    tag: str,
    attempts: int,
    max_attempts: int,
) -> str:
    """Apply the retry policy: transient stays pending, then becomes failed."""
    next_attempts = attempts + 1
    if next_attempts >= max(1, max_attempts):
        store.mark_failed(memory_id, f"{error} (after {next_attempts} attempts)", extractor=tag)
        store.drop_pending(memory_id)
        return "failed"
    store.mark_pending(memory_id, error, extractor=tag, attempts=next_attempts)
    return "pending"


def _write_meta(
    store: GraphStore,
    *,
    tag: str,
    extractor_name: str,
    extractor_version: str,
    extract_types: Iterable[str] | None = None,
    last_memory_id: str = "",
    resolver_version: str = GRAPH_RESOLVER_VERSION,
    source: dict[str, int] | None = None,
) -> dict[str, Any]:
    counts = store.counts()
    meta = {
        "version": GRAPH_SCHEMA_VERSION,
        "schema_version": GRAPH_SCHEMA_VERSION,
        "extractor": extractor_name,
        "extractor_version": extractor_version,
        "resolver_version": resolver_version,
        "tag": tag,
        "built_at": _now(),
        "extract_types": sorted(extract_types) if extract_types else sorted(DURABLE_TYPES),
        "source": source or {},
        "counts": counts,
        "last_memory_id": last_memory_id,
    }
    store.write_meta(meta)
    return meta


def _apply_validated(
    store: GraphStore,
    index: GraphIndex,
    record: Any,
    extraction: Extraction,
    *,
    tag: str,
    extractor_name: str,
    extractor_version: str,
    resolver: Any,
    resolver_version: str,
) -> dict[str, Any]:
    """Project one validated extraction, mark it and refresh meta."""
    result = project_extraction(
        store, index, record, extraction, tag=tag, resolver=resolver,
        extractor_name=extractor_name, extractor_version=extractor_version,
        resolver_version=resolver_version,
    )
    store.mark_extracted(
        record.id, result["entities"], result["relations"], extractor=tag
    )
    store.drop_pending(record.id)
    _write_meta(
        store,
        tag=tag,
        extractor_name=extractor_name or "custom",
        extractor_version=extractor_version,
        resolver_version=resolver_version,
        last_memory_id=record.id,
    )
    return {"ok": True, "status": "extracted", **result}


def apply_record_extraction(
    store: GraphStore,
    record: Any,
    fn: Extractor,
    *,
    tag: str,
    extractor_name: str = "",
    extractor_version: str = "",
    resolver: Any = None,
    resolver_version: str = GRAPH_RESOLVER_VERSION,
    index: GraphIndex | None = None,
    max_attempts: int = MAX_ATTEMPTS,
) -> dict[str, Any]:
    """Extract and project a single record with retry policy.

    Expected failures (``ExtractionError``: schema, empty completion, API
    timeout) follow the pending/failed policy; unexpected exceptions fail
    immediately. The tape is never touched here.
    """
    if record.id in store.extracted_ids(tag):
        return {
            "ok": True,
            "status": "skipped",
            "entities": 0,
            "relations": 0,
            "created_entities": 0,
            "empty": 0,
        }
    attempts = store.pending_attempts(record.id, extractor=tag)
    try:
        raw = fn(record)
        extraction = (
            raw
            if isinstance(raw, Extraction)
            else Extraction.from_obj(
                raw,
                memory_id=record.id,
                extractor=extractor_name,
                extractor_version=extractor_version,
            )
        )
    except ExtractionError as exc:
        status = _retry_or_fail(
            store, record.id, str(exc), tag=tag, attempts=attempts,
            max_attempts=max_attempts,
        )
        return {"ok": False, "status": status, "error": str(exc)}
    except Exception as exc:  # unexpected: definitive
        store.mark_failed(record.id, str(exc), extractor=tag)
        store.drop_pending(record.id)
        return {"ok": False, "status": "failed", "error": str(exc)}

    idx = index if index is not None else store.index()
    return _apply_validated(
        store, idx, record, extraction, tag=tag, extractor_name=extractor_name,
        extractor_version=extractor_version, resolver=resolver,
        resolver_version=resolver_version,
    )


def apply_batch_extraction(
    store: GraphStore,
    records: list[Any],
    batch_fn: Callable[[list[Any]], dict[str, Any]],
    *,
    tag: str,
    extractor_name: str = "",
    extractor_version: str = "",
    resolver: Any = None,
    resolver_version: str = GRAPH_RESOLVER_VERSION,
    index: GraphIndex | None = None,
    max_attempts: int = MAX_ATTEMPTS,
) -> dict[str, Any]:
    """One transport call for many records; one idempotency unit each.

    Batching is only a transport optimization: each record is still validated,
    projected and marked independently. A record missing from the response is
    retried per the pending/failed policy, and the extractor can never touch a
    memory that was not in this batch.
    """
    records = [r for r in records if r.id not in store.extracted_ids(tag)]
    if not records:
        return {
            "ok": True, "status": "skipped", "applied": 0,
            "pending": 0, "failed": 0, "created_entities": 0, "empty": 0,
            "new_mentions": 0,
        }
    idx = index if index is not None else store.index()

    def retry_all(error: str) -> dict[str, Any]:
        pending = 0
        for record in records:
            status = _retry_or_fail(
                store, record.id, error, tag=tag,
                attempts=store.pending_attempts(record.id, extractor=tag),
                max_attempts=max_attempts,
            )
            pending += int(status == "pending")
        return {
            "ok": False, "status": "pending" if pending else "failed",
            "applied": 0, "pending": pending, "failed": len(records) - pending,
            "created_entities": 0, "empty": 0, "new_mentions": 0,
        }

    try:
        results = batch_fn(records)
    except ExtractionError as exc:
        return retry_all(str(exc))
    except Exception as exc:  # unexpected: definitive
        for record in records:
            store.mark_failed(record.id, str(exc), extractor=tag)
            store.drop_pending(record.id)
        return {
            "ok": False, "status": "failed", "applied": 0,
            "pending": 0, "failed": len(records), "created_entities": 0,
            "empty": 0, "new_mentions": 0,
        }

    if not isinstance(results, dict):
        results = {}

    applied = pending = failed = 0
    created_entities = empty = mentions = 0
    for record in records:
        extraction = results.get(record.id)
        if extraction is not None and not isinstance(extraction, Extraction):
            try:
                extraction = Extraction.from_obj(
                    extraction,
                    memory_id=record.id,
                    extractor=extractor_name,
                    extractor_version=extractor_version,
                )
            except Exception:
                extraction = None
        if extraction is None:
            status = _retry_or_fail(
                store, record.id, "missing from batch response", tag=tag,
                attempts=store.pending_attempts(record.id, extractor=tag),
                max_attempts=max_attempts,
            )
            pending += int(status == "pending")
            failed += int(status == "failed")
            continue
        outcome = _apply_validated(
            store, idx, record, extraction, tag=tag, extractor_name=extractor_name,
            extractor_version=extractor_version, resolver=resolver,
            resolver_version=resolver_version,
        )
        applied += 1
        created_entities += int(outcome.get("created_entities") or 0)
        mentions += int(outcome.get("entities") or 0)
        empty += int(outcome.get("empty") or 0)
    return {
        "ok": True, "status": "extracted", "applied": applied,
        "pending": pending, "failed": failed,
        "created_entities": created_entities, "empty": empty,
        "new_mentions": mentions,
    }


def _chunk_records(
    records: list[Any], batch_size: int, batch_max_chars: int
) -> list[list[Any]]:
    """Split records into batches honoring both the count and char limits."""
    batches: list[list[Any]] = []
    current: list[Any] = []
    used = 0
    for record in records:
        cost = len(record.text()) if hasattr(record, "text") else len(str(record))
        overflow = batch_max_chars and current and used + cost > batch_max_chars
        if current and (len(current) >= max(1, batch_size) or overflow):
            batches.append(current)
            current = []
            used = 0
        current.append(record)
        used += cost
    if current:
        batches.append(current)
    return batches


def _swap_directories(target: Path, building: Path) -> None:
    """Atomically replace ``target`` with a fully built ``building`` dir."""
    import shutil

    backup = target.with_name(target.name + ".previous")
    shutil.rmtree(backup, ignore_errors=True)
    if target.exists():
        target.rename(backup)
    building.rename(target)
    shutil.rmtree(backup, ignore_errors=True)


def _build_into(
    tape: Any,
    store: GraphStore,
    spec: ExtractorSpec,
    *,
    name: str,
    tag: str,
    types: set[str],
    resolver: Any,
    resolver_version: str,
    max_attempts: int,
    batch_size: int,
    batch_max_chars: int,
    batch_fn: Callable[[list[Any]], dict[str, Any]] | None,
) -> dict[str, Any]:
    records = tape.read()
    index = store.index()
    done = store.extracted_ids(tag)
    if resolver is not None and hasattr(resolver, "bind"):
        resolver.bind(index)

    eligible = [r for r in records if r.type in types and not r.derived_from]
    pending_records = [r for r in eligible if r.id not in done]
    stats: dict[str, int] = {
        "considered": len(pending_records),
        "extracted": 0,
        "skipped": len(eligible) - len(pending_records),
        "failed": 0,
        "pending": 0,
        "empty": 0,
        "new_mentions": 0,
    }
    created_entities = 0

    use_batches = batch_fn is not None and batch_size > 1 and len(pending_records) > 1
    if use_batches:
        for batch in _chunk_records(pending_records, batch_size, batch_max_chars):
            outcome = apply_batch_extraction(
                store, batch, batch_fn, tag=tag, extractor_name=name,
                extractor_version=spec.version, resolver=resolver,
                resolver_version=resolver_version, index=index,
                max_attempts=max_attempts,
            )
            stats["extracted"] += int(outcome.get("applied") or 0)
            stats["pending"] += int(outcome.get("pending") or 0)
            stats["failed"] += int(outcome.get("failed") or 0)
            stats["empty"] += int(outcome.get("empty") or 0)
            stats["new_mentions"] += int(outcome.get("new_mentions") or 0)
            created_entities += int(outcome.get("created_entities") or 0)
            if outcome.get("status") == "skipped":
                stats["skipped"] += len(batch)
    else:
        for record in pending_records:
            outcome = apply_record_extraction(
                store, record, spec.fn, tag=tag, extractor_name=name,
                extractor_version=spec.version, resolver=resolver,
                resolver_version=resolver_version, index=index,
                max_attempts=max_attempts,
            )
            if outcome["status"] == "extracted":
                stats["extracted"] += 1
                created_entities += int(outcome.get("created_entities") or 0)
                stats["new_mentions"] += int(outcome.get("entities") or 0)
                stats["empty"] += int(outcome.get("empty") or 0)
            elif outcome["status"] == "pending":
                stats["pending"] += 1
            elif outcome["status"] == "failed":
                stats["failed"] += 1
            else:
                stats["skipped"] += 1

    source = {
        "tape_records_seen": len(records),
        "eligible_records": len(eligible),
        "extracted_records": stats["extracted"],
    }
    _write_meta(
        store,
        tag=tag,
        extractor_name=name,
        extractor_version=spec.version,
        extract_types=types,
        resolver_version=resolver_version,
        source=source,
        last_memory_id=str(getattr(tape.last(), "id", "") or ""),
    )
    return {
        "ok": True,
        "extractor": tag,
        "created_entities": created_entities,
        **stats,
        "counts": store.counts(),
    }


def build_graph(
    tape: Any,
    store: GraphStore,
    extractor: Extractor | ExtractorSpec,
    *,
    extract_types: Iterable[str] | str | None = None,
    rebuild: bool = False,
    extractor_name: str = "",
    resolver: Any = None,
    resolver_version: str = GRAPH_RESOLVER_VERSION,
    max_attempts: int = MAX_ATTEMPTS,
    batch_size: int = 1,
    batch_max_chars: int = 0,
    batch_fn: Callable[[list[Any]], dict[str, Any]] | None = None,
    atomic: bool = True,
) -> dict[str, Any]:
    """Extract durable tape records into the graph store.

    ``tape`` is only read. A rebuild with a different extractor tag is
    required when the recorded projection was built by another extractor
    version. ``atomic`` rebuilds into ``graph.building/`` and swaps only after
    a complete, validated run, so an interrupted rebuild never destroys the
    previous projection. ``batch_fn`` (e.g. ``GraphExtractor.extract_batch``)
    is a transport optimization: each record keeps its own idempotency unit.
    """
    spec = extractor if isinstance(extractor, ExtractorSpec) else ExtractorSpec(extractor)
    name = extractor_name or ("noop" if spec.fn is noop_extractor else "custom")
    tag = f"{name}/{spec.version}"
    types = parse_types(extract_types) if extract_types else set(DURABLE_TYPES)

    recorded_tag = str(store.meta().get("tag") or "")
    if recorded_tag and recorded_tag != tag and not rebuild:
        return {
            "ok": False,
            "error": f"graph was built with {recorded_tag}; rebuild required for {tag}",
            "built_tag": recorded_tag,
            "requested_tag": tag,
        }

    target = store
    building: GraphStore | None = None
    if rebuild and atomic:
        building = GraphStore(Path(str(store.directory) + ".building"))
        building.clear()
        building.copy_reviews_from(store)
        target = building
    elif rebuild:
        store.clear()

    try:
        result = _build_into(
            tape, target, spec, name=name, tag=tag, types=types, resolver=resolver,
            resolver_version=resolver_version, max_attempts=max_attempts,
            batch_size=batch_size, batch_max_chars=batch_max_chars, batch_fn=batch_fn,
        )
    except Exception as exc:
        if building is not None:
            return {
                "ok": False,
                "error": f"rebuild failed; previous graph kept: {exc}",
                "building_dir": str(building.directory),
            }
        return {"ok": False, "error": str(exc)}

    if building is not None:
        _swap_directories(store.directory, building.directory)
        result["rebuilt"] = True
    return result


def graph_status(
    store: GraphStore,
    tape: Any = None,
    *,
    extract_types: Iterable[str] | str | None = None,
    extractor_tag: str = "",
) -> dict[str, Any]:
    """Summary of the projection, plus pending records for the current tag."""
    meta = store.meta()
    result: dict[str, Any] = {
        "ok": True,
        "path": str(store.directory),
        "built": store.exists(),
        "meta": meta,
        "counts": store.counts(),
    }
    if tape is not None:
        types = parse_types(extract_types) if extract_types else set(DURABLE_TYPES)
        durable = [r.id for r in tape.read() if r.type in types and not r.derived_from]
        done = store.extracted_ids(extractor_tag) if extractor_tag else set()
        result["durable_records"] = len(durable)
        result["pending_records"] = (
            len([mid for mid in durable if mid not in done]) if extractor_tag else len(durable)
        )
        result["extractor_tag"] = extractor_tag
    result["failed"] = store.failed_rows()[-20:]
    result["pending"] = store.pending_rows()[-20:]
    return result


def explain_relation(store: GraphStore, tape: Any, relation_id: str) -> dict[str, Any]:
    """Walk a relation back to its source memory (provenance)."""
    relation = next((r for r in store.relations() if r.id == relation_id), None)
    if relation is None:
        return {"ok": False, "error": f"unknown relation: {relation_id}"}
    entities = {e.id: e for e in store.entities()}
    record = next((r for r in tape.read() if r.id == relation.memory_id), None)
    return {
        "ok": True,
        "relation": relation.to_dict(),
        "source": entities[relation.source].to_dict() if relation.source in entities else None,
        "target": entities[relation.target].to_dict() if relation.target in entities else None,
        "aliases": [
            a.to_dict()
            for a in store.aliases()
            if a.entity_id in {relation.source, relation.target}
        ],
        "memory": record.to_dict() if record is not None else None,
    }
