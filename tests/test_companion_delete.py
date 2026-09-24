from memory_machine.companion_memory import CompanionMemory
from memory_machine.coordinator import Machine
from memory_machine.tape import MemoryRecord


def test_delete_cascade_removes_descendants_and_prevents_id_reuse(tmp_path):
    memory = CompanionMemory(tmp_path)
    source = memory.tape.append(MemoryRecord(type="person_report", summary="private sister song"))
    child = memory.tape.append(MemoryRecord(
        type="episode", summary="private sister song discussed",
        derived_from=[source.id],
    ))
    rollup = memory.tape.append(MemoryRecord(
        type="memory", summary="private sister song summary",
        derived_from=[child.id],
    ))
    independent = memory.tape.append(MemoryRecord(type="persona", summary="likes piano"))
    corrected = memory.supersede(source.id, MemoryRecord(
        type="person_report", summary="song for mother",
    ))
    cache = tmp_path / "recall_cache.json"
    cache.write_text('{"result":{"evidence":"private sister song"}}')
    (tmp_path / "context.json").write_text('{"summary":"private sister song"}')
    (tmp_path / "whiteboard.json").write_text('{"subject":"private sister song"}')
    graph = tmp_path / "graph"
    graph.mkdir()
    (graph / "derived.json").write_text('{"summary":"private sister song"}')

    removed = memory.delete(source.id)
    assert set(removed) == {source.id, child.id, rollup.id, corrected.id}
    assert [r.id for r in memory.tape.read()] == [independent.id]
    assert not cache.exists()
    assert not (tmp_path / "context.json").exists()
    assert not (tmp_path / "whiteboard.json").exists()
    assert not graph.exists()
    assert memory.evidence(removed) == []
    assert all(r.id not in removed for r in memory.search("private sister song"))
    assert Machine(tmp_path).rehydrate(rollup.id)["ok"] is False

    fresh = CompanionMemory(tmp_path)
    next_record = fresh.tape.append(MemoryRecord(type="person_report", summary="fresh report"))
    assert next_record.id == "M0006"
    assert fresh.delete(source.id) == []


def test_delete_rollup_preserves_unrelated_source(tmp_path):
    memory = CompanionMemory(tmp_path)
    a = memory.tape.append(MemoryRecord(type="person_report", summary="a"))
    b = memory.tape.append(MemoryRecord(type="person_report", summary="b"))
    rollup = memory.tape.append(MemoryRecord(
        type="memory", summary="a and b", derived_from=[a.id, b.id],
    ))
    assert set(memory.delete(a.id)) == {a.id, rollup.id}
    assert [r.id for r in memory.tape.read()] == [b.id]
