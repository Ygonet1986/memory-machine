"""Graph projection hygiene: dead evidence cannot route to active memories."""

from __future__ import annotations

import json

from fakes import FakeClient
from memory_machine.config import Config
from memory_machine.coordinator import Machine
from memory_machine.graph import GraphStore


def _extract(messages, temperature):
    assert "memory graph agent" in messages[0]["content"]
    body = messages[1]["content"]
    entities = []
    relations = []
    refs: dict[str, str] = {}

    def ref(name: str) -> str:
        if name not in refs:
            key = f"e{len(refs) + 1}"
            refs[name] = key
            entities.append({"ref": key, "name": name, "type": "concept"})
        return refs[name]

    for name in ("Lia", "jardim", "Nina", "praça"):
        if name in body:
            ref(name)
    if "Lia" in body and "jardim" in body:
        relations.append({"source": ref("Lia"), "target": ref("jardim"),
                          "relation": "related_to", "confidence": 0.9})
    if "Nina" in body and "praça" in body:
        relations.append({"source": ref("Nina"), "target": ref("praça"),
                          "relation": "related_to", "confidence": 0.9})
    if "jardim" in body and "praça" in body:
        relations.append({"source": ref("jardim"), "target": ref("praça"),
                          "relation": "related_to", "confidence": 0.9})
    return json.dumps({"entities": entities, "relations": relations,
                       "events": []})


def _machine(tmp_path, **cfg):
    config = Config(capacity=200, graph_enabled=True,
                    graph_conversation_enabled=True,
                    graph_recall_mode="augment", graph_depth=3, **cfg)
    return Machine(tmp_path, config=config, client=FakeClient(_extract))


def _ids(result):
    return {item.memory_id for item in result.evidence}


def test_dead_evidence_cannot_bridge_to_active_memories(tmp_path):
    machine = _machine(tmp_path)
    a = machine.add_turn_slot("question", "Lia cuida do jardim",
                              message_id="a")["record"]["id"]
    b = machine.add_turn_slot("question", "Nina desenhou a praça",
                              message_id="b")["record"]["id"]
    bridge = machine.add_turn_slot("question", "O jardim cerca a praça",
                                   message_id="c")["record"]["id"]

    before = _ids(machine._graph_recall("Lia"))
    assert {a, b} <= before  # the bridge connects the two active memories

    machine.tape.set_status(bridge, "superseded")

    after = _ids(machine._graph_recall("Lia"))
    assert a in after
    assert b not in after  # only the dead bridge used to reach it

    machine.tape.delete(bridge)
    again = _ids(machine._graph_recall("Lia"))
    assert a in again and b not in again


def test_pruning_is_read_only_and_idempotent(tmp_path):
    machine = _machine(tmp_path)
    machine.add_turn_slot("question", "Lia cuida do jardim", message_id="a")
    machine.add_turn_slot("question", "O jardim cerca a praça",
                          message_id="c")
    store_dir = tmp_path / "graph"
    before = {path.name: path.read_bytes()
              for path in store_dir.glob("*") if path.is_file()}

    machine.tape.set_status(
        next(record.id for record in machine.tape.read()
             if record.type == "question" and "cerca" in record.why),
        "superseded")
    machine._graph_recall("Lia")
    machine._graph_recall("Lia")
    after = {path.name: path.read_bytes()
             for path in store_dir.glob("*") if path.is_file()}
    assert after == before  # append-only store untouched


def test_dimension_mode_receives_graph_annotations(tmp_path):
    machine = _machine(tmp_path, whiteboard_mode="dimension")
    machine.add_turn_slot("question", "Lia cuida do jardim", message_id="a")
    linked = machine.add_turn_slot("question", "O jardim cerca a praça",
                                   message_id="c")["record"]["id"]

    result = machine.recall("Lia")
    annotated = {item["memory_id"] for item in result["annotations"]}
    assert linked in annotated
    assert any(item.agent_id == "graph"
               for item in machine.whiteboard.annotations
               if item.memory_id == linked)


def test_prune_to_active_unit(tmp_path):
    machine = _machine(tmp_path)
    machine.add_turn_slot("question", "Lia cuida do jardim", message_id="a")
    bridge = machine.add_turn_slot("question", "O jardim cerca a praça",
                                   message_id="c")["record"]["id"]
    store = GraphStore(tmp_path / "graph")
    index = store.index()
    removed = index.prune_to_active({bridge})  # only the bridge is active
    assert removed["entities"] >= 1 and removed["relations"] >= 1
    assert index.resolve("jardim")
    assert not any(entity.name == "Lia" for entity in index.entities.values())
    assert index.prune_to_active({bridge}) == {"entities": 0, "relations": 0}
