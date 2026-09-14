"""LLM graph extractor (Graph Memory Machine, F2).

The extractor turns ONE eligible tape memory into a validated, immutable
``Extraction`` of semantic refs (``e1``/``ev1``). It never touches the graph
store and never chooses ``E####``/``R####`` ids: validation happens entirely
before the resolver maps refs to graph ids, so a partially malformed model
response cannot start mutating the projection.

Failures are typed: ``TransientExtractionError`` (API/timeout/empty output) and
``ExtractionError`` (schema/parse) follow the pending/failed policy in
``graph.apply_record_extraction``; the tape is never affected either way.
"""

from __future__ import annotations

from typing import Any

from .graph import (
    GRAPH_EXTRACTOR_VERSION,
    Extraction,
    ExtractionError,
    ExtractedEvent,
    ExtractedRelation,
    TransientExtractionError,
)
from .llm import extract_json_object

EXTRACTOR_NAME = "llm"
MAX_MEMORY_CHARS = 6000

GRAPH_EXTRACT_PROMPT = """You extract a small knowledge graph from ONE memory \
record of a persistent project tape. The record is the only source: never \
invent facts, entities or relations that it does not state.

Return ONLY a JSON object, nothing else:

{{"entities":[{{"ref":"e1","name":"Kalak","type":"person","confidence":0.99,"aliases":["the king"]}},{{"ref":"e2","name":"rochedo","type":"object","confidence":0.96}}],"events":[{{"ref":"ev1","action":"contornar","agent":"e1","object":"e2","confidence":0.97}}],"relations":[{{"source":"e1","relation":"crossed","target":"e2","confidence":0.9,"kind":""}}],"mentions":["e1","e2"],"confidence":0.95}}

Rules:
- refs are LOCAL to this answer (e1, e2, ev1, ...). NEVER use graph ids such \
as E0001 or R0001.
- "entities": concrete things (people, objects, places, organizations, \
concepts, decisions). type is one of person|object|place|organization|concept|event|action|unknown. \
List aliases the record uses for the same thing.
- "events": an action the record describes, with "agent" and/or "object" \
pointing at entity refs (omit when absent).
- "relations": edges the record states between entities. Use short canonical \
verbs when obvious (cross, find, decide, create, use, fix, add, remove, \
change, before, after, belongs_to, part_of); otherwise keep the record's verb.
- "mentions": refs of entities the record mentions but that appear in no \
relation.
- confidence is per item, 0.0-1.0; prefer lower values when the record is \
vague.
- If the record has nothing worth extracting, return \
{{"entities":[],"events":[],"relations":[]}}."""

_CANONICAL_RELATIONS = {
    "crossed": "cross",
    "crossing": "cross",
    "contornou": "cross",
    "contornar": "cross",
    "found": "find",
    "finds": "find",
    "encontrou": "find",
    "encontrar": "find",
    "created": "create",
    "criou": "create",
    "criar": "create",
    "decided": "decide",
    "decidiu": "decide",
    "decidir": "decide",
    "used": "use",
    "uses": "use",
    "usou": "use",
    "usar": "use",
    "fixed": "fix",
    "corrigiu": "fix",
    "corrigir": "fix",
    "added": "add",
    "adicionou": "add",
    "adicionar": "add",
    "removed": "remove",
    "removeu": "remove",
    "remover": "remove",
    "changed": "change",
    "mudou": "change",
    "alterou": "change",
    "pertencer": "belong_to",
    "pertence": "belong_to",
    "pertence_a": "belong_to",
    "parte_de": "part_of",
    "ligado_a": "connected_to",
    "antes_de": "before",
    "depois_de": "after",
}


def canonical_relation(verb: str) -> str:
    """Normalize an open verb to a canonical form when one is evident."""
    key = str(verb or "").strip().lower()
    key = "_".join(key.split())
    return _CANONICAL_RELATIONS.get(key, key)


def parse_extraction(
    obj: Any,
    *,
    memory_id: str,
    extractor: str = EXTRACTOR_NAME,
    extractor_version: str = GRAPH_EXTRACTOR_VERSION,
) -> Extraction:
    """Strictly validate a raw extractor payload into a frozen ``Extraction``.

    Raises ``ExtractionError`` when the response is not a JSON object carrying
    an extraction (empty or malformed model output); item-level problems are
    dropped, but nothing is projected until this returns.
    """
    if not isinstance(obj, dict) or not any(
        key in obj for key in ("entities", "events", "relations")
    ):
        raise ExtractionError("extractor output has no entities/events/relations")

    base = Extraction.from_obj(
        obj,
        memory_id=memory_id,
        extractor=extractor,
        extractor_version=extractor_version,
    )
    events = tuple(
        ExtractedEvent(
            ref=event.ref,
            action=canonical_relation(event.action),
            agent=event.agent,
            object=event.object,
            confidence=event.confidence,
            kind=event.kind,
        )
        for event in base.events
    )
    relations = tuple(
        ExtractedRelation(
            source=relation.source,
            relation=canonical_relation(relation.relation),
            target=relation.target,
            confidence=relation.confidence,
            kind=relation.kind,
        )
        for relation in base.relations
    )
    return Extraction(
        entities=base.entities,
        events=events,
        relations=relations,
        mentions=base.mentions,
        confidence=base.confidence,
        kind=base.kind,
        memory_id=memory_id,
        extractor=extractor,
        extractor_version=extractor_version,
    )


class GraphExtractor:
    """Injectable LLM extractor: tape memory -> validated ``Extraction``.

    Duck-typed marker ``is_graph_extractor`` lets ``build_graph`` route it
    through the retry/provenance-aware policy without importing this module.
    """

    is_graph_extractor = True
    VERSION = GRAPH_EXTRACTOR_VERSION

    def __init__(
        self,
        client: Any,
        *,
        name: str = EXTRACTOR_NAME,
        version: str | None = None,
        temperature: float = 0.0,
        max_chars: int = MAX_MEMORY_CHARS,
    ) -> None:
        self.client = client
        self.name = name
        self.version = version or self.VERSION
        self.temperature = temperature
        self.max_chars = max_chars

    @property
    def tag(self) -> str:
        return f"{self.name}/{self.version}"

    def memory_text(self, record: Any) -> str:
        body = f"[{record.id}] [{record.type}] {record.summary}\n{record.why or ''}".strip()
        return body[: self.max_chars]

    def extract(self, record: Any) -> Extraction:
        messages = [
            {"role": "system", "content": GRAPH_EXTRACT_PROMPT},
            {"role": "user", "content": self.memory_text(record)},
        ]
        try:
            content = self.client.complete(messages, temperature=self.temperature)
        except Exception as exc:  # API, transport, timeout
            raise TransientExtractionError(f"llm error: {exc}") from exc
        if not str(content or "").strip():
            raise TransientExtractionError("empty completion")
        return parse_extraction(
            extract_json_object(content),
            memory_id=getattr(record, "id", ""),
            extractor=self.name,
            extractor_version=self.version,
        )
