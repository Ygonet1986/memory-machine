"""trilepsia-v1 (T1): extractor, validator, tape units and CLI helpers.

Frozen contract: ``docs/TRILEPSIA_V1.md`` (T0, commit aa8fc7c). Scope: the
**B2 half of T2TC** — typed investigation memory over ``.txt`` ingestion;
parametric adaptation is out of scope.

Invariants implemented here (each has a test in ``tests/test_trilepsia.py``):

- **X is declared** at ingestion (`--schema`); ``auto`` persists the chosen id
  in the raw envelope and is never recomputed.
- **Selects; does not supply**: the unit stores references (``derived_from``
  chunk memories, ``source_span``) plus the raw extraction envelope; factual
  text stays on the tape/preserved original and is rehydrated by consumers.
- **Exact spans**: an observation's ``content`` must equal
  ``original[start:end]`` exactly; every ``evidence_span`` must lie inside the
  window's original span. Normalization or paraphrase is rejected.
- **Epistemic discipline**: observations are ``reported`` unless the window
  gives a measurement with a declared ``method``; hypotheses keep competing
  candidates separate (``state`` in the frozen vocabulary); ``causes`` needs an
  intervention or explicit ``assumptions``; qualifications are ``evaluated``
  only when the window actually evaluates them; absence of evidence is not a
  negative observation.
- **Caps with counted drops** (never silent truncation), per T0 §7.
- **Raw envelope on tape**: ``{schema_version, extractor, extractor_version,
  raw}`` plus the ``V`` dimension (scope/validity/permissions, T0 §3/§9) and
  the counted ``dropped`` sibling required by T0 §7.
- **Temporal isolation**: the prompt is built from the window text and the
  declared schema ONLY — there is no question parameter anywhere in this
  module's extraction path.
- **Idempotency**: ``(document source, window id, extractor/version)`` — the
  declared schema is NOT part of the key (T0 §5); a schema change requires a
  version bump or T2's explicit rebuild, never a silent re-extraction.

T1 covers extraction + validation + tape units + ``ingest|status|show``; the
``trilepsia/`` projection, rebuild and ``explain`` are T2.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .attachments import _file_hash
from .graph_extract import extract_json_object
from .secrets import SecretError, assert_clean
from .tape import MemoryRecord, Tape

EXTRACTOR_NAME = "trilepsia"
EXTRACTOR_VERSION = "v1"

SCHEMA_KEYS = (
    "entities",
    "events",
    "qualifications",
    "observations",
    "hypotheses",
    "query_policies",
    "unknowns",
)
CAPS: dict[str, int] = {
    "entities": 12,
    "events": 12,
    "qualifications": 12,
    "observations": 10,
    "hypotheses": 6,
    "query_policies": 6,
    "unknowns": 12,
}
OBSERVATION_KINDS = ("reported", "observed", "derived")
HYPOTHESIS_STATES = (
    "open",
    "under_investigation",
    "supported",
    "contested",
    "refuted",
)
GRAPH_ID_RE = re.compile(r"^[ERM]\d{4}$")
REF_FIELDS = ("ref", "source", "target", "agent", "object", "memory_id", "entity", "event")


class TrilepsiaError(ValueError):
    """The extractor response is unusable (empty/malformed/schema-less)."""


class TransientTrilepsiaError(TrilepsiaError):
    """Transport/API failure — retried by the caller's attempts policy."""


TRILEPSIA_PROMPT = """You extract a TRILEPSIA — a structured investigation unit \
— from ONE window of a document. The window text is the ONLY source: never \
invent facts, names or relations it does not contain. Return ONLY a JSON \
object, nothing else:

{{"schema":"<the declared schema id>","entities":[{{"ref":"e1","name":"...","kind":"...","confidence":0.9,"evidence_span":[120,168]}}],"events":[{{"ref":"ev1","agent":"e1","action":"...","object":"e2","evidence_span":[300,356]}}],"qualifications":[{{"attr":"...","value":"...","evaluated":false,"evidence_span":[400,430]}}],"observations":[{{"kind":"reported|observed|derived","content":"<exact text>","method":"","evidence_span":[120,168]}}],"hypotheses":[{{"ref":"h1","class":"...","statement":"...","state":"open|under_investigation|supported|contested|refuted","evidence_for":[],"evidence_against":[],"assumptions":[]}}],"query_policies":[{{"ref":"q1","question":"...","expected_info":"...","cost":1}}],"unknowns":["..."]}}

Rules (binding):
- refs are LOCAL to this answer (e1, ev1, h1, q1). NEVER use ids such as \
E0001, R0001 or M0001.
- Every item may carry "evidence_span": [a,b], character offsets in the \
ORIGINAL document (see the "char a-b" offsets in the "### [M####]" headers). \
An observation's "content" MUST be the exact text at its span.
- An observation about a measurement is still "reported" until the measurement \
itself is given. Use "observed" ONLY with a concrete "method" (measurement, \
tool, result); use "derived" only for conclusions drawn from other records.
- Hypotheses are competing candidates, never facts: keep them separate and \
set "state" honestly. Absence of evidence is NOT a negative observation.
- Qualifications: set "evaluated": true only when this window actually \
evaluates it; otherwise leave it false/absent (unknown).
- Causal relations: only emit "causes" when the window shows an intervention \
or the item documents its "assumptions"; otherwise omit.
- Omit empty lists. If the window supports nothing, return \
{{"schema":"<schema>","unknowns":["..."]}}."""


def build_prompt(window_text: str, schema: str) -> list[dict[str, str]]:
    """The extraction messages: window + declared schema, and nothing else.

    Temporal isolation (T0 §6): this function has no question/task parameter,
    so the recall question can never enter extraction.
    """
    system = TRILEPSIA_PROMPT.replace("<the declared schema id>", schema).replace(
        "<schema>", schema
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": window_text},
    ]


def window_blocks(window: Any, original: str) -> str:
    """The window text: original slices with memory ids and char offsets.

    Slices come from the preserved original (not from formatted memories) so
    any span the extractor cites is validatable against the original text.
    """
    blocks = []
    for member in window.members:
        span = tuple(getattr(member, "source_span", ()) or ())
        if len(span) != 2:
            raise TrilepsiaError(
                f"chunk {getattr(member, 'id', '')} has no source_span"
            )
        start, end = int(span[0]), int(span[1])
        if not (0 <= start < end <= len(original)):
            raise TrilepsiaError(
                f"chunk {getattr(member, 'id', '')} span {span} outside the original"
            )
        blocks.append(
            f"### [{getattr(member, 'id', '')}] char {start}-{end}\n{original[start:end]}"
        )
    return "\n\n".join(blocks)


def _span_error(span: Any, original: str, lo: int, hi: int) -> str:
    if not isinstance(span, (list, tuple)) or len(span) != 2:
        return "evidence_span is not [a,b]"
    try:
        start, end = int(span[0]), int(span[1])
    except (TypeError, ValueError):
        return "evidence_span is not integer offsets"
    if not (0 <= start < end <= len(original)):
        return f"evidence_span [{start},{end}] outside the original"
    if not (lo <= start and end <= hi):
        return f"evidence_span [{start},{end}] outside the window [{lo},{hi}]"
    return ""


def _item_error(key: str, item: dict[str, Any], original: str, lo: int, hi: int) -> str:
    for field_name in REF_FIELDS:
        value = item.get(field_name)
        if isinstance(value, str) and GRAPH_ID_RE.match(value.strip()):
            return f"{field_name}={value!r} is a graph id (refs must be local)"
    if "evidence_span" in item:
        error = _span_error(item.get("evidence_span"), original, lo, hi)
        if error:
            return error
    if key == "entities" and not str(item.get("name") or "").strip():
        return "entity without name"
    if key == "events" and not str(item.get("action") or "").strip():
        return "event without action"
    if key == "query_policies" and not str(item.get("question") or "").strip():
        return "query policy without question"
    if key == "observations":
        kind = str(item.get("kind") or "reported").strip().lower()
        if kind not in OBSERVATION_KINDS:
            return f"unknown observation kind {kind!r}"
        if kind == "observed" and not str(item.get("method") or "").strip():
            return "kind=observed requires a declared method"
        if "content" in item and "evidence_span" not in item:
            return "observation content without evidence_span (exact-span rule)"
        if "content" in item and "evidence_span" in item:
            span = item["evidence_span"]
            start, end = int(span[0]), int(span[1])
            if original[start:end] != str(item.get("content") or ""):
                return "observation content is not the exact text at evidence_span"
    if key == "hypotheses":
        state = str(item.get("state") or "open").strip().lower()
        if state not in HYPOTHESIS_STATES:
            return f"unknown hypothesis state {state!r}"
        causal = str(item.get("relation") or item.get("kind") or "").strip().lower()
        if causal.startswith("caus"):
            if not item.get("assumptions") and not item.get("intervention"):
                return "causal claim without intervention or assumptions"
    return ""


def _normalize_item(key: str, item: dict[str, Any]) -> dict[str, Any]:
    out = {k: v for k, v in item.items()}
    if "confidence" in out:
        try:
            out["confidence"] = max(0.0, min(1.0, float(out["confidence"])))
        except (TypeError, ValueError):
            out.pop("confidence", None)
    if key == "observations":
        out.setdefault("kind", "reported")
    if key == "hypotheses":
        out.setdefault("state", "open")
        out.setdefault("assumptions", [])
        out.setdefault("evidence_for", [])
        out.setdefault("evidence_against", [])
    if key == "qualifications":
        out["evaluated"] = bool(out.get("evaluated") is True)
    return out


def validate_trilepsia(
    obj: Any,
    *,
    original: str,
    schema: str,
    window_span: tuple[int, int] = (),
) -> tuple[dict[str, Any], dict[str, dict[str, int]]]:
    """Item-wise validation of a raw extractor payload.

    Returns ``(validated, dropped)`` where ``dropped`` counts, per key, the
    items discarded as invalid and the items beyond the frozen cap — counters,
    never silent truncation (T0 §7). Raises ``TrilepsiaError`` when the
    payload carries no trilepsia structure at all. With an empty
    ``window_span`` the bounds fall back to the whole original; the extraction
    path always passes the window span (``window_blocks`` guarantees it).
    """
    if not isinstance(obj, dict) or not any(key in obj for key in SCHEMA_KEYS):
        raise TrilepsiaError("extractor output has no trilepsia keys")
    lo, hi = window_span if window_span else (0, len(original))
    validated: dict[str, Any] = {"schema": schema}
    dropped: dict[str, dict[str, int]] = {}
    for key in SCHEMA_KEYS:
        items = obj.get(key)
        if key == "unknowns":
            values = [str(v).strip() for v in items] if isinstance(items, list) else []
            over = max(0, len(values) - CAPS[key])
            validated[key] = values[: CAPS[key]]
            if over:
                dropped[key] = {"over_cap": over, "invalid": 0}
            continue
        if not isinstance(items, list):
            items = []
        keep: list[dict[str, Any]] = []
        invalid = 0
        for item in items:
            if not isinstance(item, dict):
                invalid += 1
                continue
            if _item_error(key, item, original, lo, hi):
                invalid += 1
                continue
            keep.append(_normalize_item(key, item))
        over = max(0, len(keep) - CAPS[key])
        validated[key] = keep[: CAPS[key]]
        if over or invalid:
            dropped[key] = {"over_cap": over, "invalid": invalid}
    return validated, dropped


class TrilepsiaExtractor:
    """Injectable LLM extractor: one window -> validated raw envelope."""

    is_trilepsia_extractor = True
    VERSION = EXTRACTOR_VERSION

    def __init__(
        self,
        client: Any,
        *,
        name: str = EXTRACTOR_NAME,
        version: str | None = None,
        temperature: float = 0.0,
    ) -> None:
        self.client = client
        self.name = name
        self.version = version or self.VERSION
        self.temperature = temperature

    @property
    def tag(self) -> str:
        return f"{self.name}/{self.version}"

    def extract_window(self, window: Any, original: str, schema: str) -> dict[str, Any]:
        """One transport call; returns the frozen raw envelope (T0 §5)."""
        messages = build_prompt(window_blocks(window, original), schema)
        try:
            content, _reasoning = self.client.complete_with_reasoning(
                messages, temperature=self.temperature
            )
        except Exception as exc:  # API, transport, timeout
            raise TransientTrilepsiaError(f"llm error: {exc}") from exc
        if not str(content or "").strip():
            raise TransientTrilepsiaError("empty completion")
        raw = extract_json_object(content)
        span = tuple(getattr(window, "source_span", ()) or ())
        validated, dropped = validate_trilepsia(
            raw,
            original=original,
            schema=schema,
            window_span=(int(span[0]), int(span[1])) if len(span) == 2 else (),
        )
        envelope: dict[str, Any] = {
            "schema_version": schema,
            "extractor": self.name,
            "extractor_version": self.version,
            "raw": validated,
        }
        if dropped:
            envelope["dropped"] = dropped  # counted caps, T0 §7
        return envelope


@dataclass
class Window:
    """A source-ordered group of chunk memories (the extraction unit)."""

    id: str
    members: list[MemoryRecord] = field(default_factory=list)
    source_document: str = ""
    source_span: tuple[int, int] = ()


def window_groups(records: list[MemoryRecord], window_chars: int) -> list[Window]:
    """Source-ordered chunk groups of at most ``window_chars`` content chars."""
    groups: list[list[MemoryRecord]] = []
    current: list[MemoryRecord] = []
    used = 0
    for record in records:
        cost = len(record.why or "") or len(record.text())
        if current and used + cost > max(1, int(window_chars)):
            groups.append(current)
            current = []
            used = 0
        current.append(record)
        used += cost
    if current:
        groups.append(current)
    out = []
    for index, members in enumerate(groups, start=1):
        first, last = members[0], members[-1]
        span = ()
        if first.source_span and last.source_span:
            span = (int(first.source_span[0]), int(last.source_span[1]))
        out.append(
            Window(
                id=f"w{index:02d}",
                members=members,
                source_document=str(first.source_document or ""),
                source_span=span,
            )
        )
    return out


def document_chunks(tape: Tape, doc_source: str) -> list[MemoryRecord]:
    """Chunk records of one document, in tape order."""
    return [
        record
        for record in tape.read()
        if record.source_span
        and (
            record.source_document == doc_source
            or record.source == doc_source
        )
    ]


def unit_source(doc_source: str, window_id: str, tag: str) -> str:
    return f"{doc_source}#{window_id}#{tag}"


def existing_units(tape: Tape, tag: str) -> dict[str, MemoryRecord]:
    """Unit records of this extractor tag, keyed by their source string."""
    return {
        record.source: record
        for record in tape.read()
        if record.type == "trilepsia_unit" and record.source.endswith(f"#{tag}")
    }


DEFAULT_PERMISSIONS = {
    "local_memory": True,
    "local_training": True,
    "shared_training": False,
}


def unit_record(
    *,
    doc_source: str,
    window: Window,
    envelope: dict[str, Any],
    schema: str,
    tag: str,
    scope: str = "",
    validity: dict[str, Any] | None = None,
    permissions: dict[str, Any] | None = None,
) -> MemoryRecord:
    """The tape unit: refs + raw envelope + V (never a factual payload copy)."""
    envelope = dict(envelope)
    envelope["V"] = {
        "scope": scope,
        "validity": dict(validity or {}),
        "permissions": dict(DEFAULT_PERMISSIONS, **(permissions or {})),
    }
    # The envelope can carry extracted text; the tape's own scan only covers
    # record.text(), so scan the raw payload explicitly before it is written.
    assert_clean(json.dumps(envelope, ensure_ascii=False))
    raw = envelope.get("raw") or {}
    counts = {key: len(raw.get(key) or []) for key in SCHEMA_KEYS}
    return MemoryRecord(
        type="trilepsia_unit",
        summary=(
            f"Trilepsia {schema} unit {window.id} of {doc_source.split('#', 1)[0]}"
        ),
        why=(
            "typed counts: "
            + ", ".join(f"{key}={counts[key]}" for key in SCHEMA_KEYS)
            + f"; extractor {tag}; refs only (rehydrate from the tape/original)"
        ),
        source=unit_source(doc_source, window.id, tag),
        derived_from=[member.id for member in window.members],
        source_document=window.source_document or doc_source,
        source_span=window.source_span,
        trilepsia=envelope,
    )


def ingest_trilepsia(
    *,
    tape: Tape,
    root: Path,
    doc_source: str,
    schema: str,
    client: Any,
    window_chars: int = 12000,
    max_attempts: int = 3,
    extractor: TrilepsiaExtractor | None = None,
    scope: str = "",
    validity: dict[str, Any] | None = None,
    permissions: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Extract every window of one ingested document into tape units.

    The original is re-read from ``<root>/documents/`` and hash-checked first
    (T0 §4/R2); a missing or altered original aborts. Idempotent by
    ``(doc_source, window id, extractor tag)``. Transient failures retry up to
    ``max_attempts`` and are recorded in ``trilepsia/pending.jsonl`` /
    ``trilepsia/failed.jsonl``.
    """
    name, _, expected_hash = doc_source.partition("#")
    original_path = root / "documents" / name
    if not original_path.exists():
        return {"ok": False, "error": f"preserved original missing: {original_path}"}
    original = original_path.read_text(encoding="utf-8", errors="replace").strip()
    if expected_hash and _file_hash(original) != expected_hash:
        return {"ok": False, "error": f"original hash mismatch for {name}"}

    extractor = extractor or TrilepsiaExtractor(client)
    tag = extractor.tag
    chunks = document_chunks(tape, doc_source)
    if not chunks:
        return {"ok": False, "error": f"no chunk memories for {doc_source}"}
    existing = existing_units(tape, tag)
    queue_dir = root / "trilepsia"
    queue_dir.mkdir(parents=True, exist_ok=True)
    summary = {"ok": True, "tag": tag, "schema": schema, "windows": 0,
               "applied": 0, "skipped": 0, "pending": 0, "failed": 0}
    for window in window_groups(chunks, window_chars):
        summary["windows"] += 1
        source = unit_source(doc_source, window.id, tag)
        if source in existing:
            summary["skipped"] += 1
            continue
        error = ""
        definitive = False
        for attempt in range(1, max(1, int(max_attempts)) + 1):
            try:
                envelope = extractor.extract_window(window, original, schema)
                record = unit_record(
                    doc_source=doc_source, window=window, envelope=envelope,
                    schema=schema, tag=tag, scope=scope, validity=validity,
                    permissions=permissions,
                )
                tape.append(record)
                summary["applied"] += 1
                error = ""
                break
            except TransientTrilepsiaError as exc:  # transport: retry
                error = f"{type(exc).__name__}: {exc}"
                continue
            except TrilepsiaError as exc:  # parse/schema: definitive
                error = f"{type(exc).__name__}: {exc}"
                definitive = True
                break
            except SecretError as exc:  # secret in the envelope: definitive
                error = f"{type(exc).__name__}: {exc}"
                definitive = True
                break
            except Exception as exc:  # unknown: treat as transient
                error = f"{type(exc).__name__}: {exc}"
                continue
        if error:
            queue = "failed" if (definitive or attempt >= max_attempts) else "pending"
            with (queue_dir / f"{queue}.jsonl").open("a", encoding="utf-8") as handle:
                handle.write(json.dumps({
                    "source": source, "window": window.id, "error": error,
                }, ensure_ascii=False) + "\n")
            summary[queue] += 1
    return summary


def trilepsia_status(tape: Tape, root: Path) -> dict[str, Any]:
    """Counts of units and typed content, plus queue sizes."""
    units = [r for r in tape.read() if r.type == "trilepsia_unit"]
    counts = {key: 0 for key in SCHEMA_KEYS}
    schemas: dict[str, int] = {}
    for unit in units:
        envelope = unit.trilepsia or {}
        schema = str(envelope.get("schema_version") or "")
        schemas[schema] = schemas.get(schema, 0) + 1
        raw = envelope.get("raw") or {}
        for key in SCHEMA_KEYS:
            counts[key] += len(raw.get(key) or [])
    queues = {}
    for name in ("pending", "failed"):
        path = root / "trilepsia" / f"{name}.jsonl"
        queues[name] = (
            sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
            if path.exists()
            else 0
        )
    return {
        "ok": True,
        "units": len(units),
        "schemas": schemas,
        "typed_counts": counts,
        "queues": queues,
    }


def show_unit(tape: Tape, unit_id: str) -> dict[str, Any]:
    """A unit record + envelope (display only; rehydration is T2's explain)."""
    for record in tape.read():
        if record.id == unit_id and record.type == "trilepsia_unit":
            return {
                "ok": True,
                "id": record.id,
                "source": record.source,
                "derived_from": list(record.derived_from),
                "source_span": list(record.source_span) if record.source_span else [],
                "status": record.status,
                "trilepsia": record.trilepsia,
            }
    return {"ok": False, "error": f"trilepsia unit not found: {unit_id}"}
