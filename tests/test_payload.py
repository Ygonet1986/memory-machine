import json

from memory_machine.config import Config
from memory_machine.coordinator import Machine
from memory_machine.payload import build_evidence_payload, payload_as_context
from memory_machine.tape import MemoryRecord, Tape
from memory_machine.whiteboard import Annotation

from fakes import FakeClient


def _records(*records):
    return {r.id: r for r in records}


def test_payload_respects_budget_and_relevance():
    records = _records(
        MemoryRecord(id="M0001", type="decision", summary="high", why="w" * 200),
        MemoryRecord(id="M0002", type="lesson", summary="mid", why="w" * 200),
        MemoryRecord(id="M0003", type="lesson", summary="low", why="w" * 200),
    )
    annotations = [
        Annotation(memory_id="M0001", note="a", relevance=0.9),
        Annotation(memory_id="M0002", note="b", relevance=0.5),
        Annotation(memory_id="M0003", note="c", relevance=0.1),
    ]
    payload = build_evidence_payload(records, annotations, budget=600, min_item_chars=100)
    assert len(payload) == 3
    assert sum(item["used_chars"] for item in payload) <= 600
    assert payload[0]["memory_id"] == "M0001"  # highest relevance first
    assert payload[0]["used_chars"] >= payload[2]["used_chars"]


def test_payload_preserves_summary_and_cuts_why():
    records = _records(
        MemoryRecord(id="M0001", type="decision", summary="short summary", why="x" * 2000)
    )
    payload = build_evidence_payload(
        records, [Annotation(memory_id="M0001", note="n", relevance=0.9)],
        budget=120, min_item_chars=0,
    )
    item = payload[0]
    assert "short summary" in item["evidence"]
    assert item["truncated"] is True
    assert item["used_chars"] <= 120


def test_payload_rehydrates_rollup_sources():
    tape = Tape(__import__("pathlib").Path("/tmp/mm-payload-test.jsonl"))
    if tape.exists():
        tape.path.unlink()
    tape.append(
        MemoryRecord(id="M0001", type="decision", summary="source one", why="why one",
                     status="archived")
    )
    tape.append(
        MemoryRecord(id="M0002", type="rollup", summary="rollup", why="",
                     derived_from=["M0001"])
    )
    payload = build_evidence_payload(
        {r.id: r for r in tape.read()},
        [Annotation(memory_id="M0002", note="n", relevance=0.9)],
        budget=500, min_item_chars=0,
    )
    item = payload[0]
    assert item["source"] == "rehydrated"
    assert item["derived_from"] == ["M0001"]
    assert "source one" in item["evidence"]
    tape.path.unlink()


def test_payload_empty_annotations():
    assert build_evidence_payload({}, []) == []


def test_recall_payload_is_not_persisted(tmp_path):
    def handler(messages, temperature):
        return (
            '{"digest":"d","checklist":[],"annotations":'
            '[{"memory_id":"M0001","note":"router note","relevance":0.9}],'
            '"coverage":"complete"}'
        )

    m = Machine(
        tmp_path,
        config=Config(capacity=10, evidence_payload="budgeted"),
        client=FakeClient(handler),
    )
    m.add_memory(
        MemoryRecord(type="decision", summary="router opt-in", why="why router")
    )
    res = m.recall("what about the router?")
    assert res["evidence_payload"]
    assert res["evidence_payload_chars"] > 0
    assert "router opt-in" in payload_as_context(res["evidence_payload"])
    # the payload is recall-local: the persisted whiteboard has the note, not the evidence
    raw = json.loads((tmp_path / "whiteboard.json").read_text())
    assert "router note" in json.dumps(raw)
    assert "[M0001 |" not in json.dumps(raw)


def test_run_appends_payload_to_context(tmp_path):
    seen: dict[str, str] = {}

    def handler(messages, temperature):
        system = "\n".join(m.get("content", "") for m in messages if m.get("role") == "system")
        if "memory agent" in system:
            return (
                '{"digest":"d","checklist":[],"annotations":'
                '[{"memory_id":"M0001","note":"router note","relevance":0.9}],'
                '"coverage":"complete"}'
            )
        seen["user"] = "\n".join(
            m.get("content", "") for m in messages if m.get("role") == "user"
        )
        return "The router is opt-in."

    m = Machine(
        tmp_path,
        config=Config(capacity=10, evidence_payload="budgeted"),
        client=FakeClient(handler),
    )
    m.add_memory(
        MemoryRecord(type="decision", summary="router opt-in", why="why router")
    )
    res = m.run("why is the router opt-in?")
    assert res["evidence_payload_chars"] > 0
    assert "router opt-in" in seen["user"]
