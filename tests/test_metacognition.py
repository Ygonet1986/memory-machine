from memory_machine.metacognition import update_metacognition
from memory_machine.whiteboard import Whiteboard

from fakes import FakeClient


def test_update_with_client():
    wb = Whiteboard(subject="migrate auth")
    client = FakeClient(
        lambda messages, temperature: (
            '{"understanding":"migrating auth; postgres settled",'
            '"checklist":["use Postgres","pool connections"]}'
        )
    )
    out = update_metacognition(wb, client, task="decide db", reply="Use Postgres")
    assert out == "migrating auth; postgres settled"
    assert wb.metacognition == out
    assert wb.checklist == "- use Postgres\n- pool connections"


def test_update_evolves_previous_checklist():
    wb = Whiteboard(subject="s", metacognition="old", checklist="- old item")
    client = FakeClient(
        lambda messages, temperature: '{"understanding":"new","checklist":["new item"]}'
    )
    update_metacognition(wb, client, task="t", reply="r")
    assert wb.metacognition == "new"
    assert wb.checklist == "- new item"


def test_update_deterministic_fallback():
    wb = Whiteboard(subject="migrate auth")
    out = update_metacognition(wb, None, task="decide db", reply="Use Postgres")
    assert "migrate auth" in out
    assert "Use Postgres" in out


def test_update_falls_back_on_llm_error():
    wb = Whiteboard(subject="s")

    def boom(messages, temperature):
        raise RuntimeError("down")

    client = FakeClient(boom)
    out = update_metacognition(wb, client, task="t", reply="r")
    assert out  # deterministic fallback produced something


def test_metacognition_and_checklist_roundtrip(tmp_path):
    from memory_machine.whiteboard import load_whiteboard, save_whiteboard

    wb = Whiteboard(subject="s", metacognition="understanding", checklist="- a\n- b")
    path = tmp_path / "wb.json"
    save_whiteboard(wb, path)
    loaded = load_whiteboard(path)
    assert loaded.metacognition == "understanding"
    assert loaded.checklist == "- a\n- b"


def test_checklist_in_render():
    wb = Whiteboard(subject="s", checklist="- item")
    text = wb.render()
    assert "Checklist (must remember)" in text
    assert "- item" in text
