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
GRAPH_SCHEMA_VERSION = 3
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


def format_document_id(num: int) -> str:
    return f"D{num:04d}"


def parse_document_id(doc_id: str) -> int:
    m = re.match(r"^D(\d+)$", str(doc_id or "").strip())
    if not m:
        raise ValueError(f"invalid document id: {doc_id!r}")
    return int(m.group(1))


def _parse_span(raw: Any) -> tuple[int, int]:
    if isinstance(raw, (list, tuple)) and len(raw) == 2:
        try:
            return (int(raw[0]), int(raw[1]))
        except (TypeError, ValueError):
            pass
    return ()


def _parse_spans(raw: Any) -> list[tuple[int, int]]:
    if not isinstance(raw, (list, tuple)):
        return []
    return [span for raw_span in raw if (span := _parse_span(raw_span))]


def _parse_evidence(raw: Any) -> tuple[dict[str, Any], ...]:
    """Multi-span provenance: ``[{"memory_id": ..., "span": [s, e]}, ...]``."""
    if not isinstance(raw, (list, tuple)):
        return ()
    out: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        memory_id = str(item.get("memory_id") or "")
        span = _parse_span(item.get("span"))
        if not memory_id and not span:
            continue
        ev: dict[str, Any] = {}
        if memory_id:
            ev["memory_id"] = memory_id
        if span:
            ev["span"] = [span[0], span[1]]
        out.append(ev)
    return tuple(out)


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
    source_document: str = ""
    source_span: tuple[int, int] = ()
    extraction_scope: str = ""

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "id": self.id,
            "name": self.name,
            "type": self.type,
            "memory_id": self.memory_id,
            "created_at": self.created_at,
        }
        if self.source_document:
            d["source_document"] = self.source_document
        if self.source_span:
            d["source_span"] = [self.source_span[0], self.source_span[1]]
        if self.extraction_scope:
            d["extraction_scope"] = self.extraction_scope
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GraphEntity":
        return cls(
            id=str(data.get("id") or ""),
            name=str(data.get("name") or ""),
            type=str(data.get("type") or "unknown"),
            memory_id=str(data.get("memory_id") or ""),
            created_at=str(data.get("created_at") or ""),
            source_document=str(data.get("source_document") or ""),
            source_span=_parse_span(data.get("source_span")),
            extraction_scope=str(data.get("extraction_scope") or ""),
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
    source_document: str = ""
    source_span: tuple[int, int] = ()
    evidence: tuple[dict[str, Any], ...] = ()
    extraction_scope: str = ""

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "id": self.id,
            "source": self.source,
            "relation": self.relation,
            "target": self.target,
            "memory_id": self.memory_id,
            "confidence": self.confidence,
            "kind": self.kind,
            "extractor": self.extractor,
            "extractor_version": self.extractor_version,
        }
        if self.source_document:
            d["source_document"] = self.source_document
        if self.source_span:
            d["source_span"] = [self.source_span[0], self.source_span[1]]
        if self.evidence:
            d["evidence"] = [dict(ev) for ev in self.evidence]
        if self.extraction_scope:
            d["extraction_scope"] = self.extraction_scope
        return d

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
            source_document=str(data.get("source_document") or ""),
            source_span=_parse_span(data.get("source_span")),
            evidence=_parse_evidence(data.get("evidence")),
            extraction_scope=str(data.get("extraction_scope") or ""),
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
    source_document: str = ""
    span: tuple[int, int] = ()
    extraction_scope: str = ""

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "memory_id": self.memory_id,
            "entity_id": self.entity_id,
            "confidence": self.confidence,
        }
        if self.source_document:
            d["source_document"] = self.source_document
        if self.span:
            d["span"] = [self.span[0], self.span[1]]
        if self.extraction_scope:
            d["extraction_scope"] = self.extraction_scope
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GraphMention":
        return cls(
            memory_id=str(data.get("memory_id") or ""),
            entity_id=str(data.get("entity_id") or ""),
            confidence=_clamp(data.get("confidence"), 0.8),
            source_document=str(data.get("source_document") or ""),
            span=_parse_span(data.get("span")),
            extraction_scope=str(data.get("extraction_scope") or ""),
        )


@dataclass
class DocumentRecord:
    """Registered document (identity + provenance of an ingested .txt).

    ``source`` is the stable content key ``name#hash`` (same key used by the
    ``attachment`` records on the tape), so a subgraph can be rebuilt by
    filtering graph rows by document provenance. ``spans`` are the chunk
    offsets ``(start, end)`` produced by :func:`chunk_spans`, listed in order.
    """

    id: str
    source: str
    name: str
    hash: str
    path: str
    original: str = ""
    chunks: int = 0
    spans: list[tuple[int, int]] = field(default_factory=list)
    extractor: str = ""
    status: str = "registered"
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "id": self.id,
            "source": self.source,
            "name": self.name,
            "hash": self.hash,
            "path": self.path,
            "chunks": int(self.chunks),
            "spans": [[s, e] for s, e in self.spans],
            "extractor": self.extractor,
            "status": self.status,
            "created_at": self.created_at,
        }
        if self.original:
            d["original"] = self.original
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DocumentRecord":
        return cls(
            id=str(data.get("id") or ""),
            source=str(data.get("source") or ""),
            name=str(data.get("name") or ""),
            hash=str(data.get("hash") or ""),
            path=str(data.get("path") or ""),
            original=str(data.get("original") or ""),
            chunks=int(data.get("chunks") or 0),
            spans=_parse_spans(data.get("spans")),
            extractor=str(data.get("extractor") or ""),
            status=str(data.get("status") or "registered"),
            created_at=str(data.get("created_at") or ""),
        )


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
    evidence: tuple[dict[str, Any], ...] = ()


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
    scope: str = ""
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
        scope: str = "",
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
                    evidence=_parse_evidence(raw.get("evidence")),
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
            scope=str(obj.get("scope") or scope or "").strip().lower()[:20],
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


class _SpecDocumentExtractor:
    """Adapter so a plain :class:`ExtractorSpec` can drive the D5 document
    passes (chunk scope from ``fn``; window scope skipped when the caller did
    not supply a real window extractor)."""

    def __init__(self, fn: Extractor, batch_fn: Callable[[list[Any]], dict[str, Any]] | None,
                 name: str, version: str, tag: str) -> None:
        self.fn = fn
        self.batch_fn = batch_fn
        self.name = name
        self.version = version
        self.tag = tag

    def extract(self, record: Any) -> Any:
        return self.fn(record)

    def extract_batch(self, records: list[Any]) -> dict[str, Any]:
        if self.batch_fn is not None:
            return self.batch_fn(records)
        return {record.id: self.extract(record) for record in records}

    @property
    def extract_window(self) -> None:
        return None


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

    def prune_to_active(self, active_ids: set[str]) -> dict[str, int]:
        """Drop projections whose evidence exists only in inactive records.

        Read-time filter (the store stays append-only): superseded/deleted
        records cannot route traversal to active memories through entities or
        relations whose evidence died with them. Returns removed counts.
        """
        def alive(obj: Any) -> bool:
            candidates = {str(getattr(obj, "memory_id", "") or "")}
            candidates.update(str(item.get("memory_id") or "")
                              for item in getattr(obj, "evidence", ()) or ())
            return bool((candidates - {""}) & active_ids)

        surviving_relations = {rid: rel for rid, rel in self.relations.items()
                               if alive(rel)}
        endpoints = {node for rel in surviving_relations.values()
                     for node in (rel.source, rel.target)}
        mentioned = {eid for eid, mems in self.entity_memories.items()
                     if mems & active_ids}
        surviving_entities = {eid: ent for eid, ent in self.entities.items()
                              if eid in endpoints or eid in mentioned}
        surviving_relations = {
            rid: rel for rid, rel in surviving_relations.items()
            if rel.source in surviving_entities
            and rel.target in surviving_entities}
        removed = {
            "entities": len(self.entities) - len(surviving_entities),
            "relations": len(self.relations) - len(surviving_relations),
        }
        self.entities = surviving_entities
        self.relations = surviving_relations
        self.by_norm = {}
        for entity in self.entities.values():
            self.by_norm.setdefault(normalize_name(entity.name), entity.id)
        self.out_edges = {}
        self.in_edges = {}
        for relation in self.relations.values():
            self.out_edges.setdefault(relation.source, []).append(relation)
            self.in_edges.setdefault(relation.target, []).append(relation)
        self.memory_entities = {
            mid: {eid for eid in ents if eid in self.entities}
            for mid, ents in self.memory_entities.items() if mid in active_ids}
        self.memory_entities = {mid: ents for mid, ents
                                in self.memory_entities.items() if ents}
        self.entity_memories = {
            eid: {mid for mid in mems if mid in active_ids}
            for eid, mems in self.entity_memories.items()
            if eid in self.entities}
        self.entity_memories = {eid: mems for eid, mems
                                in self.entity_memories.items() if mems}
        self.mention_confidence = {
            key: value for key, value in self.mention_confidence.items()
            if key[0] in active_ids and key[1] in self.entities}
        return removed

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
        "documents.jsonl",
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
        source_document: str = "",
        source_span: tuple[int, int] = (),
        extraction_scope: str = "",
    ) -> GraphEntity:
        if not entity_id:
            entity_id = f"E{self.index().max_entity_num + 1:04d}"
        entity = GraphEntity(
            id=entity_id,
            name=str(name).strip(),
            type=str(entity_type or "unknown").strip() or "unknown",
            memory_id=memory_id,
            created_at=_now(),
            source_document=source_document or "",
            source_span=(int(source_span[0]), int(source_span[1])) if source_span else (),
            extraction_scope=extraction_scope or "",
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
        source_document: str = "",
        source_span: tuple[int, int] = (),
        evidence: Iterable[dict[str, Any]] = (),
        extraction_scope: str = "",
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
            source_document=source_document or "",
            source_span=(int(source_span[0]), int(source_span[1])) if source_span else (),
            evidence=tuple(
                ev for ev in (_parse_evidence(list(evidence)) if evidence else ())
            ),
            extraction_scope=extraction_scope or "",
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

    def add_mention(
        self,
        memory_id: str,
        entity_id: str,
        confidence: float = 0.8,
        *,
        source_document: str = "",
        span: tuple[int, int] = (),
        extraction_scope: str = "",
    ) -> GraphMention:
        mention = GraphMention(
            memory_id=memory_id,
            entity_id=entity_id,
            confidence=max(0.0, min(1.0, float(confidence))),
            source_document=source_document or "",
            span=(int(span[0]), int(span[1])) if span else (),
            extraction_scope=extraction_scope or "",
        )
        self._append("mentions.jsonl", mention.to_dict())
        return mention

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
        return [GraphMention.from_dict(d) for d in self._load("mentions.jsonl")]

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
            "documents": len(self.documents()),
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

    # --------------------------------------------------- documents (D2)

    def documents(self) -> list[DocumentRecord]:
        """Latest registered state per document id (append-only history)."""
        latest: dict[str, DocumentRecord] = {}
        for row in self._load("documents.jsonl"):
            record = DocumentRecord.from_dict(row)
            if record.id:
                latest[record.id] = record
        return list(latest.values())

    def next_document_num(self) -> int:
        numbers = []
        for row in self._load("documents.jsonl"):
            match = re.match(r"^D(\d+)$", str(row.get("id") or ""))
            if match:
                numbers.append(int(match.group(1)))
        return max(numbers, default=0) + 1

    def document_by_id(self, doc_id: str) -> DocumentRecord | None:
        return next((d for d in self.documents() if d.id == doc_id), None)

    def document_by_source(self, source: str) -> DocumentRecord | None:
        return next((d for d in self.documents() if d.source == source), None)

    def add_document(
        self,
        *,
        source: str,
        name: str,
        hash: str,
        path: str,
        original: str = "",
        spans: Iterable[tuple[int, int]] = (),
        extractor: str = "",
        status: str = "registered",
        chunks: int = 0,
    ) -> tuple[DocumentRecord, bool]:
        """Register a document, giving it a stable ``D####`` identity.

        The identity is stable per ``source`` (the ``name#hash`` content key):
        registering an already-known source returns the existing record
        (``created=False``) instead of duplicating it. ``original`` is the
        path of the preserved copy in ``<root>/documents/`` (hash-validated on
        rebuild).
        """
        source = str(source or "").strip()
        name = str(name or "").strip()
        if not (source and name and (hash or "").strip() and str(path or "").strip()):
            raise ValueError(
                "add_document requires source, name, hash and path"
            )
        existing = self.document_by_source(source)
        if existing is not None:
            return existing, False
        span_list = [[int(s), int(e)] for s, e in spans if e >= s]
        record = DocumentRecord(
            id=format_document_id(self.next_document_num()),
            source=source,
            name=name,
            hash=str(hash).strip(),
            path=str(path).strip(),
            original=str(original or "").strip(),
            chunks=int(chunks) if chunks else len(span_list),
            spans=[(s, e) for s, e in span_list],
            extractor=extractor,
            status=status,
            created_at=_now(),
        )
        self._append("documents.jsonl", record.to_dict())
        return record, True

    def update_document(
        self,
        doc_id: str,
        *,
        status: str | None = None,
        extractor: str | None = None,
        chunks: int | None = None,
    ) -> DocumentRecord | None:
        """Append a new state row for a registered document (latest wins)."""
        current = self.document_by_id(doc_id)
        if current is None:
            return None
        row = dict(current.to_dict())
        if status is not None:
            row["status"] = status
        if extractor is not None:
            row["extractor"] = extractor
        if chunks is not None:
            row["chunks"] = int(chunks)
        row["created_at"] = _now()
        self._append("documents.jsonl", row)
        return DocumentRecord.from_dict(row)

    def copy_documents_from(self, other: "GraphStore") -> int:
        """Carry the document registry into a fresh projection dir."""
        import shutil

        source = other._path("documents.jsonl")
        if not source.exists():
            return 0

        self.directory.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, self._path("documents.jsonl"))
        return 1


def _ensure_entity(
    store: GraphStore,
    index: GraphIndex,
    name: str,
    entity_type: str,
    memory_id: str,
    *,
    created: list[str],
    source_document: str = "",
    source_span: tuple[int, int] = (),
    extraction_scope: str = "",
) -> str:
    entity_id = index.resolve(name)
    if entity_id:
        return entity_id
    entity_id = f"E{index.max_entity_num + 1:04d}"
    entity = store.add_entity(
        name, entity_type, memory_id, entity_id=entity_id,
        source_document=source_document or "",
        source_span=source_span or (),
        extraction_scope=extraction_scope,
    )
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
    resolution: Any = None,
    extraction_scope: str = "",
) -> str:
    """Resolve/create one entity, honouring the resolver's confidence bands.

    ``resolution`` may carry a precomputed (batched) decision; the exact-name
    check still runs first so entities created earlier in the same extraction
    are reused.
    """
    if resolution is None and resolver is not None:
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
        store, index, name, entity_type, record.id, created=created,
        source_document=str(getattr(record, "source_document", "") or ""),
        source_span=tuple(getattr(record, "source_span", ()) or ()),
        extraction_scope=extraction_scope,
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
    scope: str = "",
    emit_mentions: bool = True,
) -> dict[str, int]:
    """Mutate the projection from a fully validated ``Extraction``.

    The resolver maps semantic refs (``e1``/``ev1``) to ``E####``; the LLM
    never chooses graph ids. Events become ``type=event`` entities with
    ``agent``/``action``/``object`` edges, each relation carrying provenance.

    ``scope``/``emit_mentions`` are window-scope knobs: ``scope`` is an *audit*
    marker (``chunk``/``document``) that never affects resolution or confidence;
    ``emit_mentions=False`` skips the member-mention loop for window passes
    (mentions stay a chunk-level, memory-keyed provenance). Relation evidence is
    taken from ``ExtractedRelation.evidence`` when present (long-range window
    relations reference every supporting member); otherwise it falls back to
    the record's own ``source_document``/``source_span``.
    """
    if resolver is not None and hasattr(resolver, "bind"):
        resolver.bind(index)

    local: dict[str, str] = {}
    refs: dict[str, str] = {}
    mentioned: set[str] = set()
    created: list[str] = []
    relation_count = 0

    # Documental provenance (D1 fields on the record): when the projection runs
    # over document chunks, every generated row carries the document and span;
    # durable tape records never set these, so the legacy projection stays
    # byte-identical.
    doc = str(getattr(record, "source_document", "") or "")
    span = tuple(getattr(record, "source_span", ()) or ())
    record_evidence: tuple[dict[str, Any], ...] = ()
    if doc:
        memory_id = str(getattr(record, "id", "") or "")
        record_evidence = (
            ({"memory_id": memory_id, "span": [span[0], span[1]]},) if len(span) == 2
            else ({"memory_id": memory_id},)
        )

    precomputed: list[Any] | None = None
    if resolver is not None and extraction.entities and hasattr(resolver, "resolve_batch"):
        try:
            precomputed = resolver.resolve_batch(
                [{"name": item.name, "type": item.type} for item in extraction.entities]
            )
        except Exception:
            precomputed = None

    for position, item in enumerate(extraction.entities):
        entity_id = _resolve_with_resolver(
            store, index, resolver, item.name, item.type, record,
            created=created, extractor_name=extractor_name,
            extractor_version=extractor_version,
            resolver_version=resolver_version,
            resolution=precomputed[position] if precomputed is not None else None,
            extraction_scope=scope,
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
            f"{event.action} ({record.id})", "event", record.id,
            source_document=doc, source_span=span,
            extraction_scope=scope,
        )
        index.add_entity(event_entity)
        created.append(event_entity.id)
        refs.setdefault(event.ref, event_entity.id)
        mentioned.add(event_entity.id)

        action_entity = action_entities.get(event.action)
        if not action_entity:
            action_entity = _ensure_entity(
                store, index, event.action, "action", record.id, created=created,
                source_document=doc, source_span=span,
                extraction_scope=scope,
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
                    store, index, ref, "unknown", record.id, created=created,
                    source_document=doc, source_span=span,
                    extraction_scope=scope,
                )
            edges.append((role, target))
        for role, target in edges:
            relation = store.add_relation(
                event_entity.id, role, target, record.id, event.confidence,
                kind="event", extractor=extractor_name,
                extractor_version=extractor_version,
                source_document=doc, source_span=span,
                evidence=record_evidence,
                extraction_scope=scope,
            )
            index.add_relation(relation)
            mentioned.add(target)
            relation_count += 1

    for item in extraction.relations:
        source = resolve_endpoint(item.source)
        if not source:
            source = _ensure_entity(
                store, index, item.source, "unknown", record.id, created=created,
                source_document=doc, source_span=span,
                extraction_scope=scope,
            )
        target = resolve_endpoint(item.target)
        if not target:
            target = _ensure_entity(
                store, index, item.target, "unknown", record.id, created=created,
                source_document=doc, source_span=span,
                extraction_scope=scope,
            )
        relation = store.add_relation(
            source, item.relation, target, record.id, item.confidence,
            kind=item.kind, extractor=extractor_name,
            extractor_version=extractor_version,
            source_document=doc, source_span=span,
            evidence=tuple(item.evidence) if item.evidence else record_evidence,
            extraction_scope=scope,
        )
        index.add_relation(relation)
        mentioned.add(source)
        mentioned.add(target)
        relation_count += 1

    for raw in extraction.mentions:
        entity_id = resolve_endpoint(raw)
        if not entity_id:
            entity_id = _ensure_entity(
                store, index, raw, "unknown", record.id, created=created,
                source_document=doc, source_span=span,
                extraction_scope=scope,
            )
        mentioned.add(entity_id)

    if emit_mentions:
        for entity_id in sorted(mentioned):
            store.add_mention(
                record.id, entity_id, source_document=doc, span=span,
                extraction_scope=scope,
            )

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
    scope: str = "",
) -> dict[str, Any]:
    """Project one validated extraction, mark it and refresh meta."""
    result = project_extraction(
        store, index, record, extraction, tag=tag, resolver=resolver,
        extractor_name=extractor_name, extractor_version=extractor_version,
        resolver_version=resolver_version, scope=scope,
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
    scope: str = "",
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
        resolver_version=resolver_version, scope=scope,
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
    scope: str = "",
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
            resolver_version=resolver_version, scope=scope,
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


# ----------------------------------------------------------- window scope (D4)


@dataclass(frozen=True)
class WindowRecord:
    """One document-level extraction unit: the window and its member chunks.

    ``id`` is the stable idempotency key (``D####|wNN``) used for the
    pending/failed/retry and ``extracted.jsonl`` bookkeeping; ``members`` are
    the chunk ``MemoryRecord``s that compose the window, in source order.
    """

    id: str
    members: tuple[Any, ...] = ()
    source_document: str = ""
    source_span: tuple[int, int] = ()


def _resolve_window_evidence(
    extraction: Extraction, window: WindowRecord
) -> Extraction:
    """Normalize relation evidence to the window's REAL memory members.

    Guard (D4): the model must never carry evidence outside the window — even
    if it cites something plausible. Any ``memory_id`` not in ``window.members``
    is dropped. A relation left without any valid evidence (or the extractor
    omitting evidence) conservatively carries ALL members ``{memory_id, span}``,
    so a long-range relation always lists every supporting span.
    """
    member_spans: dict[str, tuple[int, int]] = {}
    for member in window.members:
        mid = str(getattr(member, "id", "") or "")
        span = tuple(getattr(member, "source_span", ()) or ())
        if mid and len(span) == 2:
            member_spans[mid] = (int(span[0]), int(span[1]))
    default_evidence = tuple(
        {"memory_id": mid, "span": [span[0], span[1]]}
        for mid, span in member_spans.items()
    )

    relations: list[ExtractedRelation] = []
    for relation in extraction.relations:
        evidence: list[dict[str, Any]] = []
        for ev in relation.evidence:
            mid = str(ev.get("memory_id") or "")
            if mid not in member_spans:
                continue  # never project evidence outside the window
            span = ev.get("span")
            if not (isinstance(span, (list, tuple)) and len(span) == 2):
                span = member_spans[mid]
            evidence.append(
                {"memory_id": mid, "span": [int(span[0]), int(span[1])]}
            )
        relations.append(
            ExtractedRelation(
                relation.source,
                relation.relation,
                relation.target,
                relation.confidence,
                relation.kind,
                tuple(evidence) if evidence else default_evidence,
            )
        )
    return Extraction(
        entities=extraction.entities,
        events=extraction.events,
        relations=tuple(relations),
        mentions=extraction.mentions,
        confidence=extraction.confidence,
        kind=extraction.kind,
        scope=extraction.scope,
        memory_id=extraction.memory_id,
        extractor=extraction.extractor,
        extractor_version=extraction.extractor_version,
    )


def apply_window_extraction(
    store: GraphStore,
    window: WindowRecord,
    fn: Callable[[WindowRecord], Any],
    *,
    tag: str,
    extractor_name: str = "",
    extractor_version: str = "",
    resolver: Any = None,
    resolver_version: str = GRAPH_RESOLVER_VERSION,
    index: GraphIndex | None = None,
    max_attempts: int = MAX_ATTEMPTS,
    scope: str = "document",
) -> dict[str, Any]:
    """Project one document-level window with the pending/failed/retry policy.

    The window is a single idempotency unit (``extracted.jsonl`` keyed by
    ``window.id``). Validation happens before any mutation; evidence is
    re-anchored to the window's real members; the projection is strictly
    additive (``scope="document"``, no mentions) and never touches chunk rows
    or the tape.
    """
    def skipped() -> dict[str, Any]:
        return {
            "ok": True, "status": "skipped", "applied": 0,
            "pending": 0, "failed": 0, "created_entities": 0,
            "empty": 0, "new_mentions": 0,
        }

    if window.id in store.extracted_ids(tag):
        return skipped()
    attempts = store.pending_attempts(window.id, extractor=tag)

    def failed_outcome(status: str, error: str) -> dict[str, Any]:
        return {
            "ok": False, "status": status, "error": error,
            "applied": 0, "pending": int(status == "pending"),
            "failed": int(status == "failed"), "created_entities": 0,
            "empty": 0, "new_mentions": 0,
        }

    try:
        raw = fn(window)
    except ExtractionError as exc:
        status = _retry_or_fail(
            store, window.id, str(exc), tag=tag, attempts=attempts,
            max_attempts=max_attempts,
        )
        return failed_outcome(status, str(exc))
    except Exception as exc:  # unexpected: definitive
        store.mark_failed(window.id, str(exc), extractor=tag)
        store.drop_pending(window.id)
        return failed_outcome("failed", str(exc))

    try:
        extraction = (
            raw
            if isinstance(raw, Extraction)
            else Extraction.from_obj(
                raw,
                memory_id=window.id,
                extractor=extractor_name,
                extractor_version=extractor_version,
                scope=scope,
            )
        )
        extraction = _resolve_window_evidence(extraction, window)
    except Exception as exc:  # malformed payload: definitive
        store.mark_failed(window.id, str(exc), extractor=tag)
        store.drop_pending(window.id)
        return failed_outcome("failed", str(exc))

    idx = index if index is not None else store.index()
    result = project_extraction(
        store, idx, window, extraction, tag=tag, resolver=resolver,
        extractor_name=extractor_name, extractor_version=extractor_version,
        resolver_version=resolver_version, scope=scope, emit_mentions=False,
    )
    store.mark_extracted(window.id, result["entities"], result["relations"], extractor=tag)
    store.drop_pending(window.id)
    _write_meta(
        store,
        tag=tag,
        extractor_name=extractor_name or "custom",
        extractor_version=extractor_version,
        resolver_version=resolver_version,
        last_memory_id=window.id,
    )
    return {
        "ok": True, "status": "extracted", "applied": 1, "pending": 0,
        "failed": 0, "created_entities": result["created_entities"],
        "empty": result["empty"], "new_mentions": 0,
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
    documents_root: Path | None = None,
    document_structure_level: str | None = None,
    window_chars: int = 12000,
    document_extractor: Any = None,
) -> dict[str, Any]:
    """Extract durable tape records into the graph store.

    ``tape`` is only read. A rebuild with a different extractor tag is
    required when the recorded projection was built by another extractor
    version. ``atomic`` rebuilds into ``graph.building/`` and swaps only after
    a complete, validated run, so an interrupted rebuild never destroys the
    previous projection. ``batch_fn`` (e.g. ``GraphExtractor.extract_batch``)
    is a transport optimization: each record keeps its own idempotency unit.

    D5: when ``document_structure_level`` is given (``chunk``/``document``/
    ``both``), the document layer is (re)projected from the tape + the
    ``D####`` registry + the preserved originals under ``documents_root`` —
    original files are hash-validated first and a missing/adulterated file
    aborts the rebuild explicitly (never approximate). ``document_extractor``
    must expose ``extract``/``extract_batch``/``extract_window`` for the
    document passes; without it only chunk-scope rows are reproduced. The
    default (``None``) keeps the graph-v3 projection byte-for-byte untouched.
    """
    from .ingest_document import DocumentRebuildError, rebuild_document_projection, validate_originals

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

    if document_structure_level is not None and store.documents():
        try:
            validate_originals(
                store, documents_root or store.directory.parent / "documents"
            )
        except DocumentRebuildError as exc:
            return {
                "ok": False,
                "error": f"{exc}",
                "documents_validated": False,
            }

    target = store
    building: GraphStore | None = None
    if rebuild and atomic:
        building = GraphStore(Path(str(store.directory) + ".building"))
        building.clear()
        building.copy_reviews_from(store)
        building.copy_documents_from(store)
        target = building
    elif rebuild:
        documents_backup = store._load("documents.jsonl")
        store.clear()
        for row in documents_backup:
            store._append("documents.jsonl", row)

    def report_failure(exc: BaseException) -> dict[str, Any]:
        if building is not None:
            return {
                "ok": False,
                "error": f"rebuild failed; previous graph kept: {exc}",
                "building_dir": str(building.directory),
            }
        return {"ok": False, "error": str(exc)}

    try:
        result = _build_into(
            tape, target, spec, name=name, tag=tag, types=types, resolver=resolver,
            resolver_version=resolver_version, max_attempts=max_attempts,
            batch_size=batch_size, batch_max_chars=batch_max_chars, batch_fn=batch_fn,
        )
        if document_structure_level is not None and target.documents():
            doc_result = rebuild_document_projection(
                target, tape,
                documents_root or target.directory.parent / "documents",
                document_extractor
                or _SpecDocumentExtractor(spec.fn, batch_fn, name, spec.version, tag),
                resolver,
                structure_level=document_structure_level,
                window_chars=window_chars,
                batch_size=batch_size,
                batch_max_chars=batch_max_chars,
                max_attempts=max_attempts,
                extractor_name=name,
                extractor_version=spec.version,
            )
            result["document"] = doc_result
    except DocumentRebuildError as exc:
        return {
            "ok": False,
            "error": f"{exc}",
            "documents_validated": False,
            **report_failure(exc),
        }
    except Exception as exc:
        return report_failure(exc)

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


def document_context(store: GraphStore, doc_key: str) -> dict[str, Any]:
    """Provenance-filtered view of the graph for one document.

    ``doc_key`` may be a ``D####`` id or a ``name#hash`` source key. The view
    is deterministic and reconstructable: entities are globally resolved (no
    per-document duplicates) and are selected through the document's mentions
    (the plural provenance point); relations are selected from the document's
    memories or by explicit ``source_document``. This is the data the future
    document subgraph will render — no recall and no new defaults.
    """
    doc = store.document_by_id(str(doc_key)) or store.document_by_source(str(doc_key))
    if doc is None:
        return {"ok": False, "error": f"unknown document: {doc_key}"}
    mentions = [
        m for m in store.mentions() if m.source_document == doc.source
    ]
    memory_ids = sorted({m.memory_id for m in mentions if m.memory_id})
    entity_ids = sorted(
        {m.entity_id for m in mentions if m.entity_id}
        | {e.id for e in store.entities() if e.source_document == doc.source}
    )
    entities = [e for e in store.entities() if e.id in entity_ids]
    relations = [
        r
        for r in store.relations()
        if r.source_document == doc.source or r.memory_id in memory_ids
    ]
    return {
        "ok": True,
        "document": doc.to_dict(),
        "memories": memory_ids,
        "entities": [e.to_dict() for e in entities],
        "relations": [r.to_dict() for r in relations],
        "mentions": [m.to_dict() for m in mentions],
    }


def _resolve_document(store: GraphStore, doc_key: str) -> DocumentRecord | None:
    return (
        store.document_by_id(str(doc_key))
        or store.document_by_source(str(doc_key))
        or next((d for d in store.documents() if d.name == str(doc_key)), None)
    )


def _original_status(doc: DocumentRecord, documents_root: Path | None) -> dict[str, Any]:
    """Present + hash-validated state of the preserved original (D5)."""
    root = documents_root or (Path(doc.original).parent if doc.original else None)
    if root is None:
        return {"present": False, "hash_ok": False, "path": "",
                "error": "no original recorded"}
    original = Path(doc.original) if doc.original else root / doc.name
    if not original.exists():
        return {
            "present": False, "hash_ok": False, "path": str(original),
            "error": "original missing", "expected_hash": doc.hash,
        }
    from .attachments import _file_hash

    actual = _file_hash(original.read_text(encoding="utf-8", errors="replace").strip())
    if actual != doc.hash:
        return {
            "present": True, "hash_ok": False, "path": str(original),
            "expected_hash": doc.hash, "actual_hash": actual,
            "error": "hash mismatch (document was altered)",
        }
    return {"present": True, "hash_ok": True, "path": str(original),
            "expected_hash": doc.hash}


def document_view(
    store: GraphStore,
    tape: Any,
    doc_key: str,
    *,
    documents_root: Path | None = None,
    memory_id: str = "",
    span: str = "",
) -> dict[str, Any]:
    """Query the document subgraph: ``D####`` / ``name#hash`` / file name.

    Filters: ``memory_id`` keeps only rows produced by one chunk memory;
    ``span`` (``"a:b"``) keeps rows whose ``source_span`` overlaps ``[a, b]``.
    Includes a window map (``D####|wNN`` idempotency units), the document's
    chunk memories and the hash-validated original status. Deterministic and
    read-only — recall/plasticity are untouched.
    """
    doc = _resolve_document(store, doc_key)
    if doc is None:
        return {"ok": False, "error": f"unknown document: {doc_key}"}
    if span.strip():
        try:
            a, b = (int(x) for x in span.strip().split(":", 1))
        except ValueError:
            return {"ok": False, "error": f"span must be 'a:b', got {span!r}"}
    else:
        a = b = None

    def in_range(row_span: tuple[int, int] | Any) -> bool:
        if a is None or not row_span or len(row_span) != 2:
            return True
        return not (int(row_span[1]) < a or int(row_span[0]) > b)

    mentions = [
        m for m in store.mentions() if m.source_document == doc.source
    ]
    if memory_id:
        mentions = [m for m in mentions if m.memory_id == memory_id]
    memory_ids = sorted({m.memory_id for m in mentions if m.memory_id})
    entity_ids = sorted(
        {m.entity_id for m in mentions if m.entity_id}
        | {e.id for e in store.entities() if e.source_document == doc.source}
    )
    entities = [e for e in store.entities() if e.id in entity_ids]
    relations = [
        r for r in store.relations()
        if r.source_document == doc.source or r.memory_id in memory_ids
    ]
    relations = [r for r in relations if in_range(r.source_span)]
    entities = [e for e in entities if in_range(e.source_span)]
    mentions = [m for m in mentions if in_range(m.span)]

    prefix = f"{doc.id}|w"
    window_rows: dict[str, list[dict[str, Any]]] = {}
    window_ids: list[str] = []
    for r in relations:
        if r.memory_id.startswith(prefix):
            window_ids.append(r.memory_id)
    for wid in sorted(set(window_ids)):
        window_rows[wid] = [r.to_dict() for r in relations if r.memory_id == wid]

    chunk_memories: list[dict[str, Any]] = []
    if tape is not None:
        chunk_memories = [
            r.to_dict() for r in sorted(
                (rec for rec in tape.read()
                 if rec.source == doc.source and rec.type == "attachment"),
                key=lambda rec: (rec.source_span[0] if rec.source_span else 0),
            )
        ]

    return {
        "ok": True,
        "document": doc.to_dict(),
        "original": _original_status(doc, documents_root),
        "memories": memory_ids,
        "chunk_memories": chunk_memories,
        "windows": window_rows,
        "entities": [e.to_dict() for e in entities],
        "relations": [r.to_dict() for r in relations],
        "mentions": [m.to_dict() for m in mentions],
    }


def explain_relation(
    store: GraphStore,
    tape: Any,
    relation_id: str,
    *,
    documents_root: Path | None = None,
) -> dict[str, Any]:
    """Walk a relation back to its full provenance chain (D5).

    Shows **every** evidence span — not just the first — with the exact text
    re-hydrated from the preserved original (``documents_root``) or, failing
    that, from the tape memory; then the document, the source/target entities
    and the window unit when the row is document-scoped.
    """
    relation = next((r for r in store.relations() if r.id == relation_id), None)
    if relation is None:
        return {"ok": False, "error": f"unknown relation: {relation_id}"}
    entities = {e.id: e for e in store.entities()}
    records = {r.id: r for r in tape.read()} if tape is not None else {}

    doc = store.document_by_source(relation.source_document) if relation.source_document else None
    original_text: str | None = None
    if doc is not None:
        status = _original_status(doc, documents_root)
        if status.get("present") and status.get("hash_ok"):
            try:
                original_text = Path(status["path"]).read_text(
                    encoding="utf-8", errors="replace"
                )
            except OSError:
                original_text = None
        doc_payload = {"record": doc.to_dict(), "original": status}
    else:
        doc_payload = None

    def slice_text(memory_id: str, span: tuple[int, int] | list[int] | Any) -> tuple[str, str]:
        start, end = (span[0], span[1]) if len(tuple(span)) == 2 else (None, None)
        if original_text is not None and start is not None:
            lo = max(0, int(start))
            hi = min(len(original_text), int(end) or lo)
            if hi > lo:
                return original_text[lo:hi], "original"
        record = records.get(memory_id)
        if record is not None and start is not None and span:
            text = str(record.why or "")
            lo = max(0, int(start) - (record.source_span[0] if len(record.source_span) == 2 else 0))
            hi = min(len(text), int(end) - (record.source_span[0] if len(record.source_span) == 2 else 0))
            if hi > lo >= 0:
                return text[lo:hi], "tape"
        return (str(record.why or "") if record else ""), "record"

    evidence = []
    for ev in relation.evidence:
        memory_id = str(ev.get("memory_id") or "")
        span = tuple(ev.get("span") or ()) if ev.get("span") else (relation.source_span,)
        if len(span) == 1:  # no explicit span -> the relation's own span
            span = span[0]
        text, source = slice_text(memory_id, span)
        record = records.get(memory_id)
        evidence.append({
            "memory_id": memory_id,
            "span": list(span) if len(tuple(span)) == 2 else None,
            "source": source,
            "text": text,
            "memory_summary": record.summary if record else "",
        })

    memory = records.get(relation.memory_id)
    return {
        "ok": True,
        "relation": relation.to_dict(),
        "scope": relation.extraction_scope,
        "source": entities[relation.source].to_dict() if relation.source in entities else None,
        "target": entities[relation.target].to_dict() if relation.target in entities else None,
        "aliases": [
            a.to_dict()
            for a in store.aliases()
            if a.entity_id in {relation.source, relation.target}
        ],
        "document": doc_payload,
        "window": relation.memory_id if relation.memory_id.startswith("D") else None,
        "memory": memory.to_dict() if memory is not None else None,
        "evidence": evidence,
    }
