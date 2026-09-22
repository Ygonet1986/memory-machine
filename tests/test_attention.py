from memory_machine.attention import (
    blend,
    classify,
    confidence,
    decay_reinforce,
    is_anaphoric,
)
from memory_machine.config import Config
from memory_machine.coordinator import Machine
from memory_machine.tape import MemoryRecord
from memory_machine.whiteboard import Whiteboard

from fakes import FakeClient


def _machine(tmp_path, handler, **cfg):
    return Machine(tmp_path, config=Config(capacity=10, **cfg), client=FakeClient(handler))


def _agent_handler(annotations="[]"):
    def handler(messages, temperature):
        return (
            '{"digest":"d","checklist":[],"annotations":' + annotations + ','
            '"coverage":"complete"}'
        )

    return handler


# ------------------------------------------------------------------ attention


def test_decay_reinforce_saturates_and_clamps():
    out = decay_reinforce(
        {"a": 0.9, "b": 0.2},
        ["a"],
        ["b"],
        decay=0.6,
        boost=0.8,
        found_boost=0.3,
    )
    assert abs(out["a"] - (0.54 + 0.8 * 0.46)) < 1e-9  # saturated boost
    assert abs(out["b"] - (0.12 + 0.3 * 0.88)) < 1e-9
    assert out["a"] <= 1.0 and out["b"] <= 1.0
    assert decay_reinforce({"a": 1.0}, ["a"], decay=0.5, boost=1.0)["a"] == 1.0


def test_blend_and_classify():
    final = blend({"topic/router": 3.0, "topic/views": 1.5}, {"topic/router": 0.8}, 0.5)
    assert final["topic/router"] > final["topic/views"]
    assert classify(1.0, 0.4) == "both"
    assert classify(1.0, 0.0) == "router"
    assert classify(0.0, 0.4) == "attention"
    assert classify(0.0, 0.0) == "none"


def test_attention_confidence():
    assert confidence({"a": 0.9, "b": 0.4}) == (0.9, 0.5)
    assert confidence({}) == (0.0, 0.0)


def test_is_anaphoric():
    assert is_anaphoric("e por que mudamos isso?", view_names=("topic/router",))
    assert is_anaphoric("why did we do that?", view_names=("topic/router",))
    assert not is_anaphoric("what changed about the router?", view_names=("topic/router",))
    assert not is_anaphoric("", view_names=())


def test_whiteboard_attention_roundtrip():
    wb = Whiteboard(subject="s")
    wb.attention = {"topic/router": 0.91, "time/2026-09": 0.37}
    restored = Whiteboard.from_dict(wb.to_dict())
    assert restored.attention == {"topic/router": 0.91, "time/2026-09": 0.37}


# ------------------------------------------------------------------ recall


def test_recall_attention_prior_keeps_active_view(tmp_path):
    m = _machine(
        tmp_path,
        _agent_handler(),
        router_enabled=True,
        router_mode="views",
        view_router_mode="lexical",
        view_dimension_mode="auto",
        attention_mode="prior",
        view_top_k=1,
    )
    m.add_memory(MemoryRecord(type="decision", summary="router opt-in", views=["topic/router"]))
    m.add_memory(
        MemoryRecord(type="lesson", summary="bossa nova guitar", views=["topic/music"])
    )

    first = m.recall("what about the router?")
    assert "topic/router" in first["routing"]["selected_views"]
    assert m.whiteboard.attention.get("topic/router", 0) > 0

    second = m.recall("e por que mudamos isso?")
    routing = second["routing"]
    assert "topic/router" in routing["selected_views"]
    scores = routing["view_scores"]["topic/router"]
    assert scores["contribution"] in {"attention", "both"}
    assert second["attention_contribution"]["attention"] >= 1


def test_recall_attention_off_keeps_no_state(tmp_path):
    m = _machine(
        tmp_path,
        _agent_handler(),
        router_enabled=True,
        router_mode="views",
        view_router_mode="lexical",
        view_dimension_mode="auto",
    )
    m.add_memory(MemoryRecord(type="decision", summary="router opt-in", views=["topic/router"]))
    res = m.recall("what about the router?")
    assert res["attention"] == {}
    assert res["attention_contribution"]["router"] >= 1
    assert res["attention_contribution"]["attention"] == 0


def test_recall_attention_found_boost(tmp_path):
    annotation = '[{"memory_id":"M0001","note":"router","relevance":0.9}]'
    m = _machine(
        tmp_path,
        _agent_handler(annotation),
        router_enabled=True,
        router_mode="views",
        view_router_mode="lexical",
        view_dimension_mode="auto",
        agent_mode="view",
        attention_mode="prior",
        view_top_k=1,
    )
    m.add_memory(MemoryRecord(type="decision", summary="router opt-in", views=["topic/router"]))
    res = m.recall("what about the router?")
    attention = res["attention"]["topic/router"]
    # selected boost (0.8) + found boost (0.3) from a cold start
    assert attention > 0.8


def test_attention_state_gate_reuses_on_anaphora(tmp_path):
    m = _machine(
        tmp_path,
        _agent_handler(),
        router_enabled=True,
        router_mode="views",
        view_router_mode="lexical",
        view_dimension_mode="auto",
        attention_mode="state",
        view_top_k=1,
    )
    m.add_memory(MemoryRecord(type="decision", summary="router opt-in", views=["topic/router"]))
    m.add_memory(MemoryRecord(type="lesson", summary="bossa nova guitar", views=["topic/music"]))
    m.recall("what about the router?")
    gated = m.recall("e por que mudamos isso?")
    routing = gated["routing"]
    assert routing["attention_gate"] == "reused"
    assert routing["anaphoric"] is True
    assert "topic/router" in routing["selected_views"]

    routed = m.recall("what are the rules for views and expansion?")
    assert routed["routing"]["attention_gate"] == "routed"


def test_attention_state_gate_requires_concentration(tmp_path):
    m = _machine(
        tmp_path,
        _agent_handler(),
        router_enabled=True,
        router_mode="views",
        view_router_mode="lexical",
        view_dimension_mode="auto",
        attention_mode="state",
        attention_gate_min=0.99,
        view_top_k=1,
    )
    m.add_memory(MemoryRecord(type="decision", summary="router opt-in", views=["topic/router"]))
    m.recall("what about the router?")
    res = m.recall("e por que mudamos isso?")
    assert res["routing"]["attention_gate"] == "routed"


def test_attention_prior_yields_on_topic_shift(tmp_path):
    m = _machine(
        tmp_path,
        _agent_handler(),
        router_enabled=True,
        router_mode="views",
        view_router_mode="lexical",
        view_dimension_mode="auto",
        attention_mode="prior",
        view_top_k=2,
    )
    m.add_memory(MemoryRecord(type="decision", summary="router opt-in", views=["topic/router"]))
    m.add_memory(
        MemoryRecord(type="preference", summary="sourdough cold ferment",
                     views=["topic/bread"])
    )
    m.recall("what about the router?")
    assert m.whiteboard.attention.get("topic/router", 0) > 0

    shifted = m.recall("what do we know about sourdough and hydration?")
    assert "topic/bread" in shifted["routing"]["selected_views"]
    assert shifted["routing"]["view_scores"]["topic/bread"]["contribution"] in {"router", "both"}
