import json

import pytest

from memory_machine.companion_session import CompanionSession
from memory_machine.coordinator import Machine
from memory_machine.tape import MemoryRecord


def _files(root):
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in root.rglob("*") if path.is_file()
    } if root.exists() else {}


def test_save_off_uses_old_memory_but_writes_zero_bytes_to_real_root(tmp_path):
    session = CompanionSession(tmp_path, "person-a", "lia", "main")
    session.run_turn(
        lambda store: store.tape.append(
            MemoryRecord(type="person_report", summary="likes music")
        ), save=True,
    )
    original = _files(session.root)

    def temporary_turn(store):
        assert store.root != session.root
        assert store.search("music")[0].summary == "likes music"
        store.tape.append(MemoryRecord(type="episode", summary="a new conversation"))
        Machine(store.root).save()
        (store.root / "recall_cache.json").write_text('{"result":"temporary"}')
        return len(store.tape.read())

    assert session.run_turn(temporary_turn, save=False) == 2
    assert _files(session.root) == original
    assert [r.summary for r in Machine(session.root).tape.read()] == ["likes music"]


def test_save_off_without_existing_root_never_creates_it(tmp_path):
    session = CompanionSession(tmp_path, "person-b", "lia", "main")
    assert not session.root.exists()
    result = session.run_turn(
        lambda store: store.tape.append(MemoryRecord(
            type="episode", summary="only in temporary root",
        )).id,
        save=False,
    )
    assert result == "M0001"
    assert not session.root.exists()


def test_save_off_cleans_up_when_turn_fails(tmp_path):
    session = CompanionSession(tmp_path, "person-c", "lia", "main")
    session.run_turn(
        lambda store: store.tape.append(MemoryRecord(type="persona", summary="Lia")),
        save=True,
    )
    original = _files(session.root)

    def fail(store):
        store.tape.append(MemoryRecord(type="episode", summary="temporary"))
        raise RuntimeError("response failed")

    with pytest.raises(RuntimeError, match="response failed"):
        session.run_turn(fail, save=False)
    assert _files(session.root) == original


@pytest.mark.parametrize("person_id", ["../other", "a/b", ".", ""])
def test_root_rejects_unsafe_ids(tmp_path, person_id):
    with pytest.raises(ValueError, match="opaque path"):
        CompanionSession(tmp_path, person_id, "lia", "main")


def test_save_off_rejects_root_symlinks_and_external_config(tmp_path):
    session = CompanionSession(tmp_path, "person-d", "lia", "main")
    session.root.mkdir(parents=True)
    (session.root / "config.json").write_text(json.dumps({"tape_path": "/tmp/outside"}))
    with pytest.raises(ValueError, match="inside its root"):
        session.run_turn(lambda store: None, save=False)
    (session.root / "config.json").unlink()
    (session.root / "linked").symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        session.run_turn(lambda store: None, save=False)


def test_root_rejects_symlink_swapped_in_after_session_created(tmp_path):
    session = CompanionSession(tmp_path, "person-e", "lia", "main")
    session.root.parent.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    session.root.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        session.run_turn(lambda store: None, save=False)
