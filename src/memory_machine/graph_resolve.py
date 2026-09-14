"""Entity resolution for the graph projection (Graph Memory Machine, F2).

Resolution order, deterministic first:

    normalized_name -> alias -> (optional embedding) -> new entity

Confidence bands (only reachable when an embedder is configured):

    >= auto (0.90)      merge via an append-only alias record
    hypothesis..auto    hypothesis: ``possibly_same_as`` edge, no merge
    < hypothesis (0.60) new entity

The LLM disambiguation hook is accepted but off by default: pass an object
with ``decide(name, candidate_name) -> bool`` to enable it. The resolver never
mutates entities; merges are additive alias records, so the projection stays
append-only and auditable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .graph import GraphIndex, normalize_name
from .retrieval import cosine, rank


@dataclass
class Resolution:
    """Outcome of resolving one extracted entity name."""

    entity_id: str = ""
    confidence: float = 0.0
    method: str = "new"  # exact | alias | embedding | llm | hypothesis | new
    hypothesis: bool = False
    other_id: str = ""


class GraphResolver:
    """Resolver over a live ``GraphIndex`` (bound by the caller)."""

    def __init__(
        self,
        *,
        embedder: Any = None,
        auto: float = 0.90,
        hypothesis: float = 0.60,
        llm: Any = None,
        max_candidates: int = 10,
    ) -> None:
        self.embedder = embedder
        self.auto = max(0.0, min(1.0, float(auto)))
        self.hypothesis = max(0.0, min(self.auto, float(hypothesis)))
        self.llm = llm
        self.max_candidates = max(1, int(max_candidates))
        self.index: GraphIndex | None = None
        # In-memory doc-vector cache: the same entity document is embedded once,
        # so caching never changes the vectors (and therefore never changes a
        # resolution); it only removes recomputation.
        self._doc_vectors: dict[str, list[float]] = {}

    def bind(self, index: GraphIndex) -> None:
        self.index = index

    def resolve(self, spec: dict[str, Any]) -> Resolution:
        name = str(spec.get("name") or "").strip()
        if not name:
            return Resolution()
        index = self.index
        if index is None:
            return Resolution()

        key = normalize_name(name)
        exact = index.by_norm.get(key)
        if exact:
            return Resolution(entity_id=exact, confidence=1.0, method="exact")
        alias = index.alias_map.get(key)
        if alias:
            return Resolution(entity_id=alias, confidence=1.0, method="alias")

        if self.embedder is None or not index.entities:
            return Resolution()

        candidates = self._shortlist(name, index)
        if not candidates:
            return Resolution()

        missing = [
            (entity_id, doc)
            for entity_id, doc in candidates
            if entity_id not in self._doc_vectors
        ]
        try:
            vectors = self.embedder.embed([name] + [doc for _eid, doc in missing])
        except Exception:
            return Resolution()
        if len(vectors) != len(missing) + 1:
            return Resolution()

        query = vectors[0]
        for (entity_id, _doc), vector in zip(missing, vectors[1:]):
            self._doc_vectors[entity_id] = vector

        scored: list[tuple[float, str]] = []
        for entity_id, _doc in candidates:
            vector = self._doc_vectors.get(entity_id)
            if vector is None:
                continue
            scored.append((cosine(query, vector), entity_id))
        best_score, best_id = max(scored)
        if best_score >= self.auto:
            return Resolution(
                entity_id=best_id, confidence=best_score, method="embedding"
            )
        if best_score >= self.hypothesis:
            if self.llm is not None:
                promoted = self._llm_decide(name, best_id, index)
                if promoted:
                    return Resolution(
                        entity_id=best_id,
                        confidence=max(best_score, self.auto),
                        method="llm",
                    )
            return Resolution(
                entity_id="",
                confidence=best_score,
                method="hypothesis",
                hypothesis=True,
                other_id=best_id,
            )
        return Resolution()

    def _llm_decide(self, name: str, candidate_id: str, index: GraphIndex) -> bool:
        candidate = index.entities.get(candidate_id)
        if candidate is None:
            return False
        try:
            return bool(self.llm.decide(name, candidate.name))
        except Exception:
            return False

    def _shortlist(
        self, name: str, index: GraphIndex
    ) -> list[tuple[str, str]]:
        """Candidate entities: lexical top-k, or every entity in small graphs."""
        entities = list(index.entities.values())
        docs = [f"{entity.name} {entity.type}".strip() for entity in entities]
        if len(entities) <= self.max_candidates:
            return list(zip(index.entities, docs))
        try:
            ranked = rank(name, docs, limit=self.max_candidates)
        except Exception:
            ranked = []
        if ranked:
            return [(entities[i].id, docs[i]) for i, _score in ranked]
        return list(zip(list(index.entities)[-self.max_candidates :], docs[-self.max_candidates :]))
