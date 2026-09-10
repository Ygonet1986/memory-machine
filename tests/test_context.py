from memory_machine.context import (
    ChatContext,
    append_turn,
    consolidate_context,
    load_context,
    needs_consolidation,
    save_context,
)

from fakes import FakeClient


def test_append_and_render():
    ctx = ChatContext()
    append_turn(ctx, "task 1", "reply 1", subject="s")
    assert len(ctx.turns) == 1
    assert "task 1" in ctx.render()


def test_needs_consolidation():
    ctx = ChatContext()
    append_turn(ctx, "a" * 100, "b" * 100)
    assert needs_consolidation(ctx, threshold=50) is True
    assert needs_consolidation(ctx, threshold=10000) is False


def test_consolidate_folds_turns_into_summary():
    ctx = ChatContext()
    append_turn(ctx, "decide db", "chose Postgres")
    append_turn(ctx, "decide cache", "chose Redis")
    result = consolidate_context(ctx)
    assert result["consolidated"] is True
    assert ctx.turns == []
    assert "chose Postgres" in ctx.summary
    assert ctx.consolidated_from


def test_consolidate_with_llm_uses_narrative():
    ctx = ChatContext()
    append_turn(ctx, "task", "reply")
    client = FakeClient(lambda messages, temperature: "compact narrative")
    consolidate_context(ctx, client=client)
    assert ctx.summary == "compact narrative"
    assert ctx.turns == []


def test_consolidate_empty_is_noop():
    ctx = ChatContext()
    result = consolidate_context(ctx)
    assert result["consolidated"] is False


def test_roundtrip(tmp_path):
    ctx = ChatContext(summary="prior")
    append_turn(ctx, "t", "r")
    path = tmp_path / "context.json"
    save_context(ctx, path)
    loaded = load_context(path)
    assert loaded.summary == "prior"
    assert len(loaded.turns) == 1
