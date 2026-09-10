from memory_machine.whiteboard import (
    Annotation,
    Whiteboard,
    load_whiteboard,
    merge_annotations,
    needs_consolidation,
    save_whiteboard,
    size_chars,
)


def _ann(memory_id, note, relevance=0.5, agent_id="A1"):
    return Annotation(memory_id=memory_id, note=note, relevance=relevance, agent_id=agent_id)


def test_merge_dedupes_by_memory_id():
    wb = Whiteboard(subject="architecture")
    kept = merge_annotations(
        wb,
        [_ann("M0001", "from A", 0.9, "A1"), _ann("M0001", "from B", 0.5, "A2")],
        budget=1000,
    )
    assert len(kept) == 1
    assert kept[0].note == "from A"


def test_merge_keeps_highest_relevance():
    wb = Whiteboard(subject="x")
    merge_annotations(wb, [_ann("M0001", "low", 0.2, "A1")], budget=1000)
    merge_annotations(wb, [_ann("M0001", "high", 0.9, "A2")], budget=1000)
    assert wb.annotations[0].note == "high"


def test_merge_ranks_and_applies_budget():
    wb = Whiteboard(subject="x")
    anns = [
        _ann("M0001", "x" * 100, 0.3),
        _ann("M0002", "y" * 100, 0.9),
        _ann("M0003", "z" * 100, 0.7),
    ]
    kept = merge_annotations(wb, anns, budget=150)
    # Only the highest-relevance item fits the tight budget.
    assert len(kept) == 1
    assert kept[0].memory_id == "M0002"


def test_merge_ignores_empty():
    wb = Whiteboard(subject="x")
    merge_annotations(wb, [Annotation(memory_id="", note="")], budget=1000)
    assert wb.annotations == []


def test_size_and_consolidation_trigger():
    wb = Whiteboard(subject="s")
    small = size_chars(wb)
    assert needs_consolidation(wb, threshold=small + 1) is False
    wb.context.append("c" * 5000)
    assert needs_consolidation(wb, threshold=small + 1) is True


def test_roundtrip(tmp_path):
    wb = Whiteboard(subject="s", objective="o", context=["a"], pending=["b"])
    wb.annotations.append(_ann("M0001", "note"))
    path = tmp_path / "whiteboard.json"
    save_whiteboard(wb, path)
    loaded = load_whiteboard(path)
    assert loaded.subject == "s"
    assert loaded.objective == "o"
    assert loaded.annotations[0].memory_id == "M0001"


def test_render():
    wb = Whiteboard(subject="s")
    wb.annotations.append(_ann("M0042", "relevant decision", 0.9))
    text = wb.render()
    assert "Subject: s" in text
    assert "M0042" in text
