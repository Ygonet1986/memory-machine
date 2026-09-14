from pathlib import Path

from memory_machine.graph import GraphStore
from memory_machine.tape import MemoryRecord

from app import backend as backend_mod
from app import settings as settings_mod

from fakes import FakeClient, text


def _setup(tmp_path, monkeypatch, **settings):
    monkeypatch.setattr(settings_mod, "APP_DIR", tmp_path)
    data = {
        "api_key": "x",
        "model": "deepseek-v4-flash",
        "base_url": "https://api.deepseek.com",
        "memory_root": str(tmp_path / "data"),
        "multi_topic": False,
    }
    data.update(settings)
    settings_mod.save_settings(data)
    return backend_mod.Backend()


def _seed_graph(backend):
    store = GraphStore(backend._machine.root / "graph")
    store.add_entity("Kalak", "person", "M0001", entity_id="E0001")
    store.add_entity("rochedo", "place", "M0001", entity_id="E0002")
    store.add_entity("petronante", "creature", "M0002", entity_id="E0003")
    store.add_entity("criatura", "creature", "M0002", entity_id="E0004")
    store.add_relation("E0001", "cross", "E0002", "M0001", 0.9, relation_id="R0001")
    store.add_relation("E0001", "find", "E0003", "M0002", 0.8, relation_id="R0002")
    store.add_relation(
        "E0004", "possibly_same_as", "E0003", "M0002", 0.75,
        kind="resolution", relation_id="R0003",
    )
    store.add_mention("M0001", "E0001")
    store.add_mention("M0002", "E0004")
    store.add_hypothesis(
        kind="possibly_same_as",
        source_entity="E0004",
        target_entity="E0003",
        source_name="criatura",
        target_name="petronante",
        confidence=0.75,
        memory_id="M0002",
        relation_id="R0003",
    )
    return store


def _seed_tape(backend):
    # Direct tape appends: these tests exercise the read/admin graph API, not
    # the write-time hook (which would call the LLM).
    backend._machine.tape.append(
        MemoryRecord(type="decision", summary="Kalak crossed the rock", why="at dusk")
    )
    backend._machine.tape.append(
        MemoryRecord(type="lesson", summary="Kalak found a petronante", why="later")
    )
    backend._machine.save()


def test_graph_settings_default_to_off(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_mod, "APP_DIR", tmp_path)
    settings = settings_mod.load_settings()
    assert settings["graph_enabled"] is False
    assert settings["graph_recall_mode"] == "off"


def test_backend_maps_graph_settings_to_config(tmp_path, monkeypatch):
    backend = _setup(
        tmp_path, monkeypatch, graph_enabled=True, graph_recall_mode="augment"
    )
    assert backend._machine.config.graph_enabled is True
    assert backend._machine.config.graph_recall_mode == "augment"

    backend = _setup(tmp_path, monkeypatch)
    assert backend._machine.config.graph_enabled is False
    assert backend._machine.config.graph_recall_mode == "off"


def test_backend_maps_recall_modes_exactly_like_cli(tmp_path, monkeypatch):
    for mode in ("off", "augment", "only"):
        backend = _setup(tmp_path, monkeypatch, graph_enabled=True, graph_recall_mode=mode)
        assert backend._machine.config.graph_recall_mode == mode


def test_backend_graph_read_api_and_provenance(tmp_path, monkeypatch):
    backend = _setup(tmp_path, monkeypatch, graph_enabled=True)
    _seed_tape(backend)
    _seed_graph(backend)

    status = backend.graph_status()
    assert status["built"] is True
    assert status["counts"]["entities"] == 4

    listing = backend.graph_entities("kal")
    assert [entity["name"] for entity in listing["entities"]] == ["Kalak"]

    entity = backend.graph_entity("E0001")
    assert entity["ok"] is True
    assert {relation["id"] for relation in entity["relations"]} == {"R0001", "R0002"}

    query = backend.graph_query("Kalak")
    assert query["ok"] is True
    assert {"M0001", "M0002"} <= {item["memory_id"] for item in query["evidence"]}

    path = backend.graph_path("Kalak", "rochedo")
    assert path["ok"] is True and "M0001" in path["evidence"]

    provenance = backend.graph_provenance("R0001")
    assert provenance["ok"] is True
    assert provenance["memory"]["id"] == "M0001"
    assert provenance["memory"]["summary"] == "Kalak crossed the rock"


def test_backend_read_api_never_writes_the_graph(tmp_path, monkeypatch):
    backend = _setup(tmp_path, monkeypatch, graph_enabled=True)
    _seed_tape(backend)
    store = _seed_graph(backend)
    files = ["entities.jsonl", "relations.jsonl", "aliases.jsonl", "mentions.jsonl"]
    before = {
        name: (store.directory / name).read_bytes()
        for name in files
        if (store.directory / name).exists()
    }

    backend.graph_status()
    backend.graph_entities("")
    backend.graph_entity("E0001")
    backend.graph_query("Kalak")
    backend.graph_path("Kalak", "rochedo")
    backend.graph_provenance("R0001")

    after = {
        name: (store.directory / name).read_bytes()
        for name in files
        if (store.directory / name).exists()
    }
    assert before == after


def test_backend_review_uses_the_same_rules(tmp_path, monkeypatch):
    backend = _setup(tmp_path, monkeypatch, graph_enabled=True)
    _seed_tape(backend)
    store = _seed_graph(backend)
    tape_before = (Path(backend._machine.root) / "tape.jsonl").read_bytes()

    review = backend.graph_review()
    assert review["count"] == 1
    assert review["open"][0]["source_name"] == "criatura"

    skipped = backend.graph_decide("H0001", "skip")
    assert skipped["decision"] == "skip"
    assert backend.graph_review()["count"] == 1

    accepted = backend.graph_decide("H0001", "accept")
    assert accepted["decision"] == "accept"
    assert backend.graph_review()["count"] == 0
    merge = next(alias for alias in store.aliases() if alias.method == "merge")
    assert store.index().canonical(merge.alias) == "E0003"
    assert (Path(backend._machine.root) / "tape.jsonl").read_bytes() == tape_before


def test_backend_rejects_unknown_hypothesis(tmp_path, monkeypatch):
    backend = _setup(tmp_path, monkeypatch, graph_enabled=True)
    _seed_tape(backend)
    _seed_graph(backend)
    assert backend.graph_decide("H9999", "accept")["ok"] is False


def test_backend_retry_and_admin_listings(tmp_path, monkeypatch):
    backend = _setup(tmp_path, monkeypatch, graph_enabled=True)
    _seed_tape(backend)
    store = _seed_graph(backend)
    store.mark_pending("M0001", "api down", extractor="llm/v1", attempts=1)

    pending = backend.graph_pending()
    assert pending["count"] == 1
    assert backend.graph_failed()["count"] == 0

    def handler(messages, temperature):
        system = text(messages, "system")
        if "memory agent" in system:
            return '{"digest":"g","annotations":[],"coverage":"complete","missing":[]}'
        return '{"entities":[{"ref":"e1","name":"Kalak","type":"person"}],"events":[],"relations":[]}'

    backend._machine.client = FakeClient(handler)
    retry = backend.graph_retry()
    assert retry["retried"] == 1
    assert retry["outcomes"][0]["status"] == "extracted"
    assert backend.graph_pending()["count"] == 0


def test_backend_rebuild_failure_keeps_graph(tmp_path, monkeypatch):
    backend = _setup(tmp_path, monkeypatch, graph_enabled=True)
    _seed_tape(backend)
    store = _seed_graph(backend)
    before = (store.directory / "entities.jsonl").read_bytes()

    import memory_machine.graph as graph_mod

    def boom(*args, **kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(graph_mod, "_build_into", boom)
    result = backend.graph_rebuild()

    assert result["ok"] is False
    assert "previous graph kept" in result["error"]
    assert (store.directory / "entities.jsonl").read_bytes() == before
