from memory_machine.companion_memory import CompanionMemory
from memory_machine.tape import MemoryRecord


def test_supersede_excludes_old_and_derived_from_search_and_payload(tmp_path):
    memory = CompanionMemory(tmp_path)
    old = memory.tape.append(MemoryRecord(
        type="person_report", summary="song for sister",
        origin={"kind": "turn", "turn_ids": ["u1"]},
    ))
    rollup = memory.tape.append(MemoryRecord(
        type="person_report", summary="song for sister (summary)",
        derived_from=[old.id],
    ))
    (tmp_path / "recall_cache.json").write_text('{"subject":"song for sister"}')
    corrected = memory.supersede(old.id, MemoryRecord(
        type="person_report", summary="song for mother",
        origin={"kind": "turn", "turn_ids": ["u2"]},
    ))

    assert corrected.supersedes == old.id
    assert {r.id: r.status for r in memory.tape.read()} == {
        old.id: "superseded", rollup.id: "superseded", corrected.id: "active",
    }
    assert all(r.id not in {old.id, rollup.id} for r in memory.search("song for sister"))
    assert [r.id for r in memory.search("song for mother")] == [corrected.id]
    assert memory.evidence([old.id, rollup.id, corrected.id])[0]["memory_id"] == corrected.id
    assert len(memory.evidence([old.id, rollup.id, corrected.id])) == 1
    assert not (tmp_path / "recall_cache.json").exists()
    assert all(r.id != old.id for r in CompanionMemory(tmp_path).search("song for sister"))


def test_supersede_rejects_repeat_and_type_change(tmp_path):
    memory = CompanionMemory(tmp_path)
    old = memory.tape.append(MemoryRecord(type="person_report", summary="A"))
    from pytest import raises

    with raises(ValueError, match="preserves"):
        memory.supersede(old.id, MemoryRecord(type="story", summary="B"))
    memory.supersede(old.id, MemoryRecord(type="person_report", summary="B"))
    with raises(ValueError, match="eligible"):
        memory.supersede(old.id, MemoryRecord(type="person_report", summary="C"))
