from memory_machine.agents import run_agents
from memory_machine.config import Config
from memory_machine.coordinator import Machine
from memory_machine.groups import Manifest, ensure_group
from memory_machine.routing import (
    RoutingPlan,
    detect_dimensions,
    dimension_of,
    ids_for_plan,
    parse_time_views,
    select_plan_lexical,
)
from memory_machine.tape import MemoryRecord, Tape
from memory_machine.whiteboard import Whiteboard

from fakes import FakeClient, text


def _machine(tmp_path, handler, **cfg):
    return Machine(tmp_path, config=Config(capacity=10, **cfg), client=FakeClient(handler))


# ------------------------------------------------------------------ dimensions


def test_dimension_of():
    assert dimension_of("topic/router") == "semantic"
    assert dimension_of("subject/memory-machine") == "semantic"
    assert dimension_of("time/2026-09") == "temporal"
    assert dimension_of("type/decision") == "structural"
    assert dimension_of("source/spec.txt") == "structural"
    assert dimension_of("misc") is None


def test_detect_dimensions_default_semantic():
    assert detect_dimensions("what is the router strategy?") == {
        "semantic": "default_semantic"
    }


def test_detect_dimensions_temporal_parser():
    dims = detect_dimensions("what changed since August?", available_time=["time/2026-08"])
    assert dims["temporal"] == "temporal_parser"
    assert dims["semantic"] == "default_semantic"


def test_detect_dimensions_type_marker():
    dims = detect_dimensions("list the decisions about caching")
    assert dims["structural"] == "type_marker"


def test_detect_dimensions_source_marker():
    dims = detect_dimensions("what does the attached spec say?")
    assert dims["structural"] == "source_marker"


def test_parse_time_views_since_range():
    available = ["time/2026-05", "time/2026-07", "time/2026-08", "time/2026-09"]
    assert parse_time_views("what changed since July?", available) == [
        "time/2026-07",
        "time/2026-08",
        "time/2026-09",
    ]


def test_parse_time_views_before():
    available = ["time/2026-05", "time/2026-07", "time/2026-09"]
    assert parse_time_views("what did we do before July?", available) == [
        "time/2026-05"
    ]


def test_parse_time_views_recent():
    available = ["time/2026-02", "time/2026-08", "time/2026-09"]
    assert parse_time_views("what changed recently?", available) == [
        "time/2026-08",
        "time/2026-09",
    ]


# ------------------------------------------------------- plans and relaxation


def _tape_with(records, tmp_path):
    tape = Tape(tmp_path / "tape.jsonl")
    for spec in records:
        tape.append(MemoryRecord(**spec))
    return tape


def test_select_plan_lexical_intersection(tmp_path):
    tape = _tape_with(
        [
            {"type": "decision", "summary": "router opt-in", "created_at": "2026-07-10",
             "views": ["topic/router"]},
            {"type": "lesson", "summary": "benchmarks favor agents", "created_at": "2026-09-01",
             "views": ["topic/benchmarks"]},
        ],
        tmp_path,
    )
    plan = select_plan_lexical(tape, "what changed about the router since July?")
    assert "semantic" in plan.views_by_dimension
    assert "temporal" in plan.views_by_dimension
    assert plan.combination == "intersection"
    ids, mode = ids_for_plan(tape, plan)
    assert mode == "strict"
    assert ids == {"M0001"}


def test_ids_for_plan_relaxed_semantic(tmp_path):
    tape = _tape_with(
        [
            {"type": "decision", "summary": "router opt-in", "created_at": "2026-05-10",
             "views": ["topic/router"]},
            {"type": "lesson", "summary": "router lost recall", "created_at": "2026-09-01",
             "views": ["subject/memory-machine"]},
        ],
        tmp_path,
    )
    plan = RoutingPlan(
        views_by_dimension={
            "semantic": ["topic/router", "subject/memory-machine"],
            "temporal": ["time/2026-09"],
        },
        dimensions=["semantic", "temporal"],
    )
    ids, mode = ids_for_plan(tape, plan)
    assert mode == "relaxed_semantic"
    assert ids == {"M0002"}


def test_ids_for_plan_relaxed_temporal(tmp_path):
    tape = _tape_with(
        [
            {"type": "decision", "summary": "router opt-in", "created_at": "2026-05-10",
             "views": ["topic/router"]},
            {"type": "lesson", "summary": "other december note", "created_at": "2026-12-01",
             "views": ["topic/other"]},
        ],
        tmp_path,
    )
    plan = RoutingPlan(
        views_by_dimension={
            "semantic": ["topic/router"],
            "temporal": ["time/2026-12"],
            "structural": ["type/decision"],
        },
        dimensions=["semantic", "temporal", "structural"],
    )
    ids, mode = ids_for_plan(tape, plan)
    assert mode == "relaxed_temporal"
    assert ids == {"M0001"}


def test_ids_for_plan_union_fallback(tmp_path):
    tape = _tape_with(
        [
            {"type": "decision", "summary": "router opt-in", "created_at": "2026-05-10",
             "views": ["topic/router"]},
            {"type": "lesson", "summary": "benchmarks favor agents", "created_at": "2026-09-01",
             "views": ["topic/benchmarks"]},
        ],
        tmp_path,
    )
    plan = RoutingPlan(
        views_by_dimension={
            "semantic": ["topic/router"],
            "temporal": ["time/2026-09"],
            "structural": ["type/lesson"],
        },
        dimensions=["semantic", "temporal", "structural"],
    )
    ids, mode = ids_for_plan(tape, plan)
    assert mode == "union_fallback"
    assert ids == {"M0001", "M0002"}


# ------------------------------------------------------------------ ids_filter


def test_run_agents_ids_filter(tmp_path):
    tape = Tape(tmp_path / "tape.jsonl")
    manifest = Manifest(capacity=10)
    tape.append(MemoryRecord(id="M0001", type="decision", summary="Use Postgres"))
    tape.append(MemoryRecord(id="M0002", type="preference", summary="Bossa nova"))
    manifest, _g, _a1, _ = ensure_group(manifest, 1)
    seen: dict[str, str] = {}

    def handler(messages, temperature):
        seen["sys"] = text(messages, "system")
        return '{"digest":"d","checklist":[],"annotations":[],"coverage":"complete"}'

    run_agents(
        tape, manifest, Whiteboard(subject="x"), FakeClient(handler), ids_filter={"M0002"}
    )
    assert "Bossa nova" in seen["sys"]
    assert "Use Postgres" not in seen["sys"]


# ------------------------------------------------------------- coverage signal


def test_run_agents_parses_coverage(tmp_path):
    tape = Tape(tmp_path / "tape.jsonl")
    manifest = Manifest(capacity=10)
    tape.append(MemoryRecord(id="M0001", type="decision", summary="Use Postgres"))
    manifest, _g, _a1, _ = ensure_group(manifest, 1)

    def handler(messages, temperature):
        return (
            '{"digest":"d","checklist":[],"annotations":[],'
            '"coverage":"partial","missing":["the later decision"]}'
        )

    run = run_agents(tape, manifest, Whiteboard(subject="x"), FakeClient(handler))
    assert run.coverage[0].coverage == "partial"
    assert run.coverage[0].missing == ["the later decision"]
    # coverage is recall-local telemetry: never persisted on the agent
    assert not hasattr(manifest.agents[0], "coverage")


def test_recall_dimension_mode_intersection(tmp_path):
    seen: dict[str, str] = {}

    def handler(messages, temperature):
        seen["sys"] = text(messages, "system")
        return '{"digest":"d","checklist":[],"annotations":[],"coverage":"complete"}'

    m = _machine(
        tmp_path,
        handler,
        router_enabled=True,
        router_mode="views",
        view_router_mode="lexical",
        view_dimension_mode="auto",
    )
    m.add_memory(
        MemoryRecord(type="decision", summary="router opt-in", created_at="2026-07-10",
                     views=["topic/router"])
    )
    m.add_memory(
        MemoryRecord(type="lesson", summary="benchmarks favor agents", created_at="2026-09-01",
                     views=["topic/benchmarks"])
    )
    res = m.recall("what changed about the router since July?")
    routing = res["routing"]
    assert routing["dimensions"] == ["semantic", "temporal"]
    assert routing["combination"] == "intersection"
    assert routing["intersection_mode"] == "strict"
    assert routing["intersection_size"] == 1
    assert "M0001" in seen["sys"]
    assert "M0002" not in seen["sys"]


def test_recall_coverage_cascade_fallback(tmp_path):
    calls = {"agents": 0}

    def handler(messages, temperature):
        sys_text = text(messages, "system")
        if "You plan how to access" in sys_text:
            return '{"dimensions":["semantic"],"views":["topic/router"],"confidence":0.9}'
        if "memory partitions" in sys_text:
            return '{"groups":["G1"]}'
        calls["agents"] += 1
        if calls["agents"] == 1:
            return (
                '{"digest":"d","checklist":[],"annotations":[],'
                '"coverage":"partial","missing":["the benchmark decision"]}'
            )
        return (
            '{"digest":"d","checklist":[],"annotations":'
            '[{"memory_id":"M0002","note":"n","relevance":0.9}],"coverage":"complete"}'
        )

    m = _machine(
        tmp_path,
        handler,
        router_enabled=True,
        router_mode="cascade",
        view_router_mode="llm",
        view_dimension_mode="auto",
        coverage_mode="agents",
    )
    m.add_memory(
        MemoryRecord(type="decision", summary="router opt-in",
                     views=["topic/router", "subject/memory-machine"])
    )
    m.add_memory(
        MemoryRecord(type="lesson", summary="benchmark changed the router",
                     views=["topic/benchmarks", "subject/memory-machine"])
    )
    res = m.recall("why did the benchmark change the router?")
    routing = res["routing"]
    assert routing["fallback_reasons"] == ["coverage_partial"]
    assert routing["level"] == 2
    assert routing["coverage_signal"] == "complete"
    assert any(a["memory_id"] == "M0002" for a in res["annotations"])
