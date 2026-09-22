from memory_machine.groups import (
    Manifest,
    add_memory,
    ensure_group,
    group_records,
    load_manifest,
    save_manifest,
)
from memory_machine.tape import MemoryRecord, Tape


def _record(summary="x"):
    return MemoryRecord(type="decision", summary=summary)


def test_ensure_group_creates_first_group():
    m = Manifest(capacity=10)
    m, group, agent, created = ensure_group(m, 1)
    assert created is True
    assert group.id == "G1"
    assert group.start == 1 and group.end == 10
    assert agent.id == "A1" and agent.group_id == "G1"


def test_ensure_group_reuses_existing_group():
    m = Manifest(capacity=10)
    m, _, _, _ = ensure_group(m, 1)
    m, group, agent, created = ensure_group(m, 7)
    assert created is False
    assert group.id == "G1"
    assert agent.id == "A1"


def test_ensure_group_spawns_new_agent_when_full():
    m = Manifest(capacity=5)
    m, g1, a1, _ = ensure_group(m, 1)
    m, g2, a2, created = ensure_group(m, 6)
    assert created is True
    assert g1.end == 5
    assert g2.start == 6 and g2.end == 10
    assert a1.id == "A1" and a2.id == "A2"
    assert a1.group_id == g1.id and a2.group_id == g2.id


def test_add_memory_grows_manifest(tmp_path):
    tape = Tape(tmp_path / "tape.jsonl")
    m = Manifest(capacity=3)
    rec, group, agent, created = add_memory(tape, m, _record("a"))
    assert rec.id == "M0001" and created is True
    for i in range(2, 5):
        rec, group, agent, created = add_memory(tape, m, _record(f"r{i}"))
    # 4 records at capacity 3 -> two groups, two agents
    assert len(m.groups) == 2
    assert len(m.agents) == 2
    assert group.id == "G2"
    assert m.group_for_id(4).id == "G2"


def test_group_records(tmp_path):
    tape = Tape(tmp_path / "tape.jsonl")
    m = Manifest(capacity=2)
    for i in range(5):
        add_memory(tape, m, _record(f"r{i}"))
    g1 = m.group_for_id(1)
    assert [r.id for r in group_records(tape, g1)] == ["M0001", "M0002"]
    g2 = m.group_for_id(3)
    assert [r.id for r in group_records(tape, g2)] == ["M0003", "M0004"]


def test_group_records_filters_archived(tmp_path):
    tape = Tape(tmp_path / "tape.jsonl")
    m = Manifest(capacity=10)
    for i in range(3):
        add_memory(tape, m, _record(f"r{i}"))
    tape.set_status("M0002", "archived")
    g1 = m.group_for_id(1)
    assert [r.id for r in group_records(tape, g1)] == ["M0001", "M0003"]


def test_manifest_roundtrip(tmp_path):
    m = Manifest(capacity=5)
    m, _, _, _ = ensure_group(m, 1)
    path = tmp_path / "manifest.json"
    save_manifest(m, path)
    loaded = load_manifest(path)
    assert loaded.capacity == 5
    assert len(loaded.groups) == 1
    assert loaded.groups[0].id == "G1"
    assert loaded.agents[0].id == "A1"


def test_default_capacity_is_500():
    assert Manifest().capacity == 500


def test_group_of_500_then_next_group():
    m = Manifest()
    m, g1, a1, created = ensure_group(m, 1)
    assert created is True
    assert (g1.start, g1.end) == (1, 500)
    assert a1.id == "A1"

    m, same, _agent, created = ensure_group(m, 500)
    assert created is False
    assert same.id == "G1"

    m, g2, a2, created = ensure_group(m, 501)
    assert created is True
    assert (g2.start, g2.end) == (501, 1000)
    assert a2.id == "A2" and g2.agent_id == "A2"
