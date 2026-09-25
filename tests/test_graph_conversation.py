import json

from memory_machine.config import Config
from memory_machine.coordinator import Machine
from memory_machine.graph import GraphStore

from fakes import FakeClient


def test_turns_feed_persistent_associative_graph_and_recall(tmp_path):
    def extract(messages, temperature):
        assert "memory graph agent" in messages[0]["content"]
        body = messages[1]["content"]
        subject = "Lia" if "Lia" in body else "Nina"
        return json.dumps({
            "entities": [
                {"ref": "e1", "name": subject, "type": "person"},
                {"ref": "e2", "name": "jardim", "type": "place"},
            ],
            "events": [],
            "relations": [{"source": "e1", "target": "e2",
                           "relation": "related_to", "confidence": 0.92}],
        })

    config = Config(graph_enabled=True, graph_conversation_enabled=True,
                    graph_recall_mode="only", graph_depth=2)
    machine = Machine(tmp_path, config=config, client=FakeClient(extract))
    first = machine.add_turn_slot("question", "Lia cuida do jardim", message_id="a")
    second = machine.add_turn_slot("question", "Nina desenhou o jardim", message_id="b")
    assert first["ok"] and second["ok"]
    store = GraphStore(tmp_path / "graph")
    assert len(store.entities()) == 3
    assert len(store.relations()) == 2
    assert store.extracted_ids("llm/v1") == {
        first["record"]["id"], second["record"]["id"],
    }
    paths = machine._graph_recall("Lia")
    assert second["record"]["id"] in {e.memory_id for e in paths.evidence}
    assert machine.add_turn_slot("question", "Lia cuida do jardim", message_id="a")["deduped"]
    assert len(store.relations()) == 2
    reopened = GraphStore(tmp_path / "graph")
    assert len(reopened.relations()) == 2


def test_conversation_graph_can_be_disabled_explicitly(tmp_path):
    client = FakeClient(lambda messages, temperature: "should not be called")
    machine = Machine(tmp_path, config=Config(graph_enabled=True,
                    graph_conversation_enabled=False), client=client)
    machine.add_turn_slot("question", "Lia cuida do jardim", message_id="a")
    assert not GraphStore(tmp_path / "graph").exists()
    assert client.calls == []


def test_default_graph_agent_puts_linked_memory_on_whiteboard(tmp_path):
    def handler(messages, temperature):
        if "memory graph agent" in messages[0]["content"]:
            subject = "Lia" if "Lia" in messages[1]["content"] else "Nina"
            return json.dumps({
                "entities": [
                    {"ref": "e1", "name": subject, "type": "person"},
                    {"ref": "e2", "name": "jardim", "type": "place"},
                ],
                "relations": [{"source": "e1", "target": "e2",
                               "relation": "related_to", "confidence": 0.9}],
                "events": [],
            })
        return '{"digest":"","annotations":[],"coverage":"complete"}'

    machine = Machine(tmp_path, config=Config(), client=FakeClient(handler))
    machine.add_turn_slot("question", "Lia cuida do jardim", message_id="a")
    nina = machine.add_turn_slot("question", "Nina desenhou o jardim", message_id="b")
    result = machine.recall("Lia")
    linked_id = nina["record"]["id"]
    assert linked_id in {item["memory_id"] for item in result["graph_evidence"]}
    assert linked_id in {item["memory_id"] for item in result["annotations"]}
    assert linked_id in {item.memory_id for item in machine.whiteboard.annotations}
    assert any(item.memory_id == linked_id and item.agent_id == "graph"
               for item in machine.whiteboard.annotations)
