"""Headless Companion turn engine: recall, labeled layers, one reply call.

The engine runs inside ``CompanionSession.run_turn``: with saving off the
whole turn (including the core recall machinery) executes against a disposable
clone, so the canonical root receives zero bytes. The measured opencode path,
the admission shadow and every product default are untouched.

This module does not write turn slots or extracted memories yet (F3b); F3a
covers recall, the labeled memory context, the persona prompt, the reply call
and the trailer protocol (used/candidate memories + violations).
"""

from __future__ import annotations

import json
import re
import uuid
from typing import Any

from .companion_extract import AUTHORS, COMPANION_TYPES
from .companion_memory import CompanionMemory
from .companion_persona import CompanionPersona, render_persona_prompt
from .companion_session import CompanionSession
from .config import Config
from .coordinator import Machine
from .groups import load_manifest, save_manifest
from .turns import add_turn_slot

LIFE_KIND = "synthetic_life_event"
LIFE_LAYER = "Passado ficcional da personagem (aprovado)"
IMPROV_LAYER = "Histórias imaginadas em conversa (ficção; nunca fatos da vida real)"

LAYERS: tuple[tuple[str, str], ...] = (
    ("person_report",
     "Relatos da pessoa (declarações; não são verificação independente)"),
    ("episode", "Episódios de conversas reais"),
    ("life", LIFE_LAYER),
    ("story", IMPROV_LAYER),
    ("hypothesis", "Hipóteses tentativas (podem estar erradas; não são fatos)"),
)
LAYER_TYPES = {"person_report", "episode", "story", "hypothesis"}
DEFAULT_LIFE_BUDGET = 800

STORE_REQUEST_RE = re.compile(
    r"(?i)\b(guarde|salve|lembre)\b[^.\n]{0,40}\bcomo\s+"
    r"(nossa|a\s+nossa|uma)\s+hist[óo]ria\b")


def _store_request_quote(message: str) -> str:
    match = STORE_REQUEST_RE.search(message or "")
    return match.group(0) if match else ""

EPISTEMIC_POLICY = """\
Regras de memória (obrigatórias):
- Mencione o passado apenas quando houver memória com id fornecido no contexto; nunca invente eventos compartilhados.
- Ficção continua ficção; histórias imaginadas nunca são fatos da vida real da pessoa.
- O passado da personagem vem de eventos aprovados (Passado ficcional): conte como história dela, nunca como experiência da pessoa.
- Hipóteses são tentativas: apresente-as como possibilidade, nunca como fato; se a pessoa corrigir, aceite.
- Se a memória necessária não estiver no contexto, pergunte ou diga que não lembra; não preencha lacunas.
- Respeite pausas e a autonomia da pessoa; sem culpa, cobrança ou exclusividade.
"""

TRAILER_SPEC = """\
Ao final da resposta, inclua UM único objeto JSON (nada depois dele):
{"used": ["M0001", ...], "memories": [{"type": "person_report", "summary": "...", "quote": "...", "source": "person"}]}
- "used": apenas ids fornecidos no contexto que você de fato usou (pode ser vazio).
- "memories": apenas memórias novas sustentadas por citação literal; "source" é "person" (fala da pessoa) ou "lia" (sua fala); "quote" deve ser trecho literal da fonte indicada.
- Nunca proponha "persona"; "hypothesis" exige "confidence" (0 a 1) e "review_at" (ISO 8601); "story" exige "event_id".
- Sem memórias novas: "memories": [].
"""


class _CountingClient:
    """Thin proxy so the engine can report cost without new dependencies."""

    def __init__(self, client: Any):
        self._client = client
        self.calls = 0

    def complete(self, messages: list[dict[str, str]], *,
                 temperature: float = 0.0) -> str:
        self.calls += 1
        return self._client.complete(messages, temperature=temperature)

    def stream(self, messages: list[dict[str, str]], *,
               temperature: float = 0.0):
        self.calls += 1
        return self._client.stream(messages, temperature=temperature)


def _extract_trailer(content: str) -> tuple[str, list[str], list[dict], bool]:
    """Split the final trailer object out of a reply.

    Scans JSON objects and keeps the last one carrying "used" or "memories";
    that object is removed from the reply text.
    """
    text = content or ""
    decoder = json.JSONDecoder()
    match: tuple[int, int, dict] | None = None
    index = 0
    while True:
        start = text.find("{", index)
        if start == -1:
            break
        try:
            obj, end = decoder.raw_decode(text[start:])
        except json.JSONDecodeError:
            index = start + 1
            continue
        if isinstance(obj, dict) and ("used" in obj or "memories" in obj):
            match = (start, start + end, obj)
        index = start + 1
    if match is None:
        return text.strip(), [], [], False
    start, end, obj = match
    used = [str(item).strip() for item in (obj.get("used") or [])
            if isinstance(item, str) and item.strip()]
    memories = [item for item in (obj.get("memories") or [])
                if isinstance(item, dict)]
    clean = (text[:start] + text[end:]).strip()
    return clean, used, memories, True


def _layer_key(record: Any) -> str:
    """Synthetic-life events get their own labeled layer (C4)."""
    if record.type == "story" and (record.origin or {}).get("kind") == LIFE_KIND:
        return "life"
    return record.type


def _cap_list(cards: list[dict], budget: int) -> tuple[list[dict], list[str]]:
    kept: list[dict] = []
    dropped: list[str] = []
    used = 0
    for card in cards:
        size = int(card.get("used_chars") or 0)
        if kept and used + size > budget:
            dropped.append(str(card.get("memory_id") or ""))
            continue
        kept.append(card)
        used += size
    return kept, dropped


def _cap_cards(cards: list[dict], records: dict[str, Any], budget: int,
               life_budget: int) -> tuple[list[dict], list[str]]:
    """Cap synthetic life with its own budget; the rest keeps the general one."""
    life: list[dict] = []
    rest: list[dict] = []
    for card in cards:
        record = records.get(str(card.get("memory_id") or ""))
        if record is not None and _layer_key(record) == "life":
            life.append(card)
        else:
            rest.append(card)
    kept_life, dropped_life = _cap_list(life, life_budget)
    kept_rest, dropped_rest = _cap_list(rest, budget)
    kept_ids = {id(card) for card in kept_life + kept_rest}
    kept = [card for card in cards if id(card) in kept_ids]
    return kept, dropped_life + dropped_rest


def render_layers(cards: list[dict], records: dict[str, Any]) -> str:
    """Render labeled, provenance-carrying layers for the conversation call."""
    by_key: dict[str, list[tuple[dict, Any]]] = {}
    for card in cards:
        record = records.get(str(card.get("memory_id") or ""))
        if record is None or record.type not in LAYER_TYPES:
            continue
        by_key.setdefault(_layer_key(record), []).append((card, record))
    sections: list[str] = []
    for key, label in LAYERS:
        items = by_key.get(key) or []
        if not items:
            continue
        lines = [f"### {label}"]
        for card, record in items:
            origin = dict(record.origin or {})
            if key == "life":
                reference = (f"vida aprovada v{origin.get('life_version', '?')}"
                             f" · {origin.get('event_id', '?')}")
            else:
                reference = str(origin.get("kind") or "?")
                if origin.get("version"):
                    reference += f":{origin['version']}"
                if origin.get("event_id"):
                    reference += f":{origin['event_id']}"
            lines.append(f"- [{record.id}] {record.summary} (fonte: {reference})")
            note = str(card.get("note") or "").strip()
            if note:
                lines.append(f"  nota: {note}")
        sections.append("\n".join(lines))
    return "\n\n".join(sections) or "(sem memórias no contexto)"


def _brief(record: Any) -> dict[str, Any]:
    return {
        "memory_id": record.id,
        "type": record.type,
        "summary": record.summary,
        "origin": dict(record.origin or {}),
    }


class CompanionEngine:
    """One headless turn: recall -> labeled context -> one reply call."""

    def __init__(self, session: CompanionSession, client: Any, *,
                 budget: int = 2000, life_budget: int = DEFAULT_LIFE_BUDGET,
                 temperature: float = 0.0):
        self.session = session
        self._client = _CountingClient(client)
        self.budget = max(0, int(budget))
        self.life_budget = max(0, int(life_budget))
        self.temperature = float(temperature)

    @property
    def calls(self) -> int:
        return self._client.calls

    def reply(self, message: str, *, save: bool = False) -> dict[str, Any]:
        text = (message or "").strip()
        if not text:
            raise ValueError("empty message")
        turn_id = uuid.uuid4().hex[:12]
        return self.session.run_turn(
            lambda store: self._turn(store, text, turn_id, save=save),
            save=save,
        )

    def _turn(self, store: CompanionMemory, message: str, turn_id: str, *,
              save: bool) -> dict[str, Any]:
        persona = CompanionPersona(store.root).load()
        if persona is None:
            raise ValueError("no approved persona in this root; create it first")
        config = Config.load(store.root)
        if config.evidence_payload == "off":
            config.evidence_payload = "budgeted"
        machine = Machine(store.root, config=config, client=self._client)
        result = machine.recall(message, temperature=self.temperature)
        records = {
            record.id: record for record in store.tape.read()
            if record.status == "active"
        }
        cards = [
            card for card in (result.get("evidence_payload") or [])
            if (records.get(str(card.get("memory_id") or "")) is not None
                and records[str(card.get("memory_id"))].type in LAYER_TYPES)
        ]
        cards, dropped = _cap_cards(cards, records, self.budget,
                                    self.life_budget)
        provided = [str(card.get("memory_id")) for card in cards]
        layers = render_layers(cards, records)
        messages = [
            {"role": "system",
             "content": render_persona_prompt(persona) + "\n\n"
                        + EPISTEMIC_POLICY + "\n" + TRAILER_SPEC},
            {"role": "user",
             "content": f"## Contexto de memória\n\n{layers}\n\n"
                        f"## Mensagem\n\n{message}"},
        ]
        content = self._client.complete(messages, temperature=self.temperature)
        reply, used, proposed, had_trailer = _extract_trailer(content)
        violations: list[dict[str, Any]] = []
        if not had_trailer:
            violations.append({"kind": "missing_trailer"})
        unknown = [memory_id for memory_id in used if memory_id not in provided]
        if unknown:
            violations.append({"kind": "unknown_used", "ids": unknown})
        used_records = [_brief(records[memory_id])
                        for memory_id in used if memory_id in provided]
        saved = None
        if save:
            saved = self._commit(store, message, reply, proposed, turn_id,
                                 violations)
        return {
            "reply": reply,
            "used": used_records,
            "provided": provided,
            "dropped": dropped,
            "proposed": proposed,
            "violations": violations,
            "calls": self._client.calls,
            "saved": saved,
        }

    def _commit(self, store: CompanionMemory, message: str, reply: str,
                proposed: list[dict], turn_id: str,
                violations: list[dict]) -> dict[str, Any]:
        """Write turn slots and the validated candidate memories (F3b).

        Slots are written first (source ``companion#<turn>``); candidates are
        then validated against their literal source before any record is
        appended. Invalid proposals are skipped and recorded, never written.
        """
        manifest = load_manifest(store.root / "manifest.json")
        question = add_turn_slot(
            store.tape, manifest, slot="question", text=message,
            message_id=turn_id, namespace="companion",
        )
        answer = add_turn_slot(
            store.tape, manifest, slot="reply", text=reply,
            message_id=f"{turn_id}-r", pair_message_id=turn_id,
            namespace="companion",
        )
        save_manifest(manifest, store.root / "manifest.json")
        slots = {"question": question, "reply": answer}
        config = Config.load(store.root)
        if config.graph_enabled and config.graph_conversation_enabled:
            from .tape import MemoryRecord

            machine = Machine(store.root, config=config, client=self._client)
            machine._graph_after_appends([
                MemoryRecord.from_dict(outcome["record"])
                for outcome in slots.values()
                if outcome.get("ok") and not outcome.get("deduped")
            ])
        records: list[str] = []
        accepted_types: list[str] = []
        for slot_name, outcome in slots.items():
            if not outcome.get("ok"):
                violations.append({
                    "kind": "slot_failed", "slot": slot_name,
                    "reason": str(outcome.get("error") or "unknown"),
                })
        source_slots = {
            "person": ("question", turn_id, message),
            "lia": ("reply", f"{turn_id}-r", reply),
        }
        for proposal in proposed:
            kind = str(proposal.get("type") or "")
            if kind == "persona":
                violations.append({"kind": "rejected_proposal", "type": kind,
                                   "reason": "persona is approved out of band"})
                continue
            if kind not in COMPANION_TYPES:
                violations.append({"kind": "rejected_proposal", "type": kind,
                                   "reason": "unknown Companion memory type"})
                continue
            source_name = str(proposal.get("source") or "person")
            if kind == "person_report" and source_name != "person":
                violations.append({"kind": "rejected_proposal", "type": kind,
                                   "reason": "person_report must quote the person"})
                continue
            if source_name not in source_slots:
                violations.append({"kind": "rejected_proposal", "type": kind,
                                   "reason": f"unknown source {source_name!r}"})
                continue
            slot_name, suffix, slot_text = source_slots[source_name]
            slot = slots[slot_name]
            if not slot.get("ok"):
                violations.append({"kind": "rejected_proposal", "type": kind,
                                   "reason": f"source slot {slot_name} was not written"})
                continue
            try:
                record = store.add_candidate(
                    proposal, author=AUTHORS[kind], turn_id=suffix,
                    source_text=slot_text,
                    source_memory_id=slot["record"]["id"],
                    event_time=str(proposal.get("event_time") or ""),
                )
            except ValueError as error:
                violations.append({"kind": "rejected_proposal", "type": kind,
                                   "reason": str(error)})
                continue
            records.append(record.id)
            accepted_types.append(kind)
        if "story" not in accepted_types:
            quote = _store_request_quote(message)
            question_slot = slots["question"]
            if quote and question_slot.get("ok"):
                try:
                    story = store.add_candidate(
                        {"type": "story",
                         "summary": message.strip()[:200],
                         "quote": quote,
                         "event_id": f"conv-{turn_id}"},
                        author=AUTHORS["story"], turn_id=turn_id,
                        source_text=message,
                        source_memory_id=question_slot["record"]["id"],
                    )
                except ValueError as error:
                    violations.append({"kind": "rejected_proposal",
                                       "type": "story",
                                       "reason": str(error)})
                else:
                    records.append(story.id)
        (store.root / "recall_cache.json").unlink(missing_ok=True)
        return {
            "turn_id": turn_id,
            "question_slot": question.get("record", {}).get("id", ""),
            "reply_slot": answer.get("record", {}).get("id", ""),
            "records": records,
        }
