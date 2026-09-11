from memory_machine.config import Config
from memory_machine.coordinator import Machine
from memory_machine.tape import MemoryRecord, Tape

from fakes import FakeClient, text


def _machine(tmp_path, handler):
    client = FakeClient(handler)
    cfg = Config(capacity=3, router_enabled=False)
    return Machine(tmp_path, config=cfg, client=client)


def test_run_full_cycle(tmp_path):
    def handler(messages, temperature):
        sys_text = text(messages, "system")
        if "You are a memory agent" in sys_text:
            return '{"annotations":[{"memory_id":"M0001","note":"prior db decision","relevance":0.9}]}'
        # main chatbot
        return "Use Postgres.\n" + '{"memories":[{"type":"lesson","summary":"pool connections","why":"perf"}]}'

    m = _machine(tmp_path, handler)
    m.add_memory(MemoryRecord(type="decision", summary="Adopt Postgres", why="ACID"), save=True)
    m.set_subject("choose the database", save=True)

    result = m.run("which database should we use?")

    assert result["ok"] is True
    assert result["raw_annotations"] == 1
    assert result["kept_annotations"][0]["memory_id"] == "M0001"
    assert result["reply"] == "Use Postgres."
    assert len(result["memories_saved"]) == 2  # chatbot memory + turn record
    assert result["tape_records"] == 3  # initial + chatbot memory + turn record
    assert result["memories_saved"][0]["type"] == "lesson"  # durable memory first
    assert result["memories_saved"][1]["type"] == "memory"  # turn record last


def test_run_dedups_duplicate_turn_record(tmp_path):
    def handler(messages, temperature):
        sys_text = text(messages, "system")
        if "You are a memory agent" in sys_text:
            return '{"annotations":[]}'
        return "ok"

    m = _machine(tmp_path, handler)
    m.set_subject("s", save=True)
    m.run("same question")
    before = len(m.tape)
    m.run("same question")  # identical turn record -> skipped
    # Only the (empty) chatbot step; the duplicate turn record is not re-appended.
    assert len(m.tape) == before


def test_run_creates_new_agent_as_tape_grows(tmp_path):
    def handler(messages, temperature):
        sys_text = text(messages, "system")
        if "You are a memory agent" in sys_text:
            return '{"annotations":[]}'
        return "ok\n" + '{"memories":[{"type":"decision","summary":"d1"},{"type":"decision","summary":"d2"},{"type":"decision","summary":"d3"},{"type":"decision","summary":"d4"}]}'

    m = _machine(tmp_path, handler)
    m.set_subject("seed decisions", save=True)
    result = m.run("make some decisions")

    # capacity 3 -> 5 records (4 memories + 1 turn record) -> 2 groups, 2 agents
    assert result["new_agents"] == 2
    assert result["groups"] == 2
    assert result["agents"] == 2
    assert result["tape_records"] == 5


def test_run_skips_secret_memories(tmp_path):
    def handler(messages, temperature):
        sys_text = text(messages, "system")
        if "You are a memory agent" in sys_text:
            return '{"annotations":[]}'
        # chatbot reply contains a secret memory
        return "done\n" + '{"memories":[{"type":"decision","summary":"leak","why":"sk-abcdefghijklmnopqrstuvwxyz123456"},{"type":"lesson","summary":"pool connections","why":"perf"}]}'

    m = _machine(tmp_path, handler)
    m.set_subject("s", save=True)
    result = m.run("do something")

    assert result["ok"] is True
    # secret memory skipped; clean memory + turn record kept
    assert result["skipped_secrets"] == 1
    summaries = [r.summary for r in m.tape.read()]
    assert "leak" not in summaries
    assert "pool connections" in summaries


def test_status(tmp_path):
    m = _machine(tmp_path, lambda messages, temperature: '{"annotations":[]}')
    m.add_memory(MemoryRecord(type="decision", summary="a"))
    m.set_subject("s")
    st = m.status()
    assert st["tape_records"] == 1
    assert st["agents"] == 1
    assert st["whiteboard_subject"] == "s"


def test_recall_returns_whiteboard(tmp_path):
    def handler(messages, temperature):
        sys_text = text(messages, "system")
        if "You are a memory agent" in sys_text:
            return '{"checklist":["remember postgres"],"annotations":[{"memory_id":"M0001","note":"db choice","relevance":0.9}]}'
        raise AssertionError("recall should only call agents")

    m = _machine(tmp_path, handler)
    m.add_memory(MemoryRecord(type="decision", summary="Use Postgres", why="ACID"))
    result = m.recall("which database?")

    assert result["ok"] is True
    assert result["annotations"][0]["memory_id"] == "M0001"
    assert result["agents_checklists"][0]["checklist"] == "- remember postgres"
    assert "which database?" in result["render"]
    assert result["tape_records"] == 1  # recall does not write to the tape


def test_checkpoint_writes_back(tmp_path):
    def handler(messages, temperature):
        sys_text = text(messages, "system")
        if "metacognitive layer" in sys_text:
            return '{"understanding":"decided db","checklist":["use postgres"]}'
        raise AssertionError("unexpected call")

    m = _machine(tmp_path, handler)
    m.set_subject("db", save=True)
    result = m.checkpoint(
        "which db?",
        "Use Postgres",
        memories=[{"type": "decision", "summary": "Adopt Postgres", "why": "ACID"}],
    )

    assert result["ok"] is True
    assert len(result["memories_saved"]) == 2  # decision + turn record
    assert result["tape_records"] == 2
    assert m.whiteboard.checklist == "- use postgres"
    assert m.whiteboard.metacognition == "decided db"


def test_add_memory_roundtrip(tmp_path):
    m = _machine(tmp_path, lambda messages, temperature: '{"annotations":[]}')
    res = m.add_memory(MemoryRecord(type="decision", summary="use redis"))
    assert res["record"]["id"] == "M0001"
    # reload from disk
    m2 = _machine(tmp_path, lambda messages, temperature: '{"annotations":[]}')
    assert len(m2.tape) == 1
    assert m2.tape.read()[0].summary == "use redis"


def test_recall_cache_skips_second_call(tmp_path):
    calls = {"n": 0}

    def handler(messages, temperature):
        calls["n"] += 1
        return '{"annotations":[]}'

    m = _machine(tmp_path, handler)
    m.add_memory(MemoryRecord(type="decision", summary="Use Postgres"))
    m.recall("a question about the database")
    m.recall("a question about the database")  # identical -> cache
    assert calls["n"] == 1


def test_recall_trivial_reuses_cache(tmp_path):
    calls = {"n": 0}

    def handler(messages, temperature):
        calls["n"] += 1
        return '{"annotations":[]}'

    m = _machine(tmp_path, handler)
    m.add_memory(MemoryRecord(type="decision", summary="Use Postgres"))
    m.recall("a real question about the database")
    n = calls["n"]
    m.recall("ok")  # trivial -> cached
    assert calls["n"] == n


def test_recall_cross_session(tmp_path):
    sdir = tmp_path / "sessions"
    a = sdir / "ses_a"
    a.mkdir(parents=True)
    Tape(a / "tape.jsonl").append(
        MemoryRecord(type="decision", summary="Use PostgreSQL for the database")
    )
    b = sdir / "ses_b"
    b.mkdir(parents=True)

    m = Machine(b, config=Config(capacity=10, router_enabled=False), client=FakeClient(lambda m_, t: "{\"annotations\":[]}"))
    res = m.recall("which database should we use", cross_session=True)
    assert res["past_hits"]
    assert res["past_hits"][0]["session_id"] == "ses_a"


def test_rollup_archives_old_records(tmp_path):
    def handler(messages, temperature):
        sys_text = text(messages, "system")
        if "consolidating older project memories" in sys_text:
            return "Rolled summary of old memories"
        return '{"annotations":[]}'

    m = _machine(tmp_path, handler)
    for i in range(5):
        m.add_memory(MemoryRecord(type="decision", summary=f"decision {i}"))
    res = m.rollup(keep_recent=2)

    assert res["rolled"] == 3
    active = [r for r in m.tape.read() if r.status == "active"]
    assert len(active) == 3  # 2 kept + 1 rollup
    assert any(r.summary == "Rolled summary of old memories" for r in active)


def test_rollup_derived_from_and_rehydrate(tmp_path):
    def handler(messages, temperature):
        sys_text = text(messages, "system")
        if "consolidating older project memories" in sys_text:
            return "Rolled summary"
        return '{"digest":"d","checklist":[],"annotations":[]}'

    m = _machine(tmp_path, handler)
    for i in range(5):
        m.add_memory(MemoryRecord(type="decision", summary=f"decision {i}"))
    res = m.rollup(keep_recent=2)
    rollup_id = res["rollup_id"]

    rec = {r.id: r for r in m.tape.read()}[rollup_id]
    assert rec.derived_from == res["archived"]

    rh = m.rehydrate(rollup_id)
    assert rh["ok"] is True
    assert len(rh["sources"]) == 3
    assert all(s["status"] == "archived" for s in rh["sources"])

    rh2 = m.rehydrate(rollup_id, reactivate=True)
    assert rh2["reactivated"] is True
    active_ids = {r.id for r in m.tape.read() if r.status == "active"}
    assert set(res["archived"]).issubset(active_ids)


def test_recall_includes_rehydrated(tmp_path):
    state: dict[str, str] = {}

    def handler(messages, temperature):
        sys_text = text(messages, "system")
        if "consolidating older project memories" in sys_text:
            return "Rolled"
        if "You are a memory agent" in sys_text:
            rid = state.get("rollup_id", "")
            anns = (
                f'{{"memory_id":"{rid}","note":"rollup","relevance":0.9}}'
                if rid and rid in sys_text
                else ""
            )
            return f'{{"digest":"d","checklist":[],"annotations":[{anns}]}}'
        return '{"annotations":[]}'

    m = _machine(tmp_path, handler)
    for i in range(5):
        m.add_memory(MemoryRecord(type="decision", summary=f"decision {i}"))
    res = m.rollup(keep_recent=2)
    state["rollup_id"] = res["rollup_id"]

    out = m.recall("what decisions were made?")
    assert out["rehydrated"]
    assert out["rehydrated"][0]["memory_id"] == res["rollup_id"]
    assert len(out["rehydrated"][0]["sources"]) == 3
