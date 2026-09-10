import pytest

from memory_machine.secrets import SecretError, assert_clean, scan_text
from memory_machine.tape import MemoryRecord, Tape


def test_scan_detects_api_key():
    hits = scan_text("the key is sk-abcdefghijklmnopqrstuvwxyz123456")
    assert hits
    assert any(h.rule == "openai-style api key" for h in hits)


def test_scan_detects_private_key():
    assert scan_text("-----BEGIN RSA PRIVATE KEY-----")


def test_scan_detects_bearer():
    assert scan_text("Authorization: Bearer abcdefghijklmnopqrstuvwxyz012345")


def test_scan_no_false_positive():
    assert scan_text("Use Postgres for the primary database") == []


def test_assert_clean_raises():
    with pytest.raises(SecretError):
        assert_clean("key sk-abcdefghijklmnopqrstuvwxyz123456")


def test_tape_rejects_secret(tmp_path):
    tape = Tape(tmp_path / "tape.jsonl")
    rec = MemoryRecord(type="memory", summary="key", why="sk-abcdefghijklmnopqrstuvwxyz123456")
    with pytest.raises(SecretError):
        tape.append(rec)
    assert len(tape) == 0


def test_tape_accepts_clean(tmp_path):
    tape = Tape(tmp_path / "tape.jsonl")
    tape.append(MemoryRecord(type="decision", summary="Use Postgres", why="ACID"))
    assert len(tape) == 1
