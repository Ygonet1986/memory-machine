"""AI life generation (C0 §4): one LLM call per request, drafts only.

Builds a next-version *draft* document from a persona sheet (and the current
world, when one exists). Generated events are `draft` with
``provenance.generator="generated"`` recording the prompt tag, model and seed.
Nothing here writes to the tape, `current.json` or recall; approval stays the
explicit user act in the creator.
"""

from __future__ import annotations

import json
import re
import uuid
from typing import Any

from .companion_life import LIFE_MAX_EVENTS, validate_life

GENERATION_PROMPT_TAG = "life-gen/v1"
MIN_EVENTS = 5
STORE_LIMIT = LIFE_MAX_EVENTS

SYSTEM = """\
Você propõe a vida ficcional *anterior* de uma personagem de companhia.
Responda SOMENTE com um objeto JSON:
{"events": [{"title": "...", "summary": "...", "event_time": "2018-06",
"time_precision": "month", "place": "..."}]}
Regras: de 5 a 10 eventos; cronologia coerente entre eles; `event_time` em
"YYYY", "YYYY-MM" ou "YYYY-MM-DD" com a precisão correspondente (ou "" com
"unknown"); ficção sobre a personagem, nunca fatos sobre a pessoa real; nada
dos temas proibidos; sem causas/efeitos; sem participantes (o sistema usa a
própria personagem).
"""


def _parse_events(raw: str) -> list[dict[str, Any]]:
    match = re.search(r"\{.*\}", raw or "", re.S)
    if not match:
        raise ValueError("generation reply has no JSON object")
    try:
        payload = json.loads(match.group(0))
    except json.JSONDecodeError as error:
        raise ValueError(f"generation reply is not valid JSON: {error}") from error
    events = payload.get("events") if isinstance(payload, dict) else None
    if not isinstance(events, list) or not events:
        raise ValueError("generation reply has no events")
    if len(events) > STORE_LIMIT:
        events = events[:STORE_LIMIT]
    if len(events) < MIN_EVENTS:
        raise ValueError(f"generation returned fewer than {MIN_EVENTS} events")
    return [event for event in events if isinstance(event, dict)]


def _world_for(sheet: dict[str, Any], current: dict[str, Any] | None,
               continuity_id: str) -> dict[str, Any]:
    if current is not None:
        world = json.loads(json.dumps(current["world"]))
        world["continuity_id"] = continuity_id
        return world
    return {
        "continuity_id": continuity_id,
        "places": [],
        "people": [],
        "forbidden_subjects": list(sheet.get("boundaries") or [])[:8] or
        ["ser humano real"],
    }


def generate_draft(client: Any, persona_sheet: dict[str, Any],
                   current: dict[str, Any] | None, *,
                   self_id: str, continuity_id: str = "main",
                   model: str = "", seed: str = "",
                   temperature: float = 0.0) -> dict[str, Any]:
    """One LLM call -> a validated next-version draft document.

    Raises ``ValueError`` on invalid model output; the caller must not write
    anything in that case.
    """
    sheet = persona_sheet
    lines = [
        f"Personagem: {sheet.get('name', '')}",
        f"Voz: {sheet.get('voice', '')}",
        "Valores: " + "; ".join(sheet.get("values") or []),
        "Limites: " + "; ".join(sheet.get("boundaries") or []),
        "Biografia aprovada: " + "; ".join(sheet.get("bio") or []),
    ]
    world = _world_for(sheet, current, continuity_id)
    if world["places"]:
        lines.append("Lugares do mundo: " +
                     "; ".join(place["name"] for place in world["places"]))
    if world["people"]:
        lines.append("Pessoas fictícias: " +
                     "; ".join(person["name"] for person in world["people"]))
    if world["forbidden_subjects"]:
        lines.append("Temas proibidos: " + "; ".join(world["forbidden_subjects"]))
    lines.append("Proponha a vida ficcional anterior (linha do tempo).")
    raw = client.complete(
        [{"role": "system", "content": SYSTEM},
         {"role": "user", "content": "\n".join(lines)}],
        temperature=temperature)
    proposals = _parse_events(raw)
    seed = seed or f"gen-{uuid.uuid4().hex[:8]}"

    sheet_version = int((current or {}).get("sheet_version") or
                        sheet.get("version") or 1)
    life_version = int((current or {}).get("life_version") or 0) + 1
    next_id = 1
    if current is not None:
        next_id = 1 + max(
            (int(event["event_id"].split("-")[-1])
             for event in current["events"]), default=0)
    events = []
    for proposal in proposals:
        summary = str(proposal.get("summary") or "").strip()
        title = str(proposal.get("title") or "").strip()
        if not title or not summary:
            raise ValueError("generated events need a title and a summary")
        precision = str(proposal.get("time_precision") or "unknown")
        event_time = str(proposal.get("event_time") or "").strip()
        events.append({
            "event_id": f"life-{next_id:04d}",
            "life_version": life_version,
            "title": title,
            "summary": summary,
            "event_time": event_time,
            "time_precision": precision,
            "place": str(proposal.get("place") or "").strip(),
            "participants": [{"id": self_id, "role": ""}],
            "causes": [], "effects": [],
            "status": "draft", "approved_at": "", "approved_by": "",
            "provenance": {"kind": "synthetic_life", "generator": "generated",
                           "sheet_version": sheet_version,
                           "prompt": GENERATION_PROMPT_TAG, "model": model,
                           "seed": seed},
        })
        next_id += 1
    draft = {
        "life_version": life_version,
        "sheet_version": sheet_version,
        "status": "draft",
        "reference_date": str((current or {}).get("reference_date") or ""),
        "world": world,
        "events": events,
        "approved_at": "",
        "approved_by": "",
    }
    return validate_life(draft, self_id=self_id)
