"""Configuration for the Memory Machine.

A project is a directory containing ``tape.jsonl`` (long-term memory),
``manifest.json`` (groups/agents), ``whiteboard.json`` (working memory) and
``config.json`` (settings). All paths are resolved relative to the project
root unless absolute.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

# Default group capacity: number of memories held by a single memory agent.
DEFAULT_CAPACITY = 500

# Char budget for annotations held on the whiteboard (token proxy: chars / 4).
DEFAULT_WHITEBOARD_BUDGET = 4000

# When the serialized whiteboard exceeds this many chars it is consolidated.
DEFAULT_CONSOLIDATE_THRESHOLD = 6000

# When the main chatbot's own conversation context exceeds this many chars it
# is consolidated (independent of the whiteboard).
DEFAULT_CONTEXT_CONSOLIDATE_THRESHOLD = 6000

DEFAULT_MODEL = "deepseek-v4-flash"
DEFAULT_API_KEY_ENV = "DEEPSEEK_API_KEY"
DEFAULT_BASE_URL = "https://api.deepseek.com"


@dataclass
class Config:
    capacity: int = DEFAULT_CAPACITY
    whiteboard_budget: int = DEFAULT_WHITEBOARD_BUDGET
    consolidate_threshold: int = DEFAULT_CONSOLIDATE_THRESHOLD
    context_consolidate_threshold: int = DEFAULT_CONTEXT_CONSOLIDATE_THRESHOLD
    attach_chunk_size: int = 600
    router_enabled: bool = False
    router_mode: str = "llm"
    router_top_k: int = 5
    router_fallback: str = "full"
    router_full_every: int = 0
    view_router_mode: str = "lexical"
    view_top_k: int = 5
    view_dimension_mode: str = "off"
    view_prune: str = "none"
    agent_mode: str = "group"
    agent_history_messages: int = 10
    answerer_history_messages: int = 10
    answerer_observer: bool = True
    whiteboard_mode: str = "single"
    attention_mode: str = "off"
    attention_decay: float = 0.6
    attention_boost: float = 0.8
    attention_found_boost: float = 0.3
    attention_weight: float = 0.5
    attention_gate_min: float = 0.5
    attention_gate_margin: float = 0.1
    evidence_payload: str = "off"
    evidence_payload_budget: int = 4000
    evidence_payload_min_item: int = 200
    evidence_payload_window: bool = False
    graph_enabled: bool = True
    graph_conversation_enabled: bool = True
    graph_path: str = "graph"
    graph_extract_types: str = "decision,lesson,preference,bugfix,build"
    graph_recall_mode: str = "augment_guarded"
    graph_depth: int = 2
    graph_top_k: int = 8
    graph_confidence_auto: float = 0.90
    graph_confidence_hypothesis: float = 0.60
    graph_max_attempts: int = 3
    graph_batch_size: int = 8
    graph_batch_max_chars: int = 12000
    graph_hub_degree: int = 0
    graph_augment_hub_degree: int = 20
    graph_augment_min_score: float = 0.80
    graph_augment_max_items: int = 3
    graph_augment_weight: float = 1.0
    graph_augment_question_gate: bool = False
    graph_augment_question_min_cov: float = 0.30
    graph_resolver_candidates: int = 10
    document_graph_enabled: bool = True
    document_structure_level: str = "chunk"
    document_window_chars: int = 12000
    trilepsia_enabled: bool = False
    trilepsia_recall_mode: str = "off"
    trilepsia_window_chars: int = 12000
    trilepsia_batch_size: int = 8
    trilepsia_max_attempts: int = 3
    trilepsia_schema: str = ""
    plasticity_mode: str = "off"
    coverage_mode: str = "off"
    cascade_min_score: float = 0.0
    cascade_expand_top_k: int = 5
    embedding_model: str = ""
    embedding_base_url: str = ""
    embedding_api_key_env: str = ""
    ablation_no_checklist: bool = False
    model: str = DEFAULT_MODEL
    base_url: str = DEFAULT_BASE_URL
    api_key_env: str = DEFAULT_API_KEY_ENV
    tape_path: str = "tape.jsonl"
    manifest_path: str = "manifest.json"
    whiteboard_path: str = "whiteboard.json"
    context_path: str = "context.json"

    def __post_init__(self) -> None:
        def _int(value: Any, default: int) -> int:
            try:
                return int(value)
            except (TypeError, ValueError):
                return default

        self.capacity = max(1, _int(self.capacity, DEFAULT_CAPACITY))
        self.whiteboard_budget = max(100, _int(self.whiteboard_budget, DEFAULT_WHITEBOARD_BUDGET))
        self.consolidate_threshold = max(
            self.whiteboard_budget + 1,
            _int(self.consolidate_threshold, DEFAULT_CONSOLIDATE_THRESHOLD),
        )
        self.context_consolidate_threshold = max(
            100,
            _int(self.context_consolidate_threshold, DEFAULT_CONTEXT_CONSOLIDATE_THRESHOLD),
        )
        self.attach_chunk_size = max(100, _int(self.attach_chunk_size, 600))
        self.router_enabled = bool(self.router_enabled)
        self.router_mode = (
            self.router_mode
            if self.router_mode in {"lexical", "embedding", "llm", "views", "cascade"}
            else "lexical"
        )
        self.router_top_k = max(1, _int(self.router_top_k, 5))
        self.router_fallback = (
            self.router_fallback if self.router_fallback in {"full", "recent"} else "full"
        )
        self.router_full_every = max(0, _int(self.router_full_every, 0))
        self.view_router_mode = (
            self.view_router_mode if self.view_router_mode in {"lexical", "llm"} else "lexical"
        )
        self.view_top_k = max(1, _int(self.view_top_k, 5))
        self.view_dimension_mode = (
            self.view_dimension_mode if self.view_dimension_mode in {"off", "auto"} else "off"
        )
        self.view_prune = self.view_prune if self.view_prune in {"none", "subject"} else "none"
        self.agent_mode = self.agent_mode if self.agent_mode in {"group", "view"} else "group"
        self.agent_history_messages = max(
            0, min(50, _int(self.agent_history_messages, 10)))
        self.answerer_history_messages = max(
            0, min(50, _int(self.answerer_history_messages, 10)))
        self.answerer_observer = bool(self.answerer_observer)
        self.whiteboard_mode = (
            self.whiteboard_mode if self.whiteboard_mode in {"single", "dimension"} else "single"
        )
        self.attention_mode = (
            self.attention_mode
            if self.attention_mode in {"off", "prior", "context", "state"}
            else "off"
        )
        for name, default in (
            ("attention_decay", 0.6),
            ("attention_boost", 0.8),
            ("attention_found_boost", 0.3),
            ("attention_weight", 0.5),
            ("attention_gate_min", 0.5),
            ("attention_gate_margin", 0.1),
        ):
            try:
                value = float(getattr(self, name))
            except (TypeError, ValueError):
                value = default
            setattr(self, name, max(0.0, min(1.0, value)))
        self.evidence_payload = (
            self.evidence_payload
            if self.evidence_payload in {"off", "budgeted", "full"}
            else "off"
        )
        self.evidence_payload_budget = max(0, _int(self.evidence_payload_budget, 4000))
        self.evidence_payload_min_item = max(0, _int(self.evidence_payload_min_item, 200))
        self.evidence_payload_window = bool(self.evidence_payload_window)
        self.graph_enabled = bool(self.graph_enabled)
        self.graph_conversation_enabled = bool(self.graph_conversation_enabled)
        self.graph_path = (self.graph_path or "graph").strip() or "graph"
        self.graph_extract_types = ",".join(
            t.strip().lower()
            for t in (self.graph_extract_types or "").split(",")
            if t.strip()
        )
        self.graph_recall_mode = (
            self.graph_recall_mode
            if self.graph_recall_mode in {"off", "augment", "augment_guarded", "only"}
            else "off"
        )
        self.graph_depth = max(1, min(4, _int(self.graph_depth, 2)))
        self.graph_top_k = max(1, _int(self.graph_top_k, 8))
        for name, default in (
            ("graph_confidence_auto", 0.90),
            ("graph_confidence_hypothesis", 0.60),
        ):
            try:
                value = float(getattr(self, name))
            except (TypeError, ValueError):
                value = default
            setattr(self, name, max(0.0, min(1.0, value)))
        if self.graph_confidence_hypothesis > self.graph_confidence_auto:
            self.graph_confidence_hypothesis = self.graph_confidence_auto
        self.graph_max_attempts = max(1, min(10, _int(self.graph_max_attempts, 3)))
        self.graph_batch_size = max(1, min(32, _int(self.graph_batch_size, 8)))
        self.graph_batch_max_chars = max(0, _int(self.graph_batch_max_chars, 12000))
        self.graph_hub_degree = max(0, _int(self.graph_hub_degree, 0))
        self.graph_augment_hub_degree = max(0, _int(self.graph_augment_hub_degree, 20))
        self.graph_augment_max_items = max(0, _int(self.graph_augment_max_items, 3))
        self.graph_augment_question_gate = bool(self.graph_augment_question_gate)
        self.graph_resolver_candidates = max(1, _int(self.graph_resolver_candidates, 10))
        self.document_graph_enabled = bool(self.document_graph_enabled)
        self.document_structure_level = (
            self.document_structure_level
            if self.document_structure_level in {"chunk", "document", "both"}
            else "chunk"
        )
        self.document_window_chars = max(1, _int(self.document_window_chars, 12000))
        self.trilepsia_enabled = bool(self.trilepsia_enabled)
        self.trilepsia_recall_mode = (
            self.trilepsia_recall_mode
            if self.trilepsia_recall_mode in {"off", "augment", "only"}
            else "off"
        )
        self.trilepsia_window_chars = max(1, _int(self.trilepsia_window_chars, 12000))
        self.trilepsia_batch_size = max(1, min(32, _int(self.trilepsia_batch_size, 8)))
        self.trilepsia_max_attempts = max(1, min(10, _int(self.trilepsia_max_attempts, 3)))
        self.trilepsia_schema = str(self.trilepsia_schema or "").strip()
        self.plasticity_mode = (
            self.plasticity_mode
            if self.plasticity_mode in {"off", "observe", "shadow", "update", "deliver"}
            else "off"
        )
        for name, default in (
            ("graph_augment_min_score", 0.80),
            ("graph_augment_weight", 1.0),
            ("graph_augment_question_min_cov", 0.30),
        ):
            try:
                value = float(getattr(self, name))
            except (TypeError, ValueError):
                value = default
            setattr(self, name, max(0.0, min(1.0, value)))
        self.coverage_mode = (
            self.coverage_mode if self.coverage_mode in {"off", "agents", "structural", "both", "judge", "judge_views", "views"} else "off"
        )
        try:
            self.cascade_min_score = float(self.cascade_min_score)
        except (TypeError, ValueError):
            self.cascade_min_score = 0.0
        self.cascade_expand_top_k = max(1, _int(self.cascade_expand_top_k, 5))
        self.embedding_model = (self.embedding_model or "").strip()
        self.embedding_base_url = (self.embedding_base_url or self.base_url).strip().rstrip("/")
        self.embedding_api_key_env = (self.embedding_api_key_env or self.api_key_env).strip()
        self.ablation_no_checklist = bool(self.ablation_no_checklist)
        self.model = (self.model or DEFAULT_MODEL).strip()
        self.base_url = (self.base_url or DEFAULT_BASE_URL).strip().rstrip("/")
        self.api_key_env = (self.api_key_env or DEFAULT_API_KEY_ENV).strip()

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not self.base_url.startswith(("http://", "https://")):
            errors.append(f"base_url must be http(s): {self.base_url!r}")
        if not self.model:
            errors.append("model must not be empty")
        if not self.api_key_env:
            errors.append("api_key_env must not be empty")
        if not self.tape_path:
            errors.append("tape_path must not be empty")
        if not self.manifest_path:
            errors.append("manifest_path must not be empty")
        if not self.whiteboard_path:
            errors.append("whiteboard_path must not be empty")
        return errors

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def save(self, path: Path) -> None:
        path.write_text(json.dumps(self.to_dict(), indent=2) + "\n", encoding="utf-8")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Config":
        known = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in data.items() if k in known})

    @classmethod
    def load(cls, root: Path) -> "Config":
        path = root / "config.json"
        if path.exists():
            try:
                return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))
            except (json.JSONDecodeError, OSError):
                pass
        return cls()


def resolve_path(root: Path, raw: str | Path) -> Path:
    """Resolve a config path against the project root."""
    p = Path(raw)
    if p.is_absolute():
        return p
    return root / p
