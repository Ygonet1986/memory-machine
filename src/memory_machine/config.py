"""Configuration for the Memory Machine.

A project is a directory containing ``tape.jsonl`` (long-term memory),
``manifest.json`` (groups/agents), ``whiteboard.json`` (working memory) and
``config.json`` (settings). All paths are resolved relative to the project
root unless absolute.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

# Default group capacity: number of memories held by a single memory agent.
DEFAULT_CAPACITY = 50

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
