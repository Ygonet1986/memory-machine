from memory_machine.consolidate import consolidate_whiteboard
from memory_machine.groups import Manifest
from memory_machine.tape import Tape
from memory_machine.whiteboard import Annotation, Whiteboard

from fakes import FakeClient


def _populated_whiteboard():
    wb = Whiteboard(subject="migrate auth", objective="replace tokens")
    wb.context.append("current tokens are JWT")
    wb.pending.append("decide refresh strategy")
    wb.annotations.append(Annotation(memory_id="M0042", note="old decision on sessions", relevance=0.9))
    return wb


def test_deterministic_consolidation_persists_and_shrinks(tmp_path):
    tape = Tape(tmp_path / "tape.jsonl")
    manifest = Manifest(capacity=50)
    wb = _populated_whiteboard()
    before = len(tape)

    result = consolidate_whiteboard(wb, tape=tape, manifest=manifest)

    assert result["ok"] is True
    # Working state persisted to the tape (no loss of continuity).
    assert len(tape) == before + 1
    persisted = tape.read()[-1]
    assert "M0042" in persisted.why  # annotation memory id survives
    assert "refresh strategy" in persisted.why  # pending item survives
    # Whiteboard shrunk.
    assert wb.annotations == []
    assert wb.pending == []
    assert len(wb.context) == 1
    assert wb.consolidated_from
    # Summary keeps the subject.
    assert "migrate auth" in result["summary"]


def test_llm_consolidation_uses_summary(tmp_path):
    tape = Tape(tmp_path / "tape.jsonl")
    manifest = Manifest(capacity=50)
    wb = _populated_whiteboard()
    client = FakeClient(lambda messages, temperature: "compact: auth migration in progress")

    result = consolidate_whiteboard(wb, client=client, tape=tape, manifest=manifest)

    assert result["summary"] == "compact: auth migration in progress"
    assert wb.context == ["compact: auth migration in progress"]
    assert len(tape) == 1


def test_consolidation_without_tape_is_read_only(tmp_path):
    wb = _populated_whiteboard()
    result = consolidate_whiteboard(wb)
    assert result["persisted"] == []
    assert wb.annotations == []
    assert wb.context
