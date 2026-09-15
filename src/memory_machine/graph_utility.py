"""Plasticity (Fase P) — learned path priority over the graph.

P0 scope: a deterministic, auditable utility ledger. The ledger learns *which
paths to search for* (navigation preference), never what a document "said".
It is a derived, disposable projection:

- Tape, graph, evidence and recall are never touched by ``UtilityLedger``.
- ``plasticity_mode="off"`` (the default) leaves every prior behavior
  byte-equivalent: nothing here is wired into recall yet (P1).
- ``EdgeKey`` identity includes ``extraction_scope``; ``R####``, document and
  memory ids are audit-only, never resolution criteria.

Storage (all under ``<root>/plasticity/``):

- ``events.jsonl`` — append-only source of truth (one event per ``record``).
- ``utility.jsonl`` — append-only materialization; on load the last row per
  key wins. ``rebuild()`` replays ``events.jsonl`` deterministically.
- ``reset()`` deletes both files and restores the baseline (no learned state).
"""

from __future__ import annotations

import copy as _copy
import datetime as _dt
import json
import os
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

# Pre-registered policy (docs/PLASTICITY_V1.md). Changing any of these
# constants is a re-pre-registration; events carry the values actually used.
POLICY_VERSION = "p0"
DEFAULT_SCOPE = "chunk"
DEFAULT_LAMBDA = 0.01  # decay per update: u' = (1 - λ)·u + η·s
DEFAULT_ETA = 0.10     # learning rate of the signal
CLIP_MIN = 1.0         # u ∈ [-1, 1]; permanent dominance is impossible
CLIP_MAX = 1.0
SHRINKAGE_K = 5.0      # u_eff = u·n/(n+k): few observations ⇒ low confidence
HOP_COST = 0.15        # per extra hop (semantic_depth - 1)
WEIGHT_UTILITY = 0.5   # weight of learned utility in the energy


def _utcnow() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


def _clamp(value: float, clip_min: float = CLIP_MIN, clip_max: float = CLIP_MAX) -> float:
    return max(-clip_min, min(clip_max, value))


@dataclass(frozen=True, order=True)
class EdgeKey:
    """Stable identity of a navigable edge.

    ``source``/``target`` are entity ids (E####), ``relation`` is the canonical
    verb and ``extraction_scope`` the provenance scope (empty → ``chunk``).
    ``from_relation`` ignores ``R####``, ``source_document`` and ``memory_id``:
    they are audit-only.
    """

    source: str
    relation: str
    target: str
    extraction_scope: str = DEFAULT_SCOPE

    @classmethod
    def from_relation(cls, relation: Any) -> "EdgeKey":
        source = (relation.source or "").strip()
        target = (relation.target or "").strip()
        verb = (relation.relation or "").strip().lower()
        scope = (relation.extraction_scope or "").strip().lower()
        if not scope:
            scope = DEFAULT_SCOPE
        return cls(
            source=source or "?",
            relation=verb or "?",
            target=target or "?",
            extraction_scope=scope,
        )

    def to_key(self) -> str:
        return "|".join((self.source, self.relation, self.target, self.extraction_scope))

    @classmethod
    def from_key(cls, key: str) -> "EdgeKey":
        parts = key.split("|")
        if len(parts) != 4:
            raise ValueError(f"invalid edge key: {key!r}")
        return cls(*parts)


@dataclass
class LedgerRow:
    key: str
    utility: float = 0.0
    observations: int = 0
    successes: int = 0
    failures: int = 0
    last_updated: str = ""
    policy_version: str = POLICY_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LedgerRow":
        return cls(
            key=str(data.get("key") or ""),
            utility=float(data.get("utility") or 0.0),
            observations=int(data.get("observations") or 0),
            successes=int(data.get("successes") or 0),
            failures=int(data.get("failures") or 0),
            last_updated=str(data.get("last_updated") or ""),
            policy_version=str(data.get("policy_version") or POLICY_VERSION),
        )


def shrink(utility: float, observations: int, k: float = SHRINKAGE_K) -> float:
    """Confidence-shrink learned utility: u_eff = u·n/(n+k)."""
    if observations <= 0 or k <= 0:
        return 0.0
    return utility * (observations / (observations + k))


def apply_update(
    utility: float,
    signal: float,
    *,
    lam: float = DEFAULT_LAMBDA,
    eta: float = DEFAULT_ETA,
    clip_min: float = CLIP_MIN,
    clip_max: float = CLIP_MAX,
) -> float:
    """Conservative, bounded update: u' = clip((1-λ)·u + η·s, -min, max)."""
    return _clamp((1.0 - lam) * utility + eta * signal, clip_min, clip_max)


@dataclass(frozen=True)
class NavPath:
    edges: tuple[EdgeKey, ...]
    semantic_depth: int = 1


def energy(
    path: NavPath,
    query_distance: float,
    ledger: "UtilityLedger",
    *,
    weight_utility: float = WEIGHT_UTILITY,
    hop_cost: float = HOP_COST,
    risk_penalty: float = 0.0,
    k: float = SHRINKAGE_K,
) -> float:
    """E(path|q) = D + H − w_u·U + R.

    ``D`` is the mechanical query distance (external, P1), ``H`` is the hop
    cost, ``U`` the mean shrunk utility over the path's edges and ``R`` a
    risk penalty (e.g. evidence-gate veto). Lower is preferred.
    """
    if not path.edges:
        return query_distance + risk_penalty
    carried = 0.0
    for edge in path.edges:
        row = ledger.get(edge)
        carried += shrink(row.utility, row.observations, k)
    learned = carried / len(path.edges)
    hops = hop_cost * max(0, path.semantic_depth - 1)
    return query_distance + hops - weight_utility * learned + risk_penalty


class UtilityLedger:
    """Append-only, replay-reconstructible ledger of edge utility.

    Never touches Tape, graph, evidence or recall. All state lives under
    ``<root>/plasticity/``.
    """

    def __init__(self, root: Path | str, *, policy_version: str = POLICY_VERSION) -> None:
        self.root = Path(root)
        self.dir = self.root / "plasticity"
        self.events_path = self.dir / "events.jsonl"
        self.utility_path = self.dir / "utility.jsonl"
        self.policy_version = policy_version
        self._rows: dict[str, LedgerRow] = {}
        self.load()

    # ------------------------------------------------------------------ read
    def get(self, edge: EdgeKey | str) -> LedgerRow:
        key = edge.to_key() if isinstance(edge, EdgeKey) else edge
        return self._rows.get(key, LedgerRow(key=key, policy_version=self.policy_version))

    def rows(self) -> dict[str, LedgerRow]:
        return dict(self._rows)

    @property
    def is_empty(self) -> bool:
        return not self._rows

    # ---------------------------------------------------------------- write
    def record(
        self,
        edge: EdgeKey,
        signal: float,
        *,
        query: str = "",
        path_ref: str = "",
        evidenced: bool = True,
        lam: float = DEFAULT_LAMBDA,
        eta: float = DEFAULT_ETA,
    ) -> LedgerRow:
        """Record one mechanical signal on the edge.

        ``evidenced=False`` (no valid provenance) blocks reinforcement: the
        event is still logged for audit but no utility/counter changes.
        """
        key = edge.to_key()
        before = self.get(edge)
        now = _utcnow()
        row = _copy.copy(before)
        if evidenced:
            after = apply_update(row.utility, signal, lam=lam, eta=eta)
            row.utility = after
            row.observations += 1
            if signal > 0:
                row.successes += 1
            elif signal < 0:
                row.failures += 1
            row.last_updated = now
            row.policy_version = self.policy_version
        else:
            after = row.utility
        event = {
            "ts": now,
            "key": key,
            "signal": signal,
            "query": query,
            "path_ref": path_ref,
            "evidenced": evidenced,
            "reinforced": evidenced,
            "before": before.utility,
            "after": after,
            "lam": lam,
            "eta": eta,
            "policy_version": self.policy_version,
        }
        self._append(self.events_path, event)
        self._append(self.utility_path, row.to_dict())
        self._rows[key] = row
        return row

    # ------------------------------------------------------------- plumbing
    def load(self) -> None:
        """Load materialized utility, latest row per key wins."""
        rows: dict[str, LedgerRow] = {}
        for line in self._lines(self.utility_path):
            data = _parse_line(line)
            if data is None or not isinstance(data.get("key"), str) or not data.get("key"):
                continue
            try:
                row = LedgerRow.from_dict(data)
            except (TypeError, ValueError):
                continue
            rows[row.key] = row
        self._rows = rows

    def rebuild(self) -> dict[str, LedgerRow]:
        """Replay ``events.jsonl`` from scratch; rewrite ``utility.jsonl``.

        Deterministic: a re-replay reproduces the same final state a sequence
        of ``record`` calls produced (events carry the λ/η actually used).
        """
        rows: dict[str, LedgerRow] = {}
        for line in self._lines(self.events_path):
            event = _parse_line(line)
            if event is None or not event.get("key"):
                continue
            key = str(event["key"])
            row = rows.get(key, LedgerRow(key=key, policy_version=self.policy_version))
            if not (event.get("reinforced", True) and event.get("evidenced", True)):
                # No valid provenance ⇒ logged but never changes state.
                rows[key] = row
                continue
            lam = float(event.get("lam") or DEFAULT_LAMBDA)
            eta = float(event.get("eta") or DEFAULT_ETA)
            signal = float(event.get("signal") or 0.0)
            row.utility = apply_update(row.utility, signal, lam=lam, eta=eta)
            row.observations += 1
            if signal > 0:
                row.successes += 1
            elif signal < 0:
                row.failures += 1
            row.last_updated = str(event.get("ts") or "")
            row.policy_version = str(event.get("policy_version") or row.policy_version)
            rows[key] = row
        self._rows = rows
        self._rewrite(self.utility_path, rows.values())
        return rows

    def reset(self) -> None:
        """Delete ledger state; baseline is restored (no learned state)."""
        self._rows = {}
        self.events_path.unlink(missing_ok=True)
        self.utility_path.unlink(missing_ok=True)

    # ----------------------------------------------------------------- util
    def _append(self, path: Path, data: dict[str, Any]) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(data, ensure_ascii=False) + "\n")
            fh.flush()
            os.fsync(fh.fileno())

    def _rewrite(self, path: Path, rows: Any) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row.to_dict(), ensure_ascii=False) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)

    @staticmethod
    def _lines(path: Path) -> list[str]:
        try:
            return path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []


def _parse_line(line: str) -> dict[str, Any] | None:
    line = line.strip()
    if not line:
        return None
    try:
        data = json.loads(line)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None