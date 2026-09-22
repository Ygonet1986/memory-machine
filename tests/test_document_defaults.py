"""N10 conformance: the shipped document layer's defaults are bounded.

With `document_graph_enabled=True` (shipped write-time layer) and
`graph_enabled=False` (recall), a clean configuration must: save chunks even
when the projection cannot run, make no LLM call when the graph is explicitly
disabled, never touch the graph during recall, and stay idempotent on
re-ingestion. These tests pin the exact scope of N10.
"""

from __future__ import annotations

import json

from memory_machine.config import Config
from memory_machine.coordinator import Machine
from memory_machine.tape import Tape

AGENT_JSON = (
    '{"digest":"d","checklist":[],"annotations":'
    '[{"memory_id":"M0001","note":"router note","relevance":0.9}],'
    '"coverage":"complete"}'
)

CONTENT = "Kalak crossed the rock. Kalak fostered the birds. " * 4


class GuardClient:
    """Records calls; optionally raises if it is ever called."""

    def __init__(self, *, forbid: bool = False):
        self.forbid = forbid
        self.calls = 0

    def complete(self, messages, *, temperature: float = 0.0) -> str:
        self.calls += 1
        if self.forbid:
            raise AssertionError("LLM must not be called in this scenario")
        return AGENT_JSON

    def complete_with_reasoning(self, messages, *, temperature: float = 0.0):
        self.calls += 1
        if self.forbid:
            raise AssertionError("LLM must not be called in this scenario")
        return AGENT_JSON, ""


def test_projection_failure_does_not_block_ingestion(tmp_path, monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    src = tmp_path / "guide.txt"
    src.write_text(CONTENT, encoding="utf-8")
    machine = Machine(tmp_path, config=Config(capacity=10), client=None)

    result = machine.ingest_document(src)
    assert result["ok"] is True
    assert result["saved"] == result["chunks"] >= 1
    # projection could not run (no client) but the tape is committed
    assert result["document_graph"]["applied"] == 0
    assert len(machine.tape.read()) == result["saved"]


def test_enable_graph_false_makes_no_llm_calls(tmp_path):
    src = tmp_path / "guide.txt"
    src.write_text(CONTENT, encoding="utf-8")
    guard = GuardClient(forbid=True)
    machine = Machine(tmp_path, config=Config(capacity=10), client=guard)

    result = machine.ingest_document(src, enable_graph=False)
    assert result["ok"] is True and result["saved"] >= 1
    assert guard.calls == 0
    assert not (tmp_path / "graph").exists()


def test_default_recall_never_touches_the_graph(tmp_path):
    from memory_machine.tape import MemoryRecord

    guard = GuardClient()
    machine = Machine(tmp_path, config=Config(capacity=10), client=guard)
    machine.add_memory(MemoryRecord(type="decision", summary="use Postgres",
                                    views=["topic/db"]))
    machine.whiteboard.subject = "database"

    machine.recall("which database?")
    assert not (tmp_path / "graph").exists()  # graph recall stays off
    assert guard.calls == 1  # exactly one agent call, no router/graph calls


def test_reingestion_preserves_previous_chunk_bytes(tmp_path):
    src = tmp_path / "guide.txt"
    src.write_text(CONTENT, encoding="utf-8")
    guard = GuardClient(forbid=True)
    machine = Machine(tmp_path, config=Config(capacity=10), client=guard)

    machine.ingest_document(src, enable_graph=False)
    first_pass = {
        r.id: json.dumps(r.to_dict(), ensure_ascii=False) for r in machine.tape.read()
    }
    second = machine.ingest_document(src, enable_graph=False)
    second_pass = {
        r.id: json.dumps(r.to_dict(), ensure_ascii=False) for r in machine.tape.read()
    }
    assert second_pass == first_pass  # idempotent, byte-for-byte content
    assert second["saved"] == 0  # chunks already exist; nothing re-written
    assert len(second_pass) == len(first_pass)
