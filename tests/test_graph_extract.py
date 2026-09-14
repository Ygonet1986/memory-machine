import pytest

from memory_machine.graph import (
    Extraction,
    ExtractionError,
    TransientExtractionError,
)
from memory_machine.graph_extract import (
    GraphExtractor,
    canonical_relation,
    parse_extraction,
)
from memory_machine.tape import MemoryRecord

from fakes import FakeClient


def _record(summary="Kalak crossed the rock", why="at dusk"):
    return MemoryRecord(type="decision", summary=summary, why=why, id="M0001")


def _client(payload):
    return FakeClient(lambda messages, temperature: payload)


def test_simple_entity():
    extractor = GraphExtractor(
        _client('{"entities":[{"ref":"e1","name":"Kalak","type":"person","confidence":0.99}]}')
    )
    result = extractor.extract(_record())

    assert isinstance(result, Extraction)
    assert result.entities[0].ref == "e1"
    assert result.entities[0].name == "Kalak"
    assert result.entities[0].confidence == 0.99
    assert result.memory_id == "M0001"
    assert result.extractor == "llm" and result.extractor_version == "v1"
    assert extractor.tag == "llm/v1"


def test_two_entities_and_relation():
    payload = (
        '{"entities":[{"ref":"e1","name":"Kalak"},'
        '{"ref":"e2","name":"rochedo","type":"object"}],'
        '"relations":[{"source":"e1","relation":"contornou","target":"e2","confidence":0.9}]}'
    )
    result = GraphExtractor(_client(payload)).extract(_record())

    assert [e.name for e in result.entities] == ["Kalak", "rochedo"]
    assert result.relations[0].source == "e1"
    assert result.relations[0].target == "e2"
    assert result.relations[0].relation == "cross"  # canonicalized
    assert result.relations[0].confidence == 0.9


def test_event_agent_action_object():
    payload = (
        '{"entities":[{"ref":"e1","name":"Kalak"},{"ref":"e2","name":"rochedo"}],'
        '"events":[{"ref":"ev1","action":"circumvent","agent":"e1","object":"e2","confidence":0.97}]}'
    )
    result = GraphExtractor(_client(payload)).extract(_record())

    event = result.events[0]
    assert event.ref == "ev1"
    assert (event.action, event.agent, event.object) == ("circumvent", "e1", "e2")
    assert event.confidence == 0.97


def test_aliases_and_mentions():
    payload = (
        '{"entities":[{"ref":"e1","name":"Kalak","aliases":["the king"]}],'
        '"mentions":["e1"]}'
    )
    result = GraphExtractor(_client(payload)).extract(_record())

    assert result.entities[0].aliases == ("the king",)
    assert result.mentions == ("e1",)


def test_canonical_relation_normalization():
    assert canonical_relation("Contornou") == "cross"
    assert canonical_relation("occur in") == "occur_in"
    assert canonical_relation("custom verb") == "custom_verb"
    assert canonical_relation("") == ""


def test_invalid_output_raises_extraction_error():
    with pytest.raises(ExtractionError):
        GraphExtractor(_client("not json at all")).extract(_record())
    with pytest.raises(ExtractionError):
        parse_extraction({"answer": "no lists"}, memory_id="M0001")


def test_api_error_and_empty_completion_are_transient():
    def boom(messages, temperature):
        raise RuntimeError("api timeout")

    with pytest.raises(TransientExtractionError):
        GraphExtractor(FakeClient(boom)).extract(_record())
    with pytest.raises(TransientExtractionError):
        GraphExtractor(_client("   ")).extract(_record())


def test_empty_extraction_is_valid():
    result = GraphExtractor(
        _client('{"entities":[],"events":[],"relations":[]}')
    ).extract(_record())

    assert result.entities == () and result.events == () and result.relations == ()


def test_bounds_truncate_oversized_payloads():
    entities = ",".join(f'{{"ref":"e{i}","name":"n{i}"}}' for i in range(1, 26))
    payload = '{"entities":[' + entities + "]}"
    result = GraphExtractor(_client(payload)).extract(_record())

    assert len(result.entities) == 20
