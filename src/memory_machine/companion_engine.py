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
from typing import Any

from .companion_memory import CompanionMemory
from .companion_persona import CompanionPersona, render_persona_prompt
from .companion_session import CompanionSession
from .config import Config
from .coordinator import Machine

LAYERS: tuple[tuple[str, str], ...] = (
    ("person_report",
     "Relatos da pessoa (declarações; não são verificação independente)"),
    ("episode", "Episódios de conversas reais"),
    ("story", "Histórias imaginadas (ficção; nunca fatos da vida real)"),
    ("hypothesis", "Hipóteses tentativas (podem estar erradas; não são fatos)"),
)
LAYER_TYPES = {kind for kind, _label in LAYERS}

EPISTEMIC_POLICY = """\
Regras de memória (obrigatórias):
- Mencione o passado apenas quando houver memória com id fornecido no contexto; nunca invente eventos compartilhados.
- Ficção continua ficção; histórias imaginadas nunca são fatos da vida real da pessoa.
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


def _cap_cards(cards: list[dict], budget: int) -> tuple[list[dict], list[str]]:
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


def render_layers(cards: list[dict], records: dict[str, Any]) -> str:
    """Render labeled, provenance-carrying layers for the conversation call."""
    by_type: dict[str, list[tuple[dict, Any]]] = {}
    for card in cards:
        record = records.get(str(card.get("memory_id") or ""))
        if record is None or record.type not in LAYER_TYPES:
            continue
        by_type.setdefault(record.type, []).append((card, record))
    sections: list[str] = []
    for kind, label in LAYERS:
        items = by_type.get(kind) or []
        if not items:
            continue
        lines = [f"### {label}"]
        for card, record in items:
            origin = dict(record.origin or {})
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
                 budget: int = 2000, temperature: float = 0.0):
        self.session = session
        self._client = _CountingClient(client)
        self.budget = max(0, int(budget))
        self.temperature = float(temperature)

    @property
    def calls(self) -> int:
        return self._client.calls

    def reply(self, message: str, *, save: bool = False) -> dict[str, Any]:
        if save:
            raise ValueError("saving lands in F3b; run with save=False")
        text = (message or "").strip()
        if not text:
            raise ValueError("empty message")
        return self.session.run_turn(
            lambda store: self._turn(store, text), save=False
        )

    def _turn(self, store: CompanionMemory, message: str) -> dict[str, Any]:
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
        cards, dropped = _cap_cards(cards, self.budget)
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
        return {
            "reply": reply,
            "used": used_records,
            "provided": provided,
            "dropped": dropped,
            "proposed": proposed,
            "violations": violations,
            "calls": self._client.calls,
        }
