from memory_machine.config import Config
from memory_machine.coordinator import Machine
from memory_machine.groups import Manifest, ensure_group
from memory_machine.router import select_groups, select_groups_llm
from memory_machine.tape import MemoryRecord, Tape

from fakes import FakeClient


def _two_groups(tmp_path, capacity=2):
    tape = Tape(tmp_path / "tape.jsonl")
    manifest = Manifest(capacity=capacity)
    tape.append(MemoryRecord(id="M0001", type="decision", summary="Use PostgreSQL database"))
    tape.append(MemoryRecord(id="M0002", type="decision", summary="Pool database connections"))
    tape.append(MemoryRecord(id="M0003", type="preference", summary="Compose bossa nova guitar"))
    tape.append(MemoryRecord(id="M0004", type="preference", summary="Use FL Studio for beats"))
    manifest, g1, a1, _ = ensure_group(manifest, 1)
    manifest, g2, a2, _ = ensure_group(manifest, 3)
    return tape, manifest, g1, g2, a1, a2


def test_select_groups_topk(tmp_path):
    tape, manifest, g1, g2, _a1, _a2 = _two_groups(tmp_path)
    selected = select_groups(tape, manifest, "which database should we use", top_k=1)
    assert [g.id for g in selected] == ["G1"]


def test_select_groups_uses_agent_digest(tmp_path):
    tape, manifest, g1, g2, a1, a2 = _two_groups(tmp_path)
    a1.digest = "postgresql database pooling"
    a1.digest_records = 2
    a2.digest = "music composition guitar"
    a2.digest_records = 2
    selected = select_groups(tape, manifest, "database pooling", top_k=1)
    assert [g.id for g in selected] == ["G1"]


def test_select_groups_stale_digest_falls_back_to_records(tmp_path):
    tape, manifest, g1, g2, a1, a2 = _two_groups(tmp_path)
    # Stale digest (digest_records != actual) must be ignored in favor of records.
    a1.digest = "irrelevant music stuff"
    a1.digest_records = 1  # actual is 2 -> stale
    selected = select_groups(tape, manifest, "database", top_k=1)
    assert [g.id for g in selected] == ["G1"]


def test_select_groups_fallback_full(tmp_path):
    tape, manifest, g1, g2, _a1, _a2 = _two_groups(tmp_path)
    selected = select_groups(tape, manifest, "zzzzz nothing matches", top_k=1)
    assert {g.id for g in selected} == {"G1", "G2"}


def test_select_groups_fallback_recent(tmp_path):
    tape, manifest, g1, g2, _a1, _a2 = _two_groups(tmp_path)
    selected = select_groups(
        tape, manifest, "zzzzz nothing matches", top_k=1, fallback="recent"
    )
    assert [g.id for g in selected] == ["G2"]


def test_recall_router_consults_only_selected(tmp_path):
    calls = {"n": 0}

    def handler(messages, temperature):
        calls["n"] += 1
        return '{"digest":"...","checklist":[],"annotations":[]}'

    m = Machine(
        tmp_path,
        config=Config(capacity=2, router_top_k=1, router_enabled=True, router_mode="lexical"),
        client=FakeClient(handler),
    )
    for s in [
        "Use PostgreSQL database",
        "Pool database connections",
        "Compose bossa nova guitar",
        "Use FL Studio for beats",
    ]:
        m.add_memory(MemoryRecord(type="decision", summary=s))

    calls["n"] = 0
    res = m.recall("which database should we use")
    assert res["total_groups"] == 2
    assert res["routed_groups"] == 1
    assert calls["n"] == 1  # only the selected group's agent was consulted


class _FakeEmbedder:
    """Deterministic fake: database-ish texts map to [1,0], others to [0,1]."""

    def embed(self, texts):
        out = []
        for t in texts:
            low = t.lower()
            is_db = any(k in low for k in ("database", "postgres", "rdbms", "accounts"))
            out.append([1.0, 0.0] if is_db else [0.0, 1.0])
        return out


def test_select_groups_semantic(tmp_path):
    tape, manifest, g1, g2, _a1, _a2 = _two_groups(tmp_path)
    # Lexically distant query that BM25 would miss, resolved by embeddings.
    selected = select_groups(
        tape, manifest, "which RDBMS holds accounts?", top_k=1, embedder=_FakeEmbedder()
    )
    assert [g.id for g in selected] == ["G1"]


def test_select_groups_llm(tmp_path):
    tape, manifest, g1, g2, _a1, _a2 = _two_groups(tmp_path)
    client = FakeClient(lambda messages, temperature: '{"groups":["G1"]}')
    selected = select_groups_llm(
        tape, manifest, "which RDBMS holds accounts?", client, top_k=1
    )
    assert [g.id for g in selected] == ["G1"]


def test_select_groups_llm_empty_returns_none(tmp_path):
    tape, manifest, *_ = _two_groups(tmp_path)
    client = FakeClient(lambda messages, temperature: '{"groups":[]}')
    assert select_groups_llm(tape, manifest, "x", client) is None


def test_select_groups_llm_ignores_unknown_ids(tmp_path):
    tape, manifest, *_ = _two_groups(tmp_path)
    client = FakeClient(lambda messages, temperature: '{"groups":["G99"]}')
    assert select_groups_llm(tape, manifest, "x", client) is None


def test_recall_router_llm_mode(tmp_path):
    calls = {"agents": 0, "router": 0}

    def handler(messages, temperature):
        sys_text = "\n".join(m.get("content", "") for m in messages if m.get("role") == "system")
        if "You route a query" in sys_text:
            calls["router"] += 1
            return '{"groups":["G1"]}'
        calls["agents"] += 1
        return '{"digest":"d","checklist":[],"annotations":[]}'

    m = Machine(
        tmp_path,
        config=Config(capacity=2, router_top_k=1, router_enabled=True, router_mode="llm", graph_enabled=False),
        client=FakeClient(handler),
    )
    for s in [
        "Use PostgreSQL database",
        "Pool database connections",
        "Compose bossa nova guitar",
        "Use FL Studio for beats",
    ]:
        m.add_memory(MemoryRecord(type="decision", summary=s))

    res = m.recall("which database should we use")
    assert res["total_groups"] == 2
    assert res["routed_groups"] == 1
    assert calls["agents"] == 1  # only the selected group's agent
    assert calls["router"] == 1  # one routing call
