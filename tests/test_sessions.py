from pathlib import Path

from memory_machine.sessions import (
    list_sessions,
    save_session_meta,
    search_sessions,
    sessions_dir_for,
)
from memory_machine.tape import MemoryRecord, Tape


def _mk_session(sessions_dir: Path, sid: str, summary: str, records: list[str]) -> Path:
    d = sessions_dir / sid
    d.mkdir(parents=True)
    tape = Tape(d / "tape.jsonl")
    for s in records:
        tape.append(MemoryRecord(type="decision", summary=s))
    save_session_meta(d, session_id=sid, summary=summary)
    return d


def test_sessions_dir_for(tmp_path):
    root = tmp_path / "sessions" / "ses_a"
    root.mkdir(parents=True)
    assert sessions_dir_for(root) == tmp_path / "sessions"
    assert sessions_dir_for(tmp_path) is None


def test_list_sessions(tmp_path):
    sdir = tmp_path / "sessions"
    _mk_session(sdir, "ses_a", "built the memory machine", ["Use PostgreSQL"])
    _mk_session(sdir, "ses_b", "music project", ["Use FL Studio"])
    sessions = list_sessions(sdir)
    assert {s["id"] for s in sessions} == {"ses_a", "ses_b"}
    by_id = {s["id"]: s for s in sessions}
    assert by_id["ses_a"]["summary"] == "built the memory machine"
    assert by_id["ses_a"]["records"] == 1


def test_search_sessions(tmp_path):
    sdir = tmp_path / "sessions"
    _mk_session(
        sdir,
        "ses_a",
        "built the memory machine",
        ["Use PostgreSQL for the database", "Pool connections"],
    )
    _mk_session(sdir, "ses_b", "music project", ["Use FL Studio for beats"])

    hits = search_sessions(sdir, "which database should we use", exclude_id="ses_b")
    assert hits
    assert hits[0]["session_id"] == "ses_a"
    assert "PostgreSQL" in hits[0]["summary"]


def test_search_sessions_excludes_current(tmp_path):
    sdir = tmp_path / "sessions"
    _mk_session(sdir, "ses_a", "a", ["Use PostgreSQL"])
    _mk_session(sdir, "ses_b", "b", ["Use PostgreSQL"])
    hits = search_sessions(sdir, "postgresql database", exclude_id="ses_a")
    assert all(h["session_id"] != "ses_a" for h in hits)
