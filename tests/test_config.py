from memory_machine.config import Config, DEFAULT_CAPACITY


def test_defaults_are_valid():
    cfg = Config()
    assert cfg.validate() == []


def test_clamps_capacity_and_budgets():
    cfg = Config(capacity=0, whiteboard_budget=10, consolidate_threshold=1)
    assert cfg.capacity == 1
    assert cfg.whiteboard_budget == 100
    assert cfg.consolidate_threshold >= cfg.whiteboard_budget + 1


def test_non_int_values_fall_back():
    cfg = Config(capacity="abc", whiteboard_budget="x")
    assert cfg.capacity == DEFAULT_CAPACITY
    assert cfg.whiteboard_budget == 4000  # DEFAULT_WHITEBOARD_BUDGET


def test_base_url_trailing_slash_removed():
    cfg = Config(base_url="https://api.deepseek.com/")
    assert cfg.base_url == "https://api.deepseek.com"


def test_validate_flags_bad_base_url():
    cfg = Config(base_url="not-a-url")
    assert any("base_url" in e for e in cfg.validate())


def test_from_dict_ignores_unknown_keys():
    cfg = Config.from_dict({"capacity": 7, "bogus": 1})
    assert cfg.capacity == 7


def test_graph_defaults_are_on_and_consistent():
    cfg = Config()
    assert cfg.graph_enabled is True
    assert cfg.graph_conversation_enabled is True
    assert cfg.graph_recall_mode == "augment_conversation"
    assert cfg.graph_depth == 2
    assert cfg.graph_confidence_hypothesis <= cfg.graph_confidence_auto
    assert cfg.document_graph_enabled is True
    assert cfg.graph_batch_size == 8
    assert cfg.graph_batch_max_chars == 12000


def test_graph_config_clamps_and_normalizes():
    cfg = Config(
        graph_recall_mode="nope",
        graph_depth=99,
        graph_top_k=0,
        graph_confidence_auto=0.5,
        graph_confidence_hypothesis=0.9,
        graph_extract_types=" Decision , ,Lesson ",
    )
    assert cfg.graph_recall_mode == "off"
    assert cfg.graph_depth == 4
    assert cfg.graph_top_k == 1
    assert cfg.graph_confidence_auto == 0.5
    assert cfg.graph_confidence_hypothesis == 0.5
    assert cfg.graph_extract_types == "decision,lesson"


def test_experimental_defaults_are_off():
    """N10: every experimental/recall layer stays off in a clean config."""
    cfg = Config()
    assert cfg.evidence_payload == "off"
    assert cfg.evidence_payload_window is False
    assert cfg.plasticity_mode == "off"
    assert cfg.trilepsia_enabled is False
    assert cfg.trilepsia_recall_mode == "off"
    assert cfg.router_enabled is False
    assert cfg.document_graph_enabled is True  # shipped write-time layer, not recall
