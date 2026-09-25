"""Rescue adopted as the conversation default: links recovered, noise blocked."""

from __future__ import annotations

import json

from fakes import FakeClient
from memory_machine.config import Config
from memory_machine.coordinator import Machine
from memory_machine.graph import GraphStore
from memory_machine.tape import MemoryRecord, Tape


def test_default_mode_and_constants():
    config = Config()
    assert config.graph_enabled is True
    assert config.graph_conversation_enabled is True
    assert config.graph_recall_mode == "augment_conversation"
    assert config.graph_conversation_min_score == 0.60
    assert config.graph_conversation_max_items == 2


def test_default_recovers_association_that_guarded_cuts(tmp_path):
    def extract(messages, temperature):
        body = messages[1]["content"]
        entities, relations, refs = [], [], {}

        def ref(name):
            if name not in refs:
                refs[name] = f"e{len(refs) + 1}"
                entities.append({"ref": refs[name], "name": name,
                                 "type": "concept"})
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

    machine = Machine(tmp_path, config=Config(capacity=200, graph_depth=3),
                      client=FakeClient(extract))
    machine.add_turn_slot("question", "Lia cuida do jardim", message_id="a")
    linked = machine.add_turn_slot("question", "Nina desenhou a praça",
                                   message_id="b")["record"]["id"]
    machine.add_turn_slot("question", "O jardim cerca a praça", message_id="c")

    result = machine.recall("Lia")
    assert linked in {row["memory_id"] for row in result["annotations"]}


def test_default_blocks_hub_noise(tmp_path):
    machine = Machine(tmp_path, config=Config(capacity=50,
                                              graph_augment_hub_degree=2),
                      client=FakeClient(
                          lambda messages, temperature: '{"annotations":[]}'))
    tape = Tape(tmp_path / "tape.jsonl")
    tape.append(MemoryRecord(type="decision", summary="Kalak crossed", why=""))
    tape.append(MemoryRecord(type="lesson", summary="Kalak knows the user",
                             why=""))
    tape.append(MemoryRecord(type="lesson", summary="the user likes petronante",
                             why=""))
    store = GraphStore(tmp_path / "graph")
    store.add_entity("Kalak", "person", "M0001", entity_id="E0001")
    store.add_entity("rochedo", "place", "M0001", entity_id="E0002")
    store.add_entity("petronante", "creature", "M0002", entity_id="E0003")
    store.add_entity("user", "person", "M0002", entity_id="E0004")
    store.add_relation("E0001", "cross", "E0002", "M0001", 0.9)
    store.add_relation("E0001", "knows", "E0004", "M0002", 0.8)
    store.add_relation("E0004", "found", "E0003", "M0002", 0.8)
    store.add_relation("E0004", "likes", "E0003", "M0003", 0.7)
    for entity_id, memory_id in (("E0001", "M0001"), ("E0002", "M0001"),
                                 ("E0003", "M0002"), ("E0004", "M0002")):
        store.add_mention(memory_id, entity_id)

    result = machine.recall("Kalak")
    assert "M0003" not in {row["memory_id"] for row in result["graph_evidence"]}
