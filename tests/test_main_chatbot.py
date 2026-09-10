from memory_machine.main_chatbot import (
    extract_memories,
    main_user_prompt,
    memory_from_spec,
    run_main_chatbot,
)
from memory_machine.whiteboard import Whiteboard

from fakes import FakeClient


def test_extract_memories():
    reply = (
        "We should use Postgres.\n"
        '{"memories":[{"type":"decision","summary":"Adopt Postgres","why":"ACID","files":["db/"]}]}\n'
        "Done."
    )
    clean, memories = extract_memories(reply)
    assert "We should use Postgres." in clean
    assert "Adopt Postgres" not in clean
    assert len(memories) == 1
    assert memories[0]["summary"] == "Adopt Postgres"


def test_extract_memories_none():
    clean, memories = extract_memories("just a normal reply")
    assert clean == "just a normal reply"
    assert memories == []


def test_memory_from_spec_files_string():
    rec = memory_from_spec({"type": "lesson", "summary": "s", "files": "a, b"})
    assert rec.files == ["a", "b"]


def test_memory_from_spec_invalid():
    assert memory_from_spec({"type": "", "summary": ""}) is None
    assert memory_from_spec({"type": "decision", "summary": ""}) is None


def test_run_main_chatbot():
    wb = Whiteboard(subject="db choice")
    client = FakeClient(
        lambda messages, temperature: (
            "Use Postgres.\n"
            '{"memories":[{"type":"decision","summary":"Adopt Postgres","why":"ACID"}]}'
        )
    )
    reply, memories, reasoning = run_main_chatbot(client, wb, "pick a database")
    assert reply == "Use Postgres."
    assert len(memories) == 1
    assert memories[0].type == "decision"
    assert reasoning == ""  # FakeClient has no complete_with_reasoning


class _ReasoningClient:
    def complete_with_reasoning(self, messages, *, temperature=0.0):
        return (
            "Use Postgres.\n"
            '{"memories":[{"type":"decision","summary":"Adopt Postgres"}]}',
            "the whiteboard says postgres is settled",
        )


def test_run_main_chatbot_captures_reasoning():
    wb = Whiteboard(subject="db choice")
    reply, memories, reasoning = run_main_chatbot(_ReasoningClient(), wb, "pick a database")
    assert reply == "Use Postgres."
    assert reasoning == "the whiteboard says postgres is settled"


def test_extra_context_is_in_prompt_but_not_whiteboard():
    wb = Whiteboard(subject="s")
    prompt = main_user_prompt(wb, "task", extra_context="## Documents\n\nsome doc chunk")
    assert "## External context" in prompt
    assert "some doc chunk" in prompt
    # External context is a separate section; it is not merged into the whiteboard.
    assert wb.annotations == []
    assert wb.context == []


class _StreamClient:
    def stream(self, messages, *, temperature=0.0):
        yield "Use Postgres.", "thinking about the db\n"
        yield '.\n{"memories":[{"type":"decision","summary":"Adopt Postgres"}]}', ""
        yield "", ""


def test_run_main_chatbot_streams_and_strips_json():
    wb = Whiteboard(subject="db")
    tokens: list[tuple[str, str]] = []
    reply, memories, reasoning = run_main_chatbot(
        _StreamClient(), wb, "pick db", on_token=lambda c, r: tokens.append((c, r))
    )
    assert reasoning == "thinking about the db\n"
    assert len(memories) == 1
    assert "Use Postgres." in reply
    streamed = "".join(c for c, _ in tokens)
    assert "Use Postgres." in streamed
    assert "memories" not in streamed  # JSON block stripped from the stream
