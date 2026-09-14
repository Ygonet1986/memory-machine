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

DURABLE_TYPES = ("decision", "lesson", "preference", "bugfix", "build")

MAX_ENTITIES = 20
MAX_RELATIONS = 30
MAX_ALIASES = 8


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
        )


@dataclass
class GraphAlias:
    entity_id: str
    alias: str
    memory_id: str = ""
    confidence: float = 0.8
    method: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class GraphMention:
    memory_id: str
    entity_id: str
    confidence: float = 0.8

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Extraction:
    """Validated extractor output (names, not ids)."""

    entities: list[dict[str, Any]] = field(default_factory=list)
    relations: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_obj(cls, obj: Any) -> "Extraction":
        entities: list[dict[str, Any]] = []
        relations: list[dict[str, Any]] = []
        if not isinstance(obj, dict):
            return cls()
        for raw in (obj.get("entities") or [])[:MAX_ENTITIES]:
            if not isinstance(raw, dict):
                continue
            name = str(raw.get("name") or "").strip()
            if not name:
                continue
            aliases = [
                str(a).strip()
                for a in (raw.get("aliases") or [])[:MAX_ALIASES]
                if str(a).strip()
            ]
            entities.append(
                {
                    "name": name[:120],
                    "type": str(raw.get("type") or "unknown").strip().lower()[:40] or "unknown",
                    "aliases": aliases,
                }
            )
        for raw in (obj.get("relations") or [])[:MAX_RELATIONS]:
            if not isinstance(raw, dict):
                continue
            source = str(raw.get("source") or "").strip()
            relation = str(raw.get("relation") or "").strip()
            target = str(raw.get("target") or "").strip()
            if not (source and relation and target):
                continue
            try:
                confidence = float(raw.get("confidence") or 0.8)
            except (TypeError, ValueError):
                confidence = 0.8
            relations.append(
                {
                    "source": source[:120],
                    "relation": relation[:60],
                    "target": target[:120],
                    "confidence": max(0.0, min(1.0, confidence)),
                    "kind": str(raw.get("kind") or "").strip().lower()[:40],
                }
            )
        return cls(entities=entities, relations=relations)


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

    @classmethod
    def load(cls, store: "GraphStore") -> "GraphIndex":
        index = cls()
        for entity in store.entities():
            index.add_entity(entity)
        for alias in store.aliases():
            index.alias_map.setdefault(normalize_name(alias.alias), alias.entity_id)
        for relation in store.relations():
            index.add_relation(relation)
        for mention in store.mentions():
            index.memory_entities.setdefault(mention.memory_id, set()).add(mention.entity_id)
            index.entity_memories.setdefault(mention.entity_id, set()).add(mention.memory_id)
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
        return self.by_norm.get(key) or self.alias_map.get(key) or ""

    def edges_of(
        self,
        entity_id: str,
        *,
        direction: str = "both",
        kinds: Iterable[str] | None = None,
    ) -> list[GraphRelation]:
        want = {str(k).strip().lower() for k in kinds} if kinds else None
        edges = []
        if direction in {"both", "out"}:
            edges.extend(self.out_edges.get(entity_id, []))
        if direction in {"both", "in"}:
            edges.extend(self.in_edges.get(entity_id, []))
        if want:
            edges = [r for r in edges if r.kind in want or r.relation in want]
        return edges

    def neighbors(
        self,
        entity_id: str,
        *,
        depth: int = 1,
        min_confidence: float = 0.0,
        direction: str = "both",
        kinds: Iterable[str] | None = None,
    ) -> list[tuple[GraphRelation, str, float]]:
        """BFS over edges; returns ``(relation, other_entity, path_confidence)``.

        The path confidence is the bottleneck (minimum edge confidence) along
        the path that reached the entity.
        """
        frontier = [(entity_id, 1.0)]
        seen = {entity_id: 1.0}
        out: list[tuple[GraphRelation, str, float]] = []
        for _ in range(max(1, depth)):
            nxt: list[tuple[str, float]] = []
            for current, path_conf in frontier:
                for relation in self.edges_of(current, direction=direction, kinds=kinds):
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


class GraphStore:
    """Append-only storage of the graph projection (never touches the tape)."""

    FILES = (
        "entities.jsonl",
        "relations.jsonl",
        "aliases.jsonl",
        "mentions.jsonl",
        "extracted.jsonl",
        "failed.jsonl",
    )

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
    ) -> GraphAlias:
        item = GraphAlias(
            entity_id=entity_id,
            alias=str(alias).strip(),
            memory_id=memory_id,
            confidence=max(0.0, min(1.0, float(confidence))),
            method=method,
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
        }

    def exists(self) -> bool:
        return any(self._path(name).exists() for name in self.FILES)

    def index(self) -> GraphIndex:
        return GraphIndex.load(self)

    def clear(self) -> None:
        """Remove every graph file (used by ``--rebuild``). Never the tape."""
        for name in (*self.FILES, "meta.json"):
            try:
                self._path(name).unlink(missing_ok=True)
            except OSError:
                continue


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


def build_graph(
    tape: Any,
    store: GraphStore,
    extractor: Extractor | ExtractorSpec,
    *,
    extract_types: Iterable[str] | str | None = None,
    rebuild: bool = False,
    extractor_name: str = "",
    resolver: Any = None,
) -> dict[str, Any]:
    """Extract durable tape records into the graph store.

    ``tape`` is only read. ``rebuild`` clears the projection first. Records
    already extracted by the same extractor tag are skipped (idempotence);
    extractor failures are recorded and retried on the next build. ``resolver``
    is the F2 hook (``.resolve(spec) -> entity_id``); F1 resolves exact names.
    """
    spec = extractor if isinstance(extractor, ExtractorSpec) else ExtractorSpec(extractor)
    name = extractor_name or ("noop" if spec.fn is noop_extractor else "custom")
    tag = f"{name}/{spec.version}"
    types = parse_types(extract_types) if extract_types else set(DURABLE_TYPES)

    if rebuild:
        store.clear()
    index = store.index()
    done = store.extracted_ids(tag)

    stats: dict[str, Any] = {
        "considered": 0,
        "extracted": 0,
        "skipped": 0,
        "failed": 0,
        "empty": 0,
        "new_mentions": 0,
    }
    created_entities: list[str] = []

    for record in tape.read():
        if record.type not in types or record.derived_from:
            continue
        if record.id in done:
            stats["skipped"] += 1
            continue
        stats["considered"] += 1
        try:
            extraction = Extraction.from_obj(spec.fn(record))
        except Exception as exc:  # extractor failures never stop the build
            store.mark_failed(record.id, str(exc), extractor=tag)
            stats["failed"] += 1
            continue

        local: dict[str, str] = {}
        mentioned: set[str] = set()
        for item in extraction.entities:
            entity_id = index.resolve(item["name"])
            if not entity_id and resolver is not None:
                entity_id = str(resolver.resolve(item) or "")
            if not entity_id:
                entity_id = _ensure_entity(
                    store, index, item["name"], item["type"], record.id,
                    created=created_entities,
                )
                for alias in item["aliases"]:
                    store.add_alias(entity_id, alias, record.id)
                    index.alias_map.setdefault(normalize_name(alias), entity_id)
            local[normalize_name(item["name"])] = entity_id
            mentioned.add(entity_id)

        for item in extraction.relations:
            source = local.get(normalize_name(item["source"])) or index.resolve(item["source"])
            if not source:
                source = _ensure_entity(
                    store, index, item["source"], "unknown", record.id,
                    created=created_entities,
                )
            target = local.get(normalize_name(item["target"])) or index.resolve(item["target"])
            if not target:
                target = _ensure_entity(
                    store, index, item["target"], "unknown", record.id,
                    created=created_entities,
                )
            relation = store.add_relation(
                source, item["relation"], target, record.id, item["confidence"],
                kind=item["kind"],
            )
            index.add_relation(relation)
            mentioned.add(source)
            mentioned.add(target)

        for entity_id in sorted(mentioned):
            store.add_mention(record.id, entity_id)
            stats["new_mentions"] += 1
        if not extraction.entities and not extraction.relations:
            stats["empty"] += 1
        store.mark_extracted(
            record.id, len(mentioned), len(extraction.relations), extractor=tag
        )
        stats["extracted"] += 1

    counts = store.counts()
    meta = {
        "version": GRAPH_EXTRACTOR_VERSION,
        "extractor": name,
        "extractor_version": spec.version,
        "tag": tag,
        "built_at": _now(),
        "extract_types": sorted(types),
        "counts": counts,
        "last_memory_id": str(getattr(tape.last(), "id", "") or ""),
    }
    store.write_meta(meta)
    return {
        "ok": True,
        "extractor": tag,
        "created_entities": len(created_entities),
        **stats,
        "counts": counts,
    }


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
        result["pending"] = len([mid for mid in durable if mid not in done]) if extractor_tag else len(durable)
        result["extractor_tag"] = extractor_tag
    result["failed"] = store.failed_rows()[-20:]
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
