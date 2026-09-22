"""Lifecycle v1 — shadow admission foundation (schemas, hashes, precedence).

Contracts frozen in docs/LIFECYCLE_V1_SPEC.md and docs/LIFECYCLE_V1_PREREG.md.
This module is the deterministic foundation the rules arm (B) runs on:

- conservative normalisation and the two separate fingerprints
  (``exact_hash`` preserved content, ``normalized_hash`` comparison form);
- ``input_hash`` over relevant fields only and the idempotent ``decision_key``;
- the frozen rule precedence (correction before dedup, typed records early,
  chatter last);
- the rebuildable projection (``<root>/lifecycle/``): decisions JSONL written
  as a whole batch, atomic manifest, temp-dir rebuild + swap, no partial
  projection is ever visible.

No tape writes, no recall changes, ``mode=shadow`` only. The full heuristics
stay in this module's policy table; evaluation lives in ``eval/``.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

from .secrets import scan_text

SCHEMA_VERSION = "1"
POLICY_VERSION = "lifecycle-v1"
MODE = "shadow"
DEDUP_WINDOW = 8  # previous records of the same session, sequence-based

CLASSES = ("semantic", "episodic", "event_only", "reject")
PROMOTED_CLASSES = ("semantic", "episodic")

# Frozen confidence per decisive reason (policy v1).
CONFIDENCE = {
    "invalid_record": 1.0,
    "secret_blocked": 1.0,
    "correction": 0.80,
    "decision_change": 0.80,
    "typed_record": 1.0,
    "duplicate_exact": 1.0,
    "duplicate_normalized": 1.0,
    "decision": 0.70,
    "preference": 0.70,
    "restriction": 0.80,
    "action_taken": 0.60,
    "experiment_result": 0.60,
    "failure_context": 0.60,
    "greeting": 0.90,
    "ack": 0.90,
    "ambiguous": 0.40,
    "no_durable_signal": 0.50,
}

_TYPED = ("decision", "lesson", "preference", "bugfix", "build")

CORRECTION_MARKERS = re.compile(
    r"\b(atualiza(?:ção|cao)|atualizado|corre(?:ção|cao)|na verdade|actually|"
    r"instead|em vez de|no lugar de|passou a ser|mudamos|trocamos|"
    r"substitu\w+|supersed\w+|revog\w+)\b", re.I)
DECISION_CHANGE_MARKERS = re.compile(
    r"\b(trocamos|mudamos|passou a ser|migra(?:mos|ção|cao)|substitu\w+)\b", re.I)
DECISION_MARKERS = re.compile(
    r"\b(decidimos|decidido|decidiu|decision|combinamos|combinado|definimos)\b", re.I)
PREFERENCE_MARKERS = re.compile(
    r"\b(prefiro|preferimos|preferência|preference|sempre|nunca|always|never)\b", re.I)
RESTRICTION_MARKERS = re.compile(
    r"\bimportante|restri(?:ção|cao)|restriction|obrigat\w+|proibido|must\b", re.I)
ACTION_MARKERS = re.compile(
    r"\b(rodei|rodamos|tentei|tentamos|fiz|fizemos|corrigi|corrigimos|"
    r"deploy\w*|refator\w+|released?|executamos|testei|testamos|"
    r"instalei|instalamos|configurei|configuramos)\b", re.I)
RESULT_MARKERS = re.compile(
    r"\b(p95|p50|resultado|result|ms\b|segundos?|por cento|%|ficou em|"
    r"medimos|medição|medicao)\b", re.I)
FAILURE_MARKERS = re.compile(
    r"\b(falh\w+|erro|error|exception|quebrou|failed?|stacktrace|timeout)\b", re.I)
GREETING_MARKERS = re.compile(r"^\s*(oi|olá|ola|hi|hello|bom dia|boa tarde|boa noite)\b", re.I)
ACK_MARKERS = re.compile(
    r"^\s*(ok|okay|beleza|combinado|valeu|obrigad\w+|thanks|thank you|"
    r"blz|certo|perfeito)[!.\s]*$", re.I)
AMBIGUOUS_MARKERS = re.compile(
    r"\b(talvez|acho que|maybe|perhaps|dev(?:emos|íamos)|no futuro|"
    r"futuro|pretendemos|não sei|nao sei|incerto|possivelmente)\b", re.I)

PUNCT_ONLY = re.compile(r"^[\W_]*$")


def normalize_text(text: str) -> str:
    """Conservative canonicalisation of the preserved text (never a re-write).

    NFKC, LF line endings and collapsed whitespace. Case, punctuation, numbers,
    units, dates and technical identifiers are preserved.
    """
    value = unicodedata.normalize("NFKC", str(text or ""))
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = re.sub(r"[ \t\f\v]+", " ", value)
    value = re.sub(r"\n{2,}", "\n", value)
    return value.strip()


def comparison_form(text: str) -> str:
    """Lowercased, punctuation-stripped form used ONLY for the normalized hash.

    Negations, numbers, units, dates, maths and identifiers survive: only
    punctuation is dropped, and never used to rewrite the stored text.
    """
    value = normalize_text(text).lower()
    value = re.sub(r"[^\w\s]", " ", value, flags=re.UNICODE)
    return re.sub(r"\s+", " ", value).strip()


def _sha256(blob: str) -> str:
    return "sha256:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()


def exact_hash(text: str) -> str:
    return _sha256(normalize_text(text))


def normalized_hash(text: str) -> str:
    return _sha256(comparison_form(text))


def canonical_context_hash() -> str:
    """Context value for rules that do not depend on any predecessor."""
    return _sha256("context-free")


def record_hash(record: dict[str, Any]) -> str:
    """Hash of the record's RELEVANT fields (audit fields never participate)."""
    payload = {
        "text": normalize_text(record.get("text") or ""),
        "tape_type": str(record.get("tape_type") or ""),
        "session": str(record.get("session") or ""),
    }
    return _sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True))


#: Backwards-compatible name used by the frozen decision schema.
input_hash = record_hash


def eligible_predecessors(previous: Sequence[dict[str, Any]],
                          *, window: int = DEDUP_WINDOW) -> list[dict[str, Any]]:
    """The predecessors the duplicate rule actually inspects.

    Same session (the caller's history), non-empty text, most recent
    ``window`` records — future records are never passed in.
    """
    non_empty = [prior for prior in previous if normalize_text(prior.get("text") or "")]
    return non_empty[-int(window):]


def context_hash(record: dict[str, Any], eligible: Sequence[dict[str, Any]],
                 *, window: int = DEDUP_WINDOW) -> str:
    """Hash of everything the duplicate rule actually looks at.

    Covers ``seq``, the configured window and the ordered fingerprints of the
    eligible predecessors. Empty and out-of-window entries are ignored here as
    well, so this function is the single source of truth for the context.
    """
    priors = eligible_predecessors(eligible, window=window)
    payload = {
        "seq": record.get("seq"),
        "session": str(record.get("session") or ""),
        "window": int(window),
        "predecessors": [
            [
                str(prior.get("memory_id") or ""),
                exact_hash(prior.get("text") or ""),
                normalized_hash(prior.get("text") or ""),
            ]
            for prior in priors
        ],
    }
    return _sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def decision_key(*, memory_id: str, input_hash_value: str, arm: str,
                 context_hash_value: str = "", policy_version: str = POLICY_VERSION,
                 schema_version: str = SCHEMA_VERSION) -> str:
    return _sha256("|".join((
        schema_version, policy_version, arm, memory_id, input_hash_value,
        context_hash_value or canonical_context_hash())))


@dataclass(frozen=True)
class Decision:
    memory_id: str
    arm: str
    target_class: str
    promoted: bool
    decisive_reason: str
    reason_codes: tuple[str, ...]
    confidence: float
    input_hash: str
    duplicate_of: str | None = None
    duplicate_kind: str | None = None
    context_hash: str = ""
    schema_version: str = SCHEMA_VERSION
    policy_version: str = POLICY_VERSION
    mode: str = MODE
    decided_at: str = ""

    @property
    def decision_key(self) -> str:
        return decision_key(memory_id=self.memory_id, input_hash_value=self.input_hash,
                            arm=self.arm,
                            context_hash_value=self.context_hash or canonical_context_hash(),
                            policy_version=self.policy_version,
                            schema_version=self.schema_version)

    def normative(self) -> dict[str, Any]:
        """Normative content — audit fields (``decided_at``) excluded."""
        return {
            "schema_version": self.schema_version,
            "policy_version": self.policy_version,
            "memory_id": self.memory_id,
            "input_hash": self.input_hash,
            "context_hash": self.context_hash or canonical_context_hash(),
            "decision_key": self.decision_key,
            "arm": self.arm,
            "mode": self.mode,
            "target_class": self.target_class,
            "promoted": self.promoted,
            "decisive_reason": self.decisive_reason,
            "reason_codes": list(self.reason_codes),
            "confidence": self.confidence,
            "duplicate_of": self.duplicate_of,
            "duplicate_kind": self.duplicate_kind,
        }

    def to_dict(self) -> dict[str, Any]:
        data = self.normative()
        data["decided_at"] = self.decided_at
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Decision":
        return cls(
            memory_id=str(data["memory_id"]),
            arm=str(data.get("arm") or ""),
            target_class=str(data.get("target_class") or ""),
            promoted=bool(data.get("promoted")),
            decisive_reason=str(data.get("decisive_reason") or ""),
            reason_codes=tuple(data.get("reason_codes") or ()),
            confidence=float(data.get("confidence") or 0.0),
            input_hash=str(data.get("input_hash") or ""),
            duplicate_of=data.get("duplicate_of"),
            duplicate_kind=data.get("duplicate_kind"),
            context_hash=str(data.get("context_hash") or ""),
            schema_version=str(data.get("schema_version") or SCHEMA_VERSION),
            policy_version=str(data.get("policy_version") or POLICY_VERSION),
            mode=str(data.get("mode") or MODE),
            decided_at=str(data.get("decided_at") or ""),
        )


# ---------------------------------------------------------------------------
# Precedence (frozen order: invalid > secret > correction > typed > duplicate
# > stability > action/result > chatter > ambiguous > no signal)


def _classify(record: dict[str, Any], previous: Sequence[dict[str, Any]],
              *, arm: str = "B", window: int = DEDUP_WINDOW) -> Decision:
    text = normalize_text(record.get("text") or "")
    tape_type = str(record.get("tape_type") or "")
    memory_id = str(record.get("memory_id") or "")
    in_hash = record_hash(record)
    context = canonical_context_hash()

    def make(target_class: str, reason: str, codes: Iterable[str],
             *, duplicate_of: str | None = None,
             duplicate_kind: str | None = None,
             context: str | None = None) -> Decision:
        return Decision(
            memory_id=memory_id, arm=arm, target_class=target_class,
            promoted=target_class in PROMOTED_CLASSES, decisive_reason=reason,
            reason_codes=tuple(dict.fromkeys(codes)), confidence=CONFIDENCE[reason],
            input_hash=in_hash, duplicate_of=duplicate_of,
            duplicate_kind=duplicate_kind,
            context_hash=context or canonical_context_hash(),
        )

    if not text or PUNCT_ONLY.match(text):
        return make("reject", "invalid_record", ["invalid_record"])
    if scan_text(text):
        return make("reject", "secret_blocked", ["secret_blocked"])

    if CORRECTION_MARKERS.search(text):
        codes = ["correction"]
        if DECISION_CHANGE_MARKERS.search(text):
            codes.append("decision_change")
            return make("semantic", "decision_change", codes)
        return make("semantic", "correction", codes)

    if tape_type in _TYPED:
        return make("semantic", "typed_record", ["typed_record", tape_type])

    # The duplicate rule is the first context-dependent level: from here on the
    # decision identity must cover the window actually inspected.
    eligible = eligible_predecessors(previous, window=window)
    context = context_hash(record, previous, window=window)
    current_exact = exact_hash(text)
    current_norm = normalized_hash(text)
    for prior in reversed(eligible):
        prior_text = normalize_text(prior.get("text") or "")
        if not prior_text:
            continue
        if exact_hash(prior_text) == current_exact:
            return make("reject", "duplicate_exact", ["duplicate_exact"],
                        duplicate_of=str(prior.get("memory_id")), duplicate_kind="exact",
                        context=context)
        if normalized_hash(prior_text) == current_norm:
            return make("reject", "duplicate_normalized", ["duplicate_normalized"],
                        duplicate_of=str(prior.get("memory_id")),
                        duplicate_kind="normalized", context=context)

    codes: list[str] = []
    if DECISION_MARKERS.search(text):
        codes.append("decision")
    if PREFERENCE_MARKERS.search(text):
        codes.append("preference")
    if RESTRICTION_MARKERS.search(text):
        codes.append("restriction")
    if codes:
        decisive = "restriction" if "restriction" in codes else codes[0]
        return make("semantic", decisive, codes, context=context)

    codes = []
    if ACTION_MARKERS.search(text):
        codes.append("action_taken")
    if FAILURE_MARKERS.search(text):
        codes.append("failure_context")
    if RESULT_MARKERS.search(text):
        codes.append("experiment_result")
    if codes:
        return make("episodic", codes[0], codes, context=context)

    if GREETING_MARKERS.search(text):
        return make("event_only", "greeting", ["greeting"], context=context)
    if ACK_MARKERS.search(text):
        return make("event_only", "ack", ["ack"], context=context)

    if AMBIGUOUS_MARKERS.search(text):
        return make("episodic", "ambiguous",
                    ["ambiguous", "possible_preference", "future_intent"],
                    context=context)

    return make("event_only", "no_durable_signal", ["no_durable_signal"],
                context=context)


def classify_record(record: dict[str, Any], previous: Sequence[dict[str, Any]] = (),
                    *, arm: str = "B", window: int = DEDUP_WINDOW) -> Decision:
    """Public, pure entry point (no I/O; deterministic)."""
    return _classify(record, previous, arm=arm, window=window)


def classify_records(records: Sequence[dict[str, Any]], *, arm: str = "B",
                     session_window: bool = True,
                     window: int = DEDUP_WINDOW) -> list[Decision]:
    """Classify records in tape order; each record sees only PRIOR records.

    The dedup window is sequence-based: the last ``DEDUP_WINDOW`` records of
    the same session (or of the whole stream when sessions are absent).
    """
    decisions: list[Decision] = []
    prior_same_session: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        session = str(record.get("session") or "")
        history = prior_same_session.get(session, []) if session_window else []
        decisions.append(_classify(record, history, arm=arm, window=window))
        prior_same_session.setdefault(session, []).append(record)
    return decisions


# ---------------------------------------------------------------------------
# Projection (rebuildable, atomic, never partially visible)


class LifecycleConflict(RuntimeError):
    """Same decision_key with different normative content."""


def order_key(record: dict[str, Any], index: int = 0) -> tuple:
    seq = record.get("seq")
    return (seq if isinstance(seq, int) else index, str(record.get("memory_id") or ""))


class LifecycleProjection:
    """``<root>/lifecycle/`` writer with idempotent batches and atomic rebuild."""

    def __init__(self, root: Path, *, arm: str = "B") -> None:
        self.root = Path(root)
        self.dir = self.root / "lifecycle"
        self.arm = arm

    # -- reading -----------------------------------------------------------

    def decisions_path(self) -> Path:
        return self.dir / "decisions.jsonl"

    def load_decisions(self) -> list[dict[str, Any]]:
        path = self.decisions_path()
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip()]

    def existing_keys(self) -> dict[str, dict[str, Any]]:
        return {row["decision_key"]: row for row in self.load_decisions()}

    # -- writing -----------------------------------------------------------

    def append_decisions(self, decisions: Sequence[Decision]) -> list[Decision]:
        """Append a fully-computed batch.

        Idempotent: identical keys are skipped; a key with different normative
        content raises ``LifecycleConflict``. Nothing is written until every
        decision of the batch exists.
        """
        existing = self.existing_keys()
        fresh: list[Decision] = []
        for decision in decisions:
            key = decision.decision_key
            if key in existing:
                if existing[key].get("target_class") != decision.target_class or \
                        existing[key].get("promoted") != decision.promoted or \
                        tuple(existing[key].get("reason_codes") or ()) != decision.reason_codes:
                    raise LifecycleConflict(
                        f"{key}: existing decision differs from the new one")
                continue
            fresh.append(decision)
        if fresh:
            self.dir.mkdir(parents=True, exist_ok=True)
            blob = "".join(
                json.dumps(d.to_dict(), ensure_ascii=False, sort_keys=True) + "\n"
                for d in fresh).encode("utf-8")
            with self.decisions_path().open("ab") as handle:  # single append, all lines
                handle.write(blob)
                handle.flush()
                os.fsync(handle.fileno())
        return fresh

    def write_manifest(self, *, records: Sequence[dict[str, Any]],
                       decisions: Sequence[Decision]) -> dict[str, Any]:
        payload = {
            "schema_version": SCHEMA_VERSION,
            "policy_version": POLICY_VERSION,
            "arm": self.arm,
            "mode": MODE,
            "records_sha256": _sha256(json.dumps(
                [order_key(r, i) for i, r in enumerate(records)] +
                [normalize_text(r.get("text") or "") for r in records],
                ensure_ascii=False, sort_keys=True)),
            "decisions_sha256": _sha256(json.dumps(
                [d.normative() for d in decisions], ensure_ascii=False, sort_keys=True)),
            "counts": {
                "records": len(records),
                "decisions": len(decisions),
                "promoted": sum(1 for d in decisions if d.promoted),
            },
        }
        self.dir.mkdir(parents=True, exist_ok=True)
        target = self.dir / "manifest.json"
        tmp = self.dir / "manifest.json.tmp"
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n",
                       encoding="utf-8")
        os.replace(tmp, target)
        return payload

    def rebuild(self, records: Sequence[dict[str, Any]]) -> dict[str, Any]:
        """Rebuild the whole projection in a temp dir and swap it into place."""
        building = self.dir.with_name(self.dir.name + ".building")
        if building.exists():
            shutil.rmtree(building)
        building.mkdir(parents=True)
        ordered = sorted(enumerate(records), key=lambda pair: order_key(pair[1], pair[0]))
        decisions = classify_records([r for _i, r in ordered], arm=self.arm)
        blob = "".join(
            json.dumps(d.to_dict(), ensure_ascii=False, sort_keys=True) + "\n"
            for d in decisions).encode("utf-8")
        (building / "decisions.jsonl").write_bytes(blob)
        payload = {
            "schema_version": SCHEMA_VERSION,
            "policy_version": POLICY_VERSION,
            "arm": self.arm,
            "mode": MODE,
            "records_sha256": _sha256(json.dumps(
                [order_key(r, i) for i, r in ordered] +
                [normalize_text(r.get("text") or "") for _i, r in ordered],
                ensure_ascii=False, sort_keys=True)),
            "decisions_sha256": _sha256(json.dumps(
                [d.normative() for d in decisions], ensure_ascii=False, sort_keys=True)),
            "counts": {
                "records": len(records),
                "decisions": len(decisions),
                "promoted": sum(1 for d in decisions if d.promoted),
            },
        }
        (building / "manifest.json").write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        if self.dir.exists():
            shutil.rmtree(self.dir)
        os.rename(building, self.dir)
        return payload
