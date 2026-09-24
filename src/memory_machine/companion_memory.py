"""Companion-only administrative memory operations and active evidence.

No existing session path calls this adapter. It intentionally does not use
cross-session search or the active admission-shadow instrumentation.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from .groups import ensure_group, load_manifest, save_manifest
from .payload import build_evidence_payload
from .retrieval import rank
from .tape import MemoryRecord, Tape, parse_id
from .whiteboard import Annotation


class CompanionMemory:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.tape = Tape(self.root / "tape.jsonl")

    def active(self) -> list[MemoryRecord]:
        return [record for record in self.tape.read() if record.status == "active"]

    def search(self, question: str, *, limit: int = 5) -> list[MemoryRecord]:
        records = self.active()
        docs = [f"{r.summary} {r.why}" for r in records]
        return [records[i] for i, _score in rank(question, docs, limit=limit)]

    def evidence(self, memory_ids: list[str], *, budget: int = 4000) -> list[dict]:
        records = {record.id: record for record in self.active()}
        annotations = [
            Annotation(memory_id=memory_id, note="Companion recall", relevance=1.0)
            for memory_id in memory_ids if memory_id in records
        ]
        return build_evidence_payload(records, annotations, budget=budget)

    def supersede(self, memory_id: str, replacement: MemoryRecord) -> MemoryRecord:
        record, _affected = self.tape.supersede(memory_id, replacement)
        self._invalidate_derived_state(record.id)
        return record

    def delete(self, memory_id: str) -> list[str]:
        removed = self.tape.delete_cascade(memory_id)
        if removed:
            self._invalidate_derived_state()
        return removed

    def _invalidate_derived_state(self, new_id: str = "") -> None:
        for name in ("recall_cache.json", "whiteboard.json", "context.json",
                     "session.json"):
            (self.root / name).unlink(missing_ok=True)
        # The Companion owns this root; discard derived graph data for a clean
        # rebuild from active tape records if graph support is added later.
        graph_path = self.root / "graph"
        if graph_path.is_dir():
            shutil.rmtree(graph_path)

        manifest_path = self.root / "manifest.json"
        manifest = load_manifest(manifest_path)
        if new_id:
            ensure_group(manifest, parse_id(new_id))
        for agent in manifest.agents:
            agent.checklist = agent.digest = agent.understanding = ""
            agent.checklist_records = agent.digest_records = agent.understanding_records = 0
        manifest.view_agents.clear()
        save_manifest(manifest, manifest_path)
