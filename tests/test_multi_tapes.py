"""Verify multi-tape correctness: each topic owns an independent tape whose
memory agents grow separately, and switching loads the right tape."""


from memory_machine.config import Config
from memory_machine.coordinator import Machine
from memory_machine.tape import MemoryRecord

from app import backend as backend_mod
from app import settings as settings_mod


def test_core_two_tapes_grow_agents_independently(tmp_path):
    ma = Machine(tmp_path / "a", config=Config(capacity=2))
    mb = Machine(tmp_path / "b", config=Config(capacity=2))

    for i in range(3):
        ma.add_memory(MemoryRecord(type="decision", summary=f"alpha-{i}"))
    mb.add_memory(MemoryRecord(type="decision", summary="beta-0"))

    st_a = ma.status()
    st_b = mb.status()

    assert st_a["tape_records"] == 3
    assert st_a["agents"] == 2  # capacity 2 -> 3 records -> 2 groups / 2 agents
    assert st_b["tape_records"] == 1
    assert st_b["agents"] == 1

    # Independent on-disk state
    assert (tmp_path / "a" / "manifest.json").exists()
    assert (tmp_path / "b" / "manifest.json").exists()
    # Agent B must not see alpha's memories
    assert [r.id for r in mb.tape.read()] == ["M0001"]


def test_core_tapes_do_not_leak_between_topics(tmp_path):
    ma = Machine(tmp_path / "a", config=Config(capacity=2))
    mb = Machine(tmp_path / "b", config=Config(capacity=2))

    ma.add_memory(MemoryRecord(type="decision", summary="only in A"))

    # b's manifest must have no groups/agents yet
    assert len(mb.manifest.groups) == 0
    assert len(mb.manifest.agents) == 0
    assert len(mb.tape.read()) == 0


def test_backend_switching_loads_correct_tape(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_mod, "APP_DIR", tmp_path)
    settings_mod.save_settings(
        {
            "api_key": "x",
            "model": "deepseek-v4-flash",
            "base_url": "https://api.deepseek.com",
            "memory_root": str(tmp_path / "data"),
            "multi_topic": False,
        }
    )
    b = backend_mod.Backend()
    ta = b.new_topic("alpha")
    # Grow alpha's tape while it is active (3 records)
    for i in range(3):
        b._machine.add_memory(MemoryRecord(type="decision", summary=f"alpha-{i}"))

    tb = b.new_topic("beta")  # beta becomes active
    b._machine.add_memory(MemoryRecord(type="decision", summary="beta-0"))

    b.switch_topic(ta["id"])
    st = b.status()
    assert st["tape_records"] == 3
    assert [r.summary for r in b._machine.tape.read()] == ["alpha-0", "alpha-1", "alpha-2"]

    b.switch_topic(tb["id"])
    st = b.status()
    assert st["tape_records"] == 1
    assert [r.summary for r in b._machine.tape.read()] == ["beta-0"]


def test_backend_new_topic_starts_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_mod, "APP_DIR", tmp_path)
    settings_mod.save_settings(
        {
            "api_key": "x",
            "model": "deepseek-v4-flash",
            "base_url": "https://api.deepseek.com",
            "memory_root": str(tmp_path / "data"),
            "multi_topic": False,
        }
    )
    b = backend_mod.Backend()
    t = b.new_topic("fresh")
    st = b.status()
    assert st["tape_records"] == 0
    assert st["agents"] == 0
    assert st["topic_id"] == t["id"]
