"""Bridge between the Qt UI and the Memory Machine core.

Owns the active topic's ``Machine`` and ``LLMClient``, runs the cycle on a
worker thread so the UI never blocks, and exposes a small thread-safe API.
Each topic owns its own tape; memory agents are created per topic as its tape
grows. In multi-topic mode, an LLM router infers the topic from each message
and switches tapes internally.
"""

from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from memory_machine.config import Config
from memory_machine.coordinator import Machine
from memory_machine.llm import LLMClient

from . import documents as documents_mod
from . import router, topics as topics_mod
from . import websearch
from .settings import load_settings, save_settings


class Backend:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._machine: Machine | None = None
        self._client: LLMClient | None = None
        self._topic_id: str = ""
        self.reload()

    # ------------------------------------------------------------- setup

    def _base(self) -> Path:
        return Path(load_settings()["memory_root"]).expanduser()

    def _build_machine(self, topic_id: str, settings: dict[str, Any]) -> Machine:
        root = topics_mod.topic_root(self._base(), topic_id)
        cfg = Config(
            model=settings["model"],
            base_url=settings["base_url"],
            api_key_env="MEMORY_MACHINE_API_KEY",
        )
        client = LLMClient(settings["base_url"], settings["api_key"], settings["model"])
        return Machine(root, config=cfg, client=client)

    def reload(self) -> None:
        settings = load_settings()
        base = self._base()
        index = topics_mod.load_index(base)
        active = index.get("active", "")
        if not active or topics_mod.get_topic(base, active) is None:
            if not index["topics"]:
                topics_mod.create_topic(base)
            active = topics_mod.active_id(base)
        with self._lock:
            self._machine = self._build_machine(active, settings)
            self._client = self._machine.client
            self._topic_id = active

    def configured(self) -> bool:
        return bool(load_settings().get("api_key", "").strip())

    def multi_topic(self) -> bool:
        return bool(load_settings().get("multi_topic", False))

    def set_multi_topic(self, enabled: bool) -> None:
        settings = load_settings()
        settings["multi_topic"] = bool(enabled)
        save_settings(settings)

    # ------------------------------------------------------------ topics

    def list_topics(self) -> list[dict[str, Any]]:
        return topics_mod.list_topics(self._base())

    def current_topic(self) -> dict[str, Any]:
        info = topics_mod.get_topic(self._base(), self._topic_id)
        return info or {"id": self._topic_id, "name": self._topic_id, "label": ""}

    def new_topic(self, label: str = "") -> dict[str, Any]:
        base = self._base()
        topic = topics_mod.create_topic(base, label=label)
        settings = load_settings()
        with self._lock:
            self._machine = self._build_machine(topic["id"], settings)
            self._client = self._machine.client
            self._topic_id = topic["id"]
        return topic

    def switch_topic(self, topic_id: str) -> dict[str, Any] | None:
        base = self._base()
        if not topics_mod.set_active(base, topic_id):
            return None
        self._switch(topic_id)
        return self.current_topic()

    def _switch(self, topic_id: str) -> None:
        settings = load_settings()
        with self._lock:
            self._machine = self._build_machine(topic_id, settings)
            self._client = self._machine.client
            self._topic_id = topic_id
        topics_mod.set_active(self._base(), topic_id)

    def set_label(self, topic_id: str, label: str) -> dict[str, Any] | None:
        return topics_mod.set_label(self._base(), topic_id, label)

    def delete_topic(self, topic_id: str) -> dict[str, Any]:
        result = topics_mod.delete_topic(self._base(), topic_id)
        if result.get("ok") and topic_id == self._topic_id:
            self.reload()
        return result

    # ----------------------------------------------------------- routing

    def _route(self, message: str) -> str | None:
        return router.route_topic(self._client, self.list_topics(), message)

    @staticmethod
    def _hours_since(iso: str) -> float:
        try:
            dt = datetime.fromisoformat(iso)
        except (ValueError, TypeError):
            return float("inf")
        return (datetime.now() - dt).total_seconds() / 3600.0

    def _auto_topic_id(self) -> str:
        """Pick the topic for "now" according to the auto-topic policy."""
        settings = load_settings()
        policy = settings.get("auto_topic", "day")
        base = self._base()
        if policy == "off":
            return self._topic_id
        if policy == "idle":
            hours = float(settings.get("auto_idle_hours", 6) or 6)
            t = topics_mod.most_recent_topic(base)
            if t is not None:
                last = t.get("last_active") or t.get("created_at") or ""
                if self._hours_since(last) <= hours:
                    return t["id"]
            return topics_mod.create_topic(base)["id"]
        # default: one topic per day
        t = topics_mod.today_topic(base)
        if t is None:
            t = topics_mod.create_topic(base)
        return t["id"]

    def _today_topic_id(self) -> str:
        t = topics_mod.today_topic(self._base())
        if t is None:
            t = topics_mod.create_topic(self._base())
        return t["id"]

    # --------------------------------------------------------- RAG + web

    def add_document(self, src: str | Path) -> dict[str, Any]:
        return documents_mod.add_document(self._base(), Path(src))

    def list_documents(self) -> list[dict[str, Any]]:
        return documents_mod.list_documents(self._base())

    def remove_document(self, name: str) -> bool:
        return documents_mod.remove_document(self._base(), name)

    def search_web(self, message: str) -> str:
        return websearch.format_results(websearch.search(message))

    # ------------------------------------------------------- tape (memory)

    def list_memories(self) -> list[dict[str, Any]]:
        with self._lock:
            assert self._machine is not None
            return [r.to_dict() for r in self._machine.tape.read()]

    def delete_memory(self, memory_id: str) -> bool:
        with self._lock:
            assert self._machine is not None
            return self._machine.tape.delete(memory_id)

    def archive_memory(self, memory_id: str) -> bool:
        with self._lock:
            assert self._machine is not None
            return self._machine.tape.set_status(memory_id, "archived")

    def supersede_memory(self, memory_id: str) -> bool:
        with self._lock:
            assert self._machine is not None
            return self._machine.tape.set_status(memory_id, "superseded")

    def export_memories(self, path: str | Path) -> dict[str, Any]:
        with self._lock:
            assert self._machine is not None
            records = self._machine.tape.read()
            lines = [f"# Memory Machine — {self.current_topic().get('name', '')}\n"]
            for r in records:
                lines.append(
                    f"## {r.id} [{r.type}] ({r.status})\n"
                    f"- **summary:** {r.summary}\n"
                    f"- **why:** {r.why or '-'}\n"
                    f"- **files:** {', '.join(r.files) if r.files else '-'}\n"
                    f"- **created_at:** {r.created_at}\n"
                )
            dest = Path(path).expanduser()
            dest.write_text("\n".join(lines), encoding="utf-8")
            return {"ok": True, "path": str(dest), "count": len(records)}

    def _external_context(self, message: str, use_web: bool) -> str:
        parts: list[str] = []
        doc_text = documents_mod.retrieve(self._base(), message)
        if doc_text:
            parts.append("## Documents\n\n" + doc_text)
        if use_web:
            results = websearch.search(message)
            if results:
                parts.append("## Web search\n\n" + websearch.format_results(results))
        return "\n\n".join(parts)

    # -------------------------------------------------------------- work

    def run(self, message: str, *, use_web: bool = False, on_token: Any = None) -> dict[str, Any]:
        extra = self._external_context(message, use_web)
        with self._lock:
            target = None
            if self.multi_topic():
                target = self._route(message)
            if target is None:
                target = self._auto_topic_id()
            if target != self._topic_id:
                self._switch(target)

            assert self._machine is not None
            self._machine.set_subject(message[:120], save=False)
            result = self._machine.run(message, extra_context=extra, on_token=on_token)
            result["topic_id"] = self._topic_id
            result["topic_name"] = topics_mod.display_name(self.current_topic())
            result["external_context_chars"] = len(extra)
            topics_mod.touch_activity(self._base(), self._topic_id)
            self._update_summary()
            return result

    def _update_summary(self) -> None:
        recs = self._machine.tape.read()  # type: ignore[union-attr]
        parts = [r.summary for r in recs[:3] if r.summary]
        subject = self._machine.whiteboard.subject  # type: ignore[union-attr]
        if subject and subject not in parts:
            parts.append(subject)
        if parts:
            topics_mod.set_summary(self._base(), self._topic_id, " | ".join(parts)[:200])

    def status(self) -> dict[str, Any]:
        with self._lock:
            assert self._machine is not None
            st = self._machine.status()
            st["topic_id"] = self._topic_id
            st["topic_name"] = topics_mod.display_name(self.current_topic())
            st["multi_topic"] = self.multi_topic()
            st["documents"] = len(self.list_documents())
            return st
