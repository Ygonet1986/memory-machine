from memory_machine.coordinator import Machine
from memory_machine.tape import MemoryRecord

from app import backend as backend_mod
from app import settings as settings_mod


def _setup(tmp_path, monkeypatch, multi_topic):
    monkeypatch.setattr(settings_mod, "APP_DIR", tmp_path)
    settings_mod.save_settings(
        {
            "api_key": "x",
            "model": "deepseek-v4-flash",
            "base_url": "https://api.deepseek.com",
            "memory_root": str(tmp_path / "data"),
            "multi_topic": multi_topic,
        }
    )
    monkeypatch.setattr(Machine, "run", lambda self, msg, **kwargs: {"reply": "hi"})
    return backend_mod.Backend()


def test_run_routes_and_switches_topic(tmp_path, monkeypatch):
    b = _setup(tmp_path, monkeypatch, multi_topic=True)
    t1 = b.new_topic("first")
    t2 = b.new_topic("second")
    assert b.current_topic()["id"] == t2["id"]

    monkeypatch.setattr(b, "_route", lambda msg: t1["id"])

    result = b.run("o que decidimos ontem?")

    assert result["topic_id"] == t1["id"]
    assert b.current_topic()["id"] == t1["id"]


def test_run_falls_back_to_today(tmp_path, monkeypatch):
    b = _setup(tmp_path, monkeypatch, multi_topic=True)
    t = b.new_topic("today")

    monkeypatch.setattr(b, "_route", lambda msg: None)

    result = b.run("vamos começar algo novo")

    assert result["topic_id"] == t["id"]


def test_run_manual_stays_on_current_topic(tmp_path, monkeypatch):
    b = _setup(tmp_path, monkeypatch, multi_topic=False)
    t = b.new_topic("current")

    called = {"routed": False}

    def fake_route(msg):
        called["routed"] = True
        return "some-other"

    monkeypatch.setattr(b, "_route", fake_route)

    result = b.run("qualquer coisa")

    assert called["routed"] is False
    assert result["topic_id"] == t["id"]


def test_set_multi_topic_persists(tmp_path, monkeypatch):
    b = _setup(tmp_path, monkeypatch, multi_topic=False)
    b.set_multi_topic(True)
    assert b.multi_topic() is True
    assert settings_mod.load_settings()["multi_topic"] is True


def _setup_with(tmp_path, monkeypatch, **overrides):
    monkeypatch.setattr(settings_mod, "APP_DIR", tmp_path)
    base = {
        "api_key": "x",
        "model": "deepseek-v4-flash",
        "base_url": "https://api.deepseek.com",
        "memory_root": str(tmp_path / "data"),
        "multi_topic": False,
        "auto_topic": "day",
    }
    base.update(overrides)
    settings_mod.save_settings(base)
    monkeypatch.setattr(Machine, "run", lambda self, msg, **kwargs: {"reply": "hi"})
    return backend_mod.Backend()


def test_auto_topic_day_switches_to_today(tmp_path, monkeypatch):
    b = _setup_with(tmp_path, monkeypatch)
    ta = b.new_topic("a")
    tb = b.new_topic("b")  # newest, still today
    b.switch_topic(ta["id"])
    b.run("hi")
    assert b.current_topic()["id"] == tb["id"]


def test_auto_topic_off_stays_manual(tmp_path, monkeypatch):
    b = _setup_with(tmp_path, monkeypatch, auto_topic="off")
    ta = b.new_topic("a")
    b.new_topic("b")
    b.switch_topic(ta["id"])
    b.run("hi")
    assert b.current_topic()["id"] == ta["id"]


def test_auto_topic_idle_creates_when_stale(tmp_path, monkeypatch):
    b = _setup_with(tmp_path, monkeypatch, auto_topic="idle")
    t = b.new_topic()
    monkeypatch.setattr(backend_mod.Backend, "_hours_since", lambda self, iso: 99999.0)
    b.run("hi")
    assert b.current_topic()["id"] != t["id"]


class _AppFakeLLM:
    def _sys(self, messages):
        return "\n".join(m.get("content", "") for m in messages if m.get("role") == "system")

    def complete(self, messages, *, temperature=0.0):
        sys = self._sys(messages)
        if "You are a memory agent" in sys:
            return '{"checklist":["remember postgres"],"annotations":[{"memory_id":"M0001","note":"db choice","relevance":0.9}]}'
        if "metacognitive layer" in sys:
            return '{"understanding":"choosing db","checklist":["use postgres"]}'
        if "topic router" in sys:
            return '{"topic_id": null}'
        return "ok"

    def complete_with_reasoning(self, messages, *, temperature=0.0):
        sys = self._sys(messages)
        if "main assistant" in sys:
            return (
                "Use Postgres.\n" + '{"memories":[{"type":"lesson","summary":"pool connections"}]}',
                "reasoning here",
            )
        return self.complete(messages, temperature=temperature), ""


def test_full_app_cycle_integration(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_mod, "APP_DIR", tmp_path)
    settings_mod.save_settings(
        {
            "api_key": "x",
            "model": "deepseek-v4-flash",
            "base_url": "https://api.deepseek.com",
            "memory_root": str(tmp_path / "data"),
            "multi_topic": False,
            "auto_topic": "day",
        }
    )
    monkeypatch.setattr(backend_mod, "LLMClient", lambda *a, **k: _AppFakeLLM())

    b = backend_mod.Backend()
    b._machine.add_memory(MemoryRecord(type="decision", summary="Use Postgres", why="ACID"))
    (tmp_path / "doc.txt").write_text("Postgres is the database.")
    b.add_document(tmp_path / "doc.txt")

    r = b.run("which database should we use?")

    assert r["reply"] == "Use Postgres."
    assert r["reasoning"] == "reasoning here"
    assert any(a["memory_id"] == "M0001" for a in r["kept_annotations"])

    st = b.status()
    assert st["whiteboard_checklist"] == "- use postgres"
    assert st["agents_checklists"][0]["checklist"] == "- remember postgres"
    assert st["documents"] == 1
    assert st["tape_records"] >= 2  # seeded decision + chatbot memory + turn record
