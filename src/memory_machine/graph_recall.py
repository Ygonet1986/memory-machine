"""Graph recall (F3): query -> entities -> paths -> memory_ids.

The graph never answers. It resolves query entities deterministically (no LLM
call per recall), walks semantic paths (an event node counts as ONE hop even
though it is two physical edges), and returns memory ids that the coordinator
rehydrates from the canonical tape through the existing evidence payload.

Scoring is deliberately simple and interpretable:

    score = bottleneck_edge_confidence * (0.85 ** (semantic_depth - 1))

No BM25/embedding/LLM score is mixed in this phase; embeddings are used only
as an optional fallback to seed entities when the deterministic match fails.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from .graph import GraphIndex, GraphRelation, normalize_name
from .retrieval import cosine

DEPTH_PENALTY = 0.85
MAX_QUERY_TOKENS = 16
MAX_NGRAM = 4
EMBEDDING_SEED_THRESHOLD = 0.72
EMBEDDING_SEED_LIMIT = 3


@dataclass
class GraphPath:
    nodes: list[str] = field(default_factory=list)
    relations: list[str] = field(default_factory=list)
    score: float = 0.0
    semantic_depth: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodes": list(self.nodes),
            "relations": list(self.relations),
            "score": round(self.score, 4),
            "semantic_depth": self.semantic_depth,
        }


@dataclass
class GraphEvidence:
    memory_id: str
    score: float = 0.0
    paths: list[GraphPath] = field(default_factory=list)
    relation_ids: list[str] = field(default_factory=list)
    entity_ids: list[str] = field(default_factory=list)
    label: str = ""
    via: str = "path"  # path | mention

    def to_dict(self) -> dict[str, Any]:
        return {
            "memory_id": self.memory_id,
            "score": round(self.score, 4),
            "via": self.via,
            "label": self.label,
            "entities": list(self.entity_ids),
            "relations": list(self.relation_ids),
            "paths": [path.to_dict() for path in self.paths],
        }


@dataclass
class GraphRecallResult:
    query: str = ""
    seeds: list[str] = field(default_factory=list)
    seed_labels: list[str] = field(default_factory=list)
    evidence: list[GraphEvidence] = field(default_factory=list)
    paths_considered: int = 0
    paths_selected: int = 0
    elapsed_ms: float = 0.0

    def metrics(self) -> dict[str, Any]:
        return {
            "graph_seed_entities": len(self.seeds),
            "graph_paths_considered": self.paths_considered,
            "graph_paths_selected": self.paths_selected,
            "graph_unique_memories": len(self.evidence),
            "graph_recall_ms": round(self.elapsed_ms, 2),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "seeds": list(self.seeds),
            "seed_labels": list(self.seed_labels),
            "evidence": [item.to_dict() for item in self.evidence],
            "metrics": self.metrics(),
        }


class GraphRecall:
    """Deterministic graph-side recall over a loaded ``GraphIndex``."""

    def __init__(
        self,
        index: GraphIndex,
        *,
        embedder: Any = None,
        depth: int = 2,
        top_k: int = 8,
        max_paths: int = 400,
        max_paths_per_evidence: int = 3,
        hub_degree: int = 0,
    ) -> None:
        self.index = index
        self.embedder = embedder
        self.depth = max(1, int(depth))
        self.top_k = max(1, int(top_k))
        self.max_paths = max(1, int(max_paths))
        self.max_paths_per_evidence = max(1, int(max_paths_per_evidence))
        self.hub_degree = max(0, int(hub_degree))
        self._degrees: dict[str, int] | None = None

    def _degree(self, entity_id: str) -> int:
        """Non-resolution relation degree, computed once per recall."""
        if self._degrees is None:
            degrees: dict[str, int] = {}
            for relation in self.index.relations.values():
                if relation.kind in {"resolution", "hypothesis"}:
                    continue
                degrees[relation.source] = degrees.get(relation.source, 0) + 1
                degrees[relation.target] = degrees.get(relation.target, 0) + 1
            self._degrees = degrees
        return self._degrees.get(entity_id, 0)

    def _is_hub(self, entity_id: str) -> bool:
        return self.hub_degree > 0 and self._degree(entity_id) > self.hub_degree

    # ------------------------------------------------------------ query side

    def resolve_query_entities(self, query: str) -> list[str]:
        seeds = self._ngram_seeds(query)
        if not seeds and self.embedder is not None:
            seeds = self._embedding_seeds(query)
        return seeds

    def _ngram_seeds(self, query: str) -> list[str]:
        tokens = [token for token in normalize_name(query).split() if token][:MAX_QUERY_TOKENS]
        if not tokens:
            return []
        found: list[str] = []
        seen: set[str] = set()
        for size in range(min(MAX_NGRAM, len(tokens)), 0, -1):
            for start in range(0, len(tokens) - size + 1):
                gram = " ".join(tokens[start : start + size])
                entity_id = self.index.by_norm.get(gram) or self.index.alias_map.get(gram)
                if entity_id and entity_id not in seen:
                    found.append(entity_id)
                    seen.add(entity_id)
        return found

    def _embedding_seeds(self, query: str) -> list[str]:
        entities = list(self.index.entities.values())
        if not entities:
            return []
        docs = [f"{entity.name} {entity.type}".strip() for entity in entities]
        try:
            vectors = self.embedder.embed([query] + docs)
        except Exception:
            return []
        if len(vectors) != len(entities) + 1:
            return []
        query_vector = vectors[0]
        scored = sorted(
            (
                (cosine(query_vector, vector), entity.id)
                for entity, vector in zip(entities, vectors[1:])
            ),
            reverse=True,
        )
        return [
            entity_id
            for score, entity_id in scored[:EMBEDDING_SEED_LIMIT]
            if score >= EMBEDDING_SEED_THRESHOLD
        ]

    # ------------------------------------------------------------ traversal

    def _semantic_neighbors(
        self, entity_id: str
    ) -> list[tuple[list[GraphRelation], str, str]]:
        """One semantic hop: direct edges, or through an event node.

        An event intermediate (agent/object edges of a ``type=event`` node)
        counts as ONE hop even though the path carries two physical relations.
        """
        out: list[tuple[list[GraphRelation], str, str]] = []
        for relation in self.index.edges_of(entity_id, direction="both"):
            other = relation.target if relation.source == entity_id else relation.source
            entity = self.index.entities.get(other)
            if entity is not None and entity.type == "event":
                for second in self.index.edges_of(
                    other, direction="both", kinds=("agent", "object")
                ):
                    nxt = second.target if second.source == other else second.source
                    if nxt == entity_id:
                        continue
                    out.append(([relation, second], nxt, other))
                continue
            out.append(([relation], other, ""))
        return out

    def paths_for_entities(self, seeds: list[str]) -> list[GraphPath]:
        paths: list[GraphPath] = []
        seen_paths: set[tuple[tuple[str, ...], tuple[str, ...]]] = set()
        for seed in seeds:
            if self._is_hub(seed):
                continue  # never expand from a stop-entity hub
            visited = {seed}
            queue: deque[tuple[str, list[str], list[str], float, int]] = deque(
                [(seed, [seed], [], 1.0, 0)]
            )
            while queue:
                current, nodes, relations, confidence, semantic = queue.popleft()
                if semantic >= self.depth:
                    continue
                for chain, nxt, via_event in self._semantic_neighbors(current):
                    chain_confidence = min([confidence, *(r.confidence for r in chain)])
                    next_nodes = nodes + ([via_event] if via_event else []) + [nxt]
                    next_relations = relations + [r.id for r in chain]
                    path = GraphPath(
                        nodes=next_nodes,
                        relations=next_relations,
                        score=chain_confidence * (DEPTH_PENALTY**semantic),
                        semantic_depth=semantic + 1,
                    )
                    key = (tuple(path.nodes), tuple(path.relations))
                    if key in seen_paths:
                        continue
                    seen_paths.add(key)
                    paths.append(path)
                    if nxt in visited:
                        continue  # parallel edge: record it, do not re-expand
                    if self._is_hub(nxt):
                        continue  # record the edge into a hub, never expand from it
                    visited.add(nxt)
                    queue.append((nxt, next_nodes, next_relations, chain_confidence, semantic + 1))
                    if len(paths) >= self.max_paths:
                        return paths
        return paths

    # ------------------------------------------------------------- evidence

    def evidence_from_paths(
        self, seeds: list[str], paths: list[GraphPath]
    ) -> list[GraphEvidence]:
        by_memory: dict[str, GraphEvidence] = {}

        def entry(memory_id: str) -> GraphEvidence:
            item = by_memory.get(memory_id)
            if item is None:
                item = GraphEvidence(memory_id=memory_id)
                by_memory[memory_id] = item
            return item

        for entity_id in seeds:
            for memory_id, confidence in self.index.memories_for_entity(entity_id):
                item = entry(memory_id)
                item.score = max(item.score, confidence)
                if entity_id not in item.entity_ids:
                    item.entity_ids.append(entity_id)
                if not item.relation_ids:
                    item.via = "mention"

        for path in paths:
            for relation_id in path.relations:
                relation = self.index.relations.get(relation_id)
                if relation is None or not relation.memory_id:
                    continue
                item = entry(relation.memory_id)
                item.score = max(item.score, path.score)
                item.via = "path"
                if (
                    path not in item.paths
                    and len(item.paths) < self.max_paths_per_evidence
                ):
                    item.paths.append(path)
                for rid in path.relations:
                    if rid not in item.relation_ids:
                        item.relation_ids.append(rid)
                for node in (relation.source, relation.target):
                    if node not in item.entity_ids:
                        item.entity_ids.append(node)

        for item in by_memory.values():
            item.label = self._label(item)
        ranked = sorted(by_memory.values(), key=lambda item: (-item.score, item.memory_id))
        return ranked[: self.top_k]

    def _entity_label(self, entity_id: str) -> str:
        entity = self.index.entities.get(entity_id)
        return entity.name if entity is not None else entity_id

    def _label(self, item: GraphEvidence) -> str:
        if item.paths:
            best = max(item.paths, key=lambda path: path.score)
            parts: list[str] = []
            for index, relation_id in enumerate(best.relations):
                relation = self.index.relations.get(relation_id)
                if relation is None:
                    continue
                if index == 0:
                    parts.append(self._entity_label(relation.source))
                parts.append(f"-{relation.relation}->")
                parts.append(self._entity_label(relation.target))
            return " ".join(parts)
        if item.entity_ids:
            return f"mentions {self._entity_label(item.entity_ids[0])}"
        return ""

    # ---------------------------------------------------------------- recall

    def recall(self, query: str) -> GraphRecallResult:
        started = time.perf_counter()
        seeds = self.resolve_query_entities(query)
        result = GraphRecallResult(query=query, seeds=seeds)
        result.seed_labels = [self._entity_label(seed) for seed in seeds]
        if seeds:
            paths = self.paths_for_entities(seeds)
            result.paths_considered = len(paths)
            result.evidence = self.evidence_from_paths(seeds, paths)
            result.paths_selected = sum(len(item.paths) for item in result.evidence)
        result.elapsed_ms = (time.perf_counter() - started) * 1000.0
        return result


QUESTION_STOP = {
    "how", "many", "did", "i", "the", "a", "an", "to", "on", "in", "of", "my",
    "was", "is", "it", "and", "for", "what", "when", "where", "that", "at",
    "me", "you", "have", "has", "been", "much", "per", "day", "days", "there",
}


def question_coverage(question: str, text: str) -> float:
    """Fraction of question content tokens present in a memory text.

    Deterministic and deliberately simple: this is a *veto* signal, not a
    retrieval score. It must not replace structural relevance — the gate is
    opt-in precisely because taking it as a ranking would turn the graph into
    another BM25.
    """
    from .retrieval import tokenize

    tokens = {t for t in tokenize(question) if t not in QUESTION_STOP and len(t) > 2}
    if not tokens:
        return 0.0
    have = set(tokenize(text))
    return len(tokens & have) / len(tokens)


def question_gate(
    evidence: list[GraphEvidence],
    records: dict[str, Any],
    question: str,
    *,
    min_cov: float = 0.30,
) -> list[GraphEvidence]:
    """Drop graph evidence whose memory text does not answer-ish the question."""
    out: list[GraphEvidence] = []
    for item in evidence:
        record = records.get(item.memory_id)
        text = f"{record.summary} {record.why}" if record is not None else item.label
        if question_coverage(question, text) >= min_cov:
            out.append(item)
    return out


def guard_evidence(
    evidence: list[GraphEvidence],
    *,
    min_score: float = 0.0,
    max_items: int = 0,
) -> list[GraphEvidence]:
    """Admission control for augmented recall: score floor plus a small cap.

    `max_items=0` disables the cap. Evidence arrives score-sorted, so the cap
    keeps the strongest structural paths and the global budget then decides
    how much room they actually get.
    """
    items = [item for item in evidence if item.score >= min_score]
    return items[:max_items] if max_items > 0 else items


def describe_evidence(
    evidence: GraphEvidence,
    index: GraphIndex,
) -> str:
    """Human-readable path label for an evidence item (used in annotations)."""
    if evidence.label:
        return evidence.label
    return "graph"


# ---------------------------------------------------------- shared payloads
# Used by both the CLI (``graph query/path``) and the desktop viewer so the
# two surfaces can never diverge.


def resolve_entity(index: GraphIndex, raw: str) -> str:
    """Resolve a user-supplied name or ``E####`` id to a canonical entity."""
    text = str(raw or "").strip()
    if not text:
        return ""
    upper = text.upper()
    if upper in index.entities:
        return upper
    return index.resolve(text)


def relation_detail(index: GraphIndex, relation_id: str) -> dict[str, Any] | None:
    """Read-only view of one relation, with entity names and provenance."""
    relation = index.relations.get(relation_id)
    if relation is None:
        return None
    source = index.entities.get(relation.source)
    target = index.entities.get(relation.target)
    return {
        "id": relation.id,
        "relation": relation.relation,
        "source": relation.source,
        "source_name": source.name if source else relation.source,
        "target": relation.target,
        "target_name": target.name if target else relation.target,
        "memory_id": relation.memory_id,
        "confidence": relation.confidence,
        "kind": relation.kind,
        "extractor": relation.extractor,
        "extractor_version": relation.extractor_version,
    }


def graph_query_payload(
    index: GraphIndex,
    query: str,
    *,
    depth: int = 2,
    top_k: int = 8,
    embedder: Any = None,
) -> dict[str, Any]:
    """Entities → paths → evidence payload for a query string."""
    recall = GraphRecall(index, embedder=embedder, depth=depth, top_k=top_k)
    result = recall.recall(query)
    payload = result.to_dict()
    payload["ok"] = True
    payload["entities"] = [
        {
            "id": entity_id,
            "name": index.entities[entity_id].name,
            "type": index.entities[entity_id].type,
            "canonical": index.canonical(entity_id),
        }
        for entity_id in result.seeds
        if entity_id in index.entities
    ]
    for item in payload["evidence"]:
        item["path_details"] = [
            detail
            for path in item.get("paths", [])
            for detail in (
                [relation_detail(index, relation_id) for relation_id in path.get("relations", [])]
            )
            if detail
        ]
    return payload


def graph_path_payload(
    index: GraphIndex,
    source_raw: str,
    target_raw: str,
    *,
    depth: int = 2,
    top_k: int = 8,
) -> dict[str, Any]:
    """Up to ``top_k`` explainable paths between two entities."""
    source = resolve_entity(index, source_raw)
    target = resolve_entity(index, target_raw)
    if not source or not target:
        return {
            "ok": False,
            "error": f"unknown entity: {source_raw!r} / {target_raw!r}",
        }
    trails = index.paths(source, target, max_depth=depth, limit=top_k)
    paths: list[dict[str, Any]] = []
    memories: list[str] = []
    for trail in trails:
        details = [d for d in (relation_detail(index, r.id) for r in trail) if d]
        for detail in details:
            if detail["memory_id"] and detail["memory_id"] not in memories:
                memories.append(detail["memory_id"])
        paths.append(
            {
                "nodes": [source] + [relation.target for relation in trail],
                "relations": [relation.id for relation in trail],
                "detail": details,
            }
        )
    return {
        "ok": True,
        "source": {"id": source, "name": index.entities[source].name},
        "target": {"id": target, "name": index.entities[target].name},
        "paths": paths,
        "evidence": memories,
    }
