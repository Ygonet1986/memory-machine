"""Dimension boards conformance: per-dimension working memory.

Covers the `whiteboard_mode="dimension"` row of the conformance matrix mode
table: board creation/inheritance, isolation between dimensions, persistence
round-trip, render selection, and that boards do not count toward the primary
consolidation threshold.
"""

from __future__ import annotations

from memory_machine.whiteboard import (
    Annotation,
    Whiteboard,
    load_whiteboard,
    save_whiteboard,
    size_chars,
)


def test_for_dimension_inherits_subject_and_keeps_own_state():
    primary = Whiteboard(subject="migrate auth", objective="choose a database")
    semantic = primary.for_dimension("semantic")
    temporal = primary.for_dimension("temporal")
    assert semantic.subject == "migrate auth" and semantic.objective == "choose a database"
    semantic.checklist = "do not reopen Postgres"
    semantic.annotations = [Annotation(memory_id="M0001", note="n", relevance=0.9)]
    assert temporal.checklist == ""
    assert temporal.annotations == []
    assert primary.for_dimension("semantic") is semantic  # idempotent accessor


def test_boards_survive_roundtrip_and_render_selectively(tmp_path):
    primary = Whiteboard(subject="s", objective="o")
    primary.for_dimension("semantic").checklist = "keep decisions"
    primary.for_dimension("temporal").checklist = "check the dates"
    path = tmp_path / "whiteboard.json"
    save_whiteboard(primary, path)
    loaded = load_whiteboard(path)
    assert set(loaded.boards) == {"semantic", "temporal"}
    assert loaded.boards["temporal"].checklist == "check the dates"
    rendered = loaded.render_boards(["temporal"])
    assert "temporal" in rendered and "semantic" not in rendered


def test_boards_do_not_count_toward_primary_consolidation_size():
    primary = Whiteboard(subject="s")
    before = size_chars(primary)
    primary.for_dimension("semantic").context = "x" * 5000
    assert size_chars(primary) == before  # boards are excluded by size_chars


def test_legacy_whiteboard_without_boards_loads(tmp_path):
    path = tmp_path / "whiteboard.json"
    path.write_text(
        '{"subject": "legacy", "objective": "", "metacognition": "m",'
        ' "checklist": [], "context": "", "pending": [], "annotations": []}',
        encoding="utf-8",
    )
    loaded = load_whiteboard(path)
    assert loaded.subject == "legacy"
    assert loaded.boards == {}
