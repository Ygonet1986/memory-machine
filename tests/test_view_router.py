from memory_machine.coordinator import Machine
from memory_machine.config import Config
from memory_machine.tape import MemoryRecord, Tape
from memory_machine.views import related_views, select_views_llm

from fakes import FakeClient, text


def _machine(tmp_path, handler, **cfg):
    return Machine(tmp_path, config=Config(capacity=10, **cfg), client=FakeClient(handler))


def _empty(messages, temperature):
    return '{"digest":"d","checklist":[],"annotations":[]}'


# ---------------------------------------------------------------- related_views


def test_related_views_cooccurrence(tmp_path):
    tape = Tape(tmp_path / "tape.jsonl")
    tape.append(
        MemoryRecord(type="decision", summary="use embedding router", views=["topic/router", "subject/mm"])
    )
    tape.append(
        MemoryRecord(type="lesson", summary="embedding router lost recall", views=["topic/benchmarks", "subject/mm"])
    )
    related = related_views(tape, ["topic/router"])
    assert "subject/mm" in related
    assert "topic/benchmarks" not in related  # not on the same record


def test_related_views_excludes_structural_and_selected(tmp_path):
    tape = Tape(tmp_path / "tape.jsonl")
    tape.append(MemoryRecord(type="decision", summary="x", views=["topic/a"]))
    assert related_views(tape, ["topic/a"]) == []


# ------------------------------------------------------------- select_views_llm


def test_select_views_llm_parses_and_filters(tmp_path):
    tape = Tape(tmp_path / "tape.jsonl")
    tape.append(MemoryRecord(type="decision", summary="Use Postgres", views=["topic/db"]))
    tape.append(MemoryRecord(type="preference", summary="Bossa nova", views=["topic/music"]))
    client = FakeClient(lambda m, t: '{"views":["topic/db","bogus"],"confidence":0.8}')
    result = select_views_llm(tape, "which database?", client)
    assert result == (["topic/db"], 0.8)


def test_select_views_llm_empty_returns_none(tmp_path):
    tape = Tape(tmp_path / "tape.jsonl")
    tape.append(MemoryRecord(type="decision", summary="x", views=["topic/a"]))
    client = FakeClient(lambda m, t: '{"views":[],"confidence":0.9}')
    assert select_views_llm(tape, "x", client) is None


def test_select_views_llm_no_client(tmp_path):
    tape = Tape(tmp_path / "tape.jsonl")
    tape.append(MemoryRecord(type="decision", summary="x", views=["topic/a"]))
    assert select_views_llm(tape, "x", None) is None


# ---------------------------------------------------------------- recall modes


def test_recall_views_mode_lexical(tmp_path):
    seen: dict[str, str] = {}

    def handler(messages, temperature):
        seen["sys"] = text(messages, "system")
        return '{"digest":"d","checklist":[],"annotations":[{"memory_id":"M0001","note":"n","relevance":0.9}]}'

    m = _machine(
        tmp_path,
        handler,
        router_enabled=True,
        router_mode="views",
        view_router_mode="lexical",
        view_top_k=2,
    )
    m.add_memory(MemoryRecord(type="decision", summary="Use PostgreSQL database", views=["topic/db"]))
    m.add_memory(MemoryRecord(type="preference", summary="Compose bossa nova guitar", views=["topic/music"]))

    res = m.recall("which database should we use")
    assert res["routing"]["mode"] == "views"
    assert res["routing"]["level"] == 1
    assert "topic/db" in res["routing"]["selected_views"]
    assert "M0001" in seen["sys"]
    assert "M0002" not in seen["sys"]
    assert res["routing"]["records_consulted"] == 1
    assert res["routing"]["records_total"] == 2


def test_recall_views_mode_llm(tmp_path):
    seen: dict[str, str] = {}
    calls = {"router": 0}

    def handler(messages, temperature):
        sys_text = text(messages, "system")
        if "regions (views)" in sys_text:
            calls["router"] += 1
            return '{"views":["topic/music"],"confidence":0.9}'
        seen["sys"] = sys_text
        return '{"digest":"d","checklist":[],"annotations":[]}'

    m = _machine(
        tmp_path,
        handler,
        router_enabled=True,
        router_mode="views",
        view_router_mode="llm",
    )
    m.add_memory(MemoryRecord(type="decision", summary="Use PostgreSQL database", views=["topic/db"]))
    m.add_memory(MemoryRecord(type="preference", summary="Compose bossa nova guitar", views=["topic/music"]))

    res = m.recall("what should I play?")
    assert calls["router"] == 1
    assert res["routing"]["selected_views"] == ["topic/music"]
    assert res["routing"]["view_score"] == 0.9
    assert "bossa" in seen["sys"]
    assert "PostgreSQL" not in seen["sys"]


def test_recall_views_override(tmp_path):
    seen: dict[str, str] = {}

    def handler(messages, temperature):
        seen["sys"] = text(messages, "system")
        return _empty(messages, temperature)

    m = _machine(tmp_path, handler, router_enabled=True, router_mode="cascade")
    m.add_memory(MemoryRecord(type="decision", summary="Use PostgreSQL database", views=["topic/db"]))
    m.add_memory(MemoryRecord(type="preference", summary="Compose bossa nova guitar", views=["topic/music"]))

    res = m.recall("anything", views=["topic/music"])
    assert res["routing"]["mode"] == "override"
    assert res["routing"]["selected_views"] == ["topic/music"]
    assert "bossa" in seen["sys"]
    assert "PostgreSQL" not in seen["sys"]


def test_routing_metadata_full(tmp_path):
    m = _machine(tmp_path, _empty)
    m.add_memory(MemoryRecord(type="decision", summary="x"))
    res = m.recall("q")
    assert res["routing"]["mode"] == "full"
    assert res["routing"]["level"] == 0
    assert res["routing"]["records_consulted"] == 1
    assert res["routed_groups"] == 1


# -------------------------------------------------------------------- cascade


def test_cascade_accepts_level1(tmp_path):
    def handler(messages, temperature):
        return '{"digest":"d","checklist":[],"annotations":[{"memory_id":"M0001","note":"n","relevance":0.9}]}'

    m = _machine(
        tmp_path,
        handler,
        router_enabled=True,
        router_mode="cascade",
        view_router_mode="lexical",
    )
    m.add_memory(MemoryRecord(type="decision", summary="Use PostgreSQL database", views=["topic/db"]))
    res = m.recall("which database should we use")
    assert res["routing"]["level"] == 1
    assert res["routing"]["fallback_reasons"] == []
    assert res["annotations"][0]["memory_id"] == "M0001"


def test_cascade_falls_back_to_similarity(tmp_path):
    calls = {"agents": 0}

    def handler(messages, temperature):
        sys_text = text(messages, "system")
        if "memory partitions" in sys_text:
            return '{"groups":["G1"]}'
        calls["agents"] += 1
        if calls["agents"] >= 2:
            return '{"digest":"d","checklist":[],"annotations":[{"memory_id":"M0001","note":"n","relevance":0.9}]}'
        return _empty(messages, temperature)

    m = _machine(
        tmp_path,
        handler,
        router_enabled=True,
        router_mode="cascade",
        view_router_mode="lexical",
    )
    m.add_memory(MemoryRecord(type="decision", summary="Use PostgreSQL database", views=["topic/db"]))
    res = m.recall("which database should we use")
    assert res["routing"]["level"] == 3
    assert "no_annotation" in res["routing"]["fallback_reasons"]
    assert "expansion_failed" in res["routing"]["fallback_reasons"]
    assert res["annotations"][0]["memory_id"] == "M0001"


def test_cascade_full_fallback(tmp_path):
    calls = {"agents": 0}

    def handler(messages, temperature):
        sys_text = text(messages, "system")
        if "memory partitions" in sys_text:
            return '{"groups":[]}'
        calls["agents"] += 1
        if calls["agents"] >= 3:
            return '{"digest":"d","checklist":[],"annotations":[{"memory_id":"M0001","note":"n","relevance":0.9}]}'
        return _empty(messages, temperature)

    m = _machine(
        tmp_path,
        handler,
        router_enabled=True,
        router_mode="cascade",
        view_router_mode="lexical",
    )
    m.add_memory(MemoryRecord(type="decision", summary="Use PostgreSQL database", views=["topic/db"]))
    res = m.recall("which database should we use")
    assert res["routing"]["level"] == 4
    assert "similarity_failed" in res["routing"]["fallback_reasons"]
    assert res["annotations"][0]["memory_id"] == "M0001"


def test_cascade_low_score_expands(tmp_path):
    calls = {"agents": 0}

    def handler(messages, temperature):
        calls["agents"] += 1
        if calls["agents"] >= 2:
            return '{"digest":"d","checklist":[],"annotations":[{"memory_id":"M0002","note":"n","relevance":0.9}]}'
        return '{"digest":"d","checklist":[],"annotations":[{"memory_id":"M0001","note":"n","relevance":0.9}]}'

    m = _machine(
        tmp_path,
        handler,
        router_enabled=True,
        router_mode="cascade",
        view_router_mode="lexical",
        view_top_k=1,
        cascade_min_score=999.0,
    )
    m.add_memory(MemoryRecord(type="decision", summary="Use PostgreSQL database", views=["topic/db"]))
    m.add_memory(MemoryRecord(type="lesson", summary="Pool database connections", views=["topic/db", "subject/infra"]))
    res = m.recall("which database should we use")
    assert "low_view_score" in res["routing"]["fallback_reasons"]
    assert res["routing"]["level"] == 2
    assert {a["memory_id"] for a in res["annotations"]} == {"M0001", "M0002"}
