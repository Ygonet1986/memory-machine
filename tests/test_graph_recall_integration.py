import json
import shutil

from memory_machine.config import Config
from memory_machine.coordinator import Machine
from memory_machine.tape import MemoryRecord

from fakes import FakeClient, text

CROSS_PAYLOAD = json.dumps(
    {
        "entities": [
            {"ref": "e1", "name": "Kalak", "type": "person"},
            {"ref": "e2", "name": "rochedo", "type": "place"},
        ],
        "events": [],
        "relations": [
            {"source": "e1", "relation": "cross", "target": "e2", "confidence": 0.9}
        ],
    }
)
FIND_PAYLOAD = json.dumps(
    {
        "entities": [
            {"ref": "e1", "name": "Kalak", "type": "person"},
            {"ref": "e3", "name": "petronante", "type": "creature"},
        ],
        "events": [],
        "relations": [
            {"source": "e1", "relation": "find", "target": "e3", "confidence": 0.8}
        ],
    }
)
EMPTY_PAYLOAD = '{"entities":[],"events":[],"relations":[]}'
NO_ANNOTATIONS = '{"digest":"g","annotations":[],"coverage":"complete","missing":[]}'


def _annotations_for(memory_id):
    return json.dumps(
        {
            "digest": "g",
            "annotations": [
                {"memory_id": memory_id, "note": "agent note", "relevance": 0.5}
            ],
            "coverage": "complete",
            "missing": [],
        }
    )


def _handler(agent_payload):
    def handler(messages, temperature):
        system = text(messages, "system")
        if "memory agent" in system:
            return agent_payload
        user = text(messages, "user")
        if "crossed" in user:
            return CROSS_PAYLOAD
        if "found" in user:
            return FIND_PAYLOAD
        return EMPTY_PAYLOAD

    return handler


def _machine(
    tmp_path,
    *,
    mode="augment",
    enabled=True,
    agent_payload=NO_ANNOTATIONS,
    budget=0,
):
    cfg = Config(
        capacity=50,
        router_enabled=False,
        graph_enabled=enabled,
        graph_recall_mode=mode,
    )
    if budget:
        cfg.evidence_payload = "budgeted"
        cfg.evidence_payload_budget = budget
    client = FakeClient(_handler(agent_payload))
    machine = Machine(tmp_path, config=cfg, client=client)
    machine.add_memory(
        MemoryRecord(type="decision", summary="Kalak crossed the rock", why="at dusk")
    )
    machine.add_memory(
        MemoryRecord(type="lesson", summary="Kalak found a petronante", why="later")
    )
    machine.save()
    return machine, client


def test_off_is_structurally_unchanged(tmp_path):
    machine, _client = _machine(tmp_path, mode="off")

    result = machine.recall("Kalak")

    assert result["ok"] is True
    assert "graph_evidence" not in result
    assert "graph_metrics" not in result
    assert "graph_mode" not in result


def test_off_never_calls_graph_recall(tmp_path, monkeypatch):
    machine, _client = _machine(tmp_path, mode="off")

    def boom(self, question):
        raise AssertionError("graph recall must not run when off")

    monkeypatch.setattr(Machine, "_graph_recall", boom)

    assert machine.recall("Kalak")["ok"] is True


def test_graph_disabled_never_calls_graph_recall(tmp_path, monkeypatch):
    machine, _client = _machine(tmp_path, mode="augment", enabled=False)

    def boom(self, question):
        raise AssertionError("graph recall must not run when disabled")

    monkeypatch.setattr(Machine, "_graph_recall", boom)

    assert machine.recall("Kalak")["ok"] is True


def test_augment_finds_graph_only_memories(tmp_path):
    machine, _client = _machine(tmp_path, mode="augment", agent_payload=NO_ANNOTATIONS)

    result = machine.recall("Kalak")

    assert result["graph_mode"] == "augment"
    assert {item["memory_id"] for item in result["annotations"]} == {"M0001", "M0002"}
    assert result["graph_metrics"]["graph_only_memories"] == 2
    assert result["graph_metrics"]["overlap_memories"] == 0
    assert result["graph_evidence"]


def test_augment_dedupes_overlap_and_preserves_reasons(tmp_path):
    machine, _client = _machine(
        tmp_path, mode="augment", agent_payload=_annotations_for("M0001")
    )

    result = machine.recall("Kalak")

    ids = [item["memory_id"] for item in result["annotations"]]
    assert sorted(ids) == sorted(set(ids))
    assert set(ids) == {"M0001", "M0002"}
    assert result["graph_metrics"]["overlap_memories"] == 1
    assert result["graph_metrics"]["graph_only_memories"] == 1


def test_only_ignores_agents(tmp_path):
    machine, client = _machine(tmp_path, mode="only")
    client.calls.clear()

    result = machine.recall("Kalak")

    assert result["graph_mode"] == "only"
    assert client.calls == []
    assert {item["memory_id"] for item in result["annotations"]} == {"M0001", "M0002"}


def test_only_still_rehydrates_from_the_tape(tmp_path):
    machine, _client = _machine(tmp_path, mode="only", budget=500)

    result = machine.recall("Kalak")

    assert result["evidence_payload"]
    payload_ids = {item["memory_id"] for item in result["evidence_payload"]}
    assert payload_ids == {"M0001", "M0002"}
    context = " ".join(item["evidence"] for item in result["evidence_payload"])
    assert "Kalak" in context


def test_graph_absent_degrades_to_normal_recall(tmp_path):
    machine, _client = _machine(
        tmp_path, mode="augment", agent_payload=_annotations_for("M0001")
    )
    shutil.rmtree(tmp_path / "graph")

    result = machine.recall("Kalak")

    assert result["ok"] is True
    assert result["graph_evidence"] == []
    assert {item["memory_id"] for item in result["annotations"]} == {"M0001"}


def test_corrupt_graph_degrades(tmp_path):
    machine, _client = _machine(
        tmp_path, mode="augment", agent_payload=_annotations_for("M0001")
    )
    (tmp_path / "graph" / "entities.jsonl").write_text("}{ not json\n", encoding="utf-8")

    result = machine.recall("Kalak")

    assert result["ok"] is True
    assert {item["memory_id"] for item in result["annotations"]} == {"M0001"}


def test_archived_memory_is_not_annotated(tmp_path):
    machine, _client = _machine(tmp_path, mode="augment", agent_payload=NO_ANNOTATIONS)
    machine.tape.set_status("M0002", "archived")

    result = machine.recall("Kalak")

    assert {item["memory_id"] for item in result["annotations"]} == {"M0001"}
    payload_ids = {item["memory_id"] for item in result.get("evidence_payload") or []}
    assert "M0002" not in payload_ids


def test_global_budget_is_applied_after_the_union(tmp_path):
    machine, _client = _machine(tmp_path, mode="only", budget=300)

    result = machine.recall("Kalak")

    assert result["evidence_payload_chars"] <= 300


def test_graph_metrics_keys(tmp_path):
    machine, _client = _machine(tmp_path, mode="augment")

    metrics = machine.recall("Kalak")["graph_metrics"]

    assert set(metrics) == {
        "graph_seed_entities",
        "graph_paths_considered",
        "graph_paths_selected",
        "graph_unique_memories",
        "graph_recall_ms",
        "graph_only_memories",
        "overlap_memories",
    }
    assert metrics["graph_seed_entities"] >= 1
