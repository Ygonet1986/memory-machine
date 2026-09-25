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

GRAPH_CONVERSATION_PROMPT = """You are the memory graph agent. Read ONE saved \
conversation turn or entity description and return ONLY a JSON object:
{{"entities":[{{"ref":"e1","name":"Lia","type":"person"}},{{"ref":"e2","name":"jardim","type":"concept"}}],"events":[],"relations":[{{"source":"e1","relation":"related_to","target":"e2","confidence":0.8}}],"mentions":["e1","e2"]}}

Extract named people, places, objects, and recurring concepts. For an \
entity_definition record, its summary is the entity's name and its why is \
the person's description: connect that entity to concepts in the description. \
Connect entities that the turn discusses together with related_to even if \
the person does not assert a factual relationship. Use a more specific short \
verb only when useful. These links are associative paths for finding memories, \
not verified facts. Do not add entities or associations absent from this turn. \
Use local refs e1/e2; entity types are person|object|place|organization|concept|event|action|unknown. \
Include confidence from 0 to 1 per entity/relation. Return empty arrays if \
there is nothing to connect."""

GRAPH_BATCH_PROMPT = """You extract a small knowledge graph from SEVERAL \
memory records of a persistent project tape. The records are the only source: \
never invent facts, entities or relations they do not state.

Return ONLY a JSON object, nothing else:

{{"records":[{{"memory_id":"M0010","entities":[{{"ref":"e1","name":"Kalak","type":"person","confidence":0.99}}],"events":[],"relations":[]}},{{"memory_id":"M0011","entities":[],"events":[],"relations":[]}}]}}

Rules:
- One entry per record, keyed by the record's exact "memory_id" (as given in \
the "### [M####]" header). Never emit a memory_id that is not in the input; \
never omit a record - use empty lists when it has nothing to extract.
- refs are LOCAL to each record's entry (e1, e2, ev1, ...). NEVER use graph \
ids such as E0001 or R0001.
- Same extraction contract as single-record mode: "entities" (name/type/\
aliases/confidence), "events" (action/agent/object), "relations" (source/\
relation/target/confidence), "mentions" (refs), per-item confidence 0..1.
- Use short canonical verbs when obvious (cross, find, decide, create, use, \
fix, add, remove, change, before, after, belongs_to, part_of).
- Entity types: person|object|place|organization|concept|event|action|unknown."""

GRAPH_WINDOW_PROMPT = """You extract the DOCUMENT-LEVEL structure of a window: \
several contiguous chunks of one document, shown in order with their memory ids \
and character offsets. This is the unit where structure that only emerges from \
seeing many pieces together becomes visible (long-range relations, topics, \
internal references). The window text is the ONLY source: never invent facts, \
entities or relations it does not support.

Return ONLY a JSON object, nothing else:

{{"entities":[{{"ref":"e1","name":"Evidence Delivery","type":"topic","confidence":0.9}},{{"ref":"e2","name":"chapter 4","type":"reference","confidence":0.7}}],"relations":[{{"source":"e1","relation":"influences","target":"e2","confidence":0.8,"evidence":[{{"memory_id":"M0042","span":[1800,2300]}},{{"memory_id":"M0171","span":[28400,29100]}}]}}]}}

Rules:
- refs are LOCAL to this answer (e1, e2, ev1, ...). NEVER use graph ids such \
as E0001 or R0001.
- "entities": reuse entity types for things already visible in the window; \
add type "topic" for the global subjects a topic spans; add type "reference" \
for internal chapter/section/header ids and clearly identifiable \
citations/bibliography. Do not build richer ontologies.
- "relations": edges that emerge ACROSS the window between entities/topics \
(chapter/entity discusses topic, topic related_to topic, entity central_to \
topic, entity interacts entity, ...). Use short canonical verbs when obvious.
- "evidence": list the EXACT memory_ids (from the "### [M####]" headers) that \
support THIS relation, with their character span when you have it. Never use a \
memory_id that is not in the window. Omit "evidence" only when no specific \
member supports it alone.
- confidence is per item, 0.0-1.0; prefer lower values when the window is vague.
- If the window adds nothing beyond the local view, return \
{{"entities":[],"relations":[]}}."""


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
    scope: str = "",
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
            evidence=relation.evidence,
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
        scope=scope or base.scope,
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
            {"role": "system", "content": (
                GRAPH_CONVERSATION_PROMPT if record.type in {
                    "question", "reply", "memory", "entity_definition",
                } else GRAPH_EXTRACT_PROMPT
            )},
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

    def batch_text(self, records: list[Any]) -> str:
        blocks = [
            f"### [{record.id}]\n{self.memory_text(record)}" for record in records
        ]
        return "\n\n".join(blocks)

    def extract_batch(self, records: list[Any]) -> dict[str, Extraction]:
        """Extract several records in one transport call.

        Returns ``{memory_id: Extraction}`` for the records it could parse;
        a memory missing from the result is retried by the caller's
        pending/failed policy. Memory ids outside the batch are ignored and
        duplicated ids keep the first occurrence.
        """
        if not records:
            return {}
        if len(records) == 1:
            record = records[0]
            return {record.id: self.extract(record)}
        messages = [
            {"role": "system", "content": GRAPH_BATCH_PROMPT},
            {"role": "user", "content": self.batch_text(records)},
        ]
        try:
            content = self.client.complete(messages, temperature=self.temperature)
        except Exception as exc:  # API, transport, timeout
            raise TransientExtractionError(f"llm error: {exc}") from exc
        if not str(content or "").strip():
            raise TransientExtractionError("empty completion")
        obj = extract_json_object(content)
        raw_records = obj.get("records") if isinstance(obj, dict) else None
        if not isinstance(raw_records, list):
            raise ExtractionError("batch output has no records list")

        allowed = {record.id for record in records}
        out: dict[str, Extraction] = {}
        for item in raw_records:
            if not isinstance(item, dict):
                continue
            memory_id = str(item.get("memory_id") or "").strip()
            if memory_id not in allowed or memory_id in out:
                continue  # never process a memory that was not in the batch
            try:
                out[memory_id] = parse_extraction(
                    item,
                    memory_id=memory_id,
                    extractor=self.name,
                    extractor_version=self.version,
                )
            except ExtractionError:
                continue  # per-record failure -> retried by the caller
        return out

    # ----------------------------------------------------- window scope (D4)

    def window_text(self, window: Any) -> str:
        blocks = []
        for member in window.members:
            span = tuple(getattr(member, "source_span", ()) or ())
            offsets = f" char {span[0]}-{span[1]}" if len(span) == 2 else ""
            blocks.append(f"### [{getattr(member, 'id', '')}]{offsets}\n{self.memory_text(member)}")
        return "\n\n".join(blocks)

    def extract_window(self, window: Any) -> Extraction:
        """One transport call over a window of chunk memories.

        Uses ``complete_with_reasoning`` so reasoning models cannot silently
        drop the JSON payload (see M0006): if ``content`` is empty the window
        is transient-failed and retried by the caller.
        """
        messages = [
            {"role": "system", "content": GRAPH_WINDOW_PROMPT},
            {"role": "user", "content": self.window_text(window)},
        ]
        try:
            content, _reasoning = self.client.complete_with_reasoning(
                messages, temperature=self.temperature
            )
        except Exception as exc:  # API, transport, timeout
            raise TransientExtractionError(f"llm error: {exc}") from exc
        if not str(content or "").strip():
            raise TransientExtractionError("empty completion")
        return parse_extraction(
            extract_json_object(content),
            memory_id=str(getattr(window, "id", "") or ""),
            extractor=self.name,
            extractor_version=self.version,
            scope="document",
        )
