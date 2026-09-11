"""The coordinator: ties tape, groups, whiteboard and the LLM layer together.

The ``Machine`` class owns the on-disk state of a project and implements the
conceptual cycle:

    read whiteboard -> dispatch memory agents -> merge annotations ->
    (consolidate if too big) -> main chatbot -> append durable memories ->
    grow tape (new agent if a group is full)
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .agents import run_agents
from .attachments import ingest_attachment
from .config import Config, resolve_path
from .consolidate import consolidate_whiteboard
from .context import (
    ChatContext,
    append_turn,
    consolidate_context,
    load_context,
    needs_consolidation,
    save_context,
)
from .groups import Manifest, add_memory, load_manifest, save_manifest
from .llm import LLMClient, LLMError
from .main_chatbot import memory_from_spec, run_main_chatbot
from .metacognition import update_metacognition
from .retrieval import Embedder
from .router import select_groups, select_groups_llm
from .secrets import SecretError
from .sessions import save_session_meta, search_sessions, sessions_dir_for
from .tape import MemoryRecord, Tape
from .whiteboard import (
    load_whiteboard,
    merge_annotations,
    needs_consolidation as whiteboard_needs_consolidation,
    save_whiteboard,
    size_chars,
    Whiteboard,
)

_TRIVIAL_MESSAGES = {
    "ok", "okay", "thanks", "thank you", "hi", "hello", "oi", "obrigado",
    "valeu", "yes", "no", "sim", "não", "nao", "blz", "beleza", "certo",
}


def _is_trivial(question: str) -> bool:
    q = (question or "").strip().lower()
    return len(q) < 4 or q in _TRIVIAL_MESSAGES


ROLLUP_PROMPT = """You are consolidating older project memories into one \
summary. Keep the durable decisions, lessons, conventions and facts; drop \
transient chatter. Be concise (a short paragraph or bullets). Return only the \
summary."""


class Machine:
    def __init__(self, root: Path | str, config: Config | None = None, client: Any = None):
        self.root = Path(root).expanduser().resolve()
        self.config = config or Config.load(self.root)
        self.client = client
        self.tape = Tape(resolve_path(self.root, self.config.tape_path))
        self.manifest_path = resolve_path(self.root, self.config.manifest_path)
        self.whiteboard_path = resolve_path(self.root, self.config.whiteboard_path)
        self.context_path = resolve_path(self.root, self.config.context_path)
        self.manifest: Manifest = load_manifest(self.manifest_path, capacity=self.config.capacity)
        self.whiteboard: Whiteboard = load_whiteboard(self.whiteboard_path)
        self.context: ChatContext = load_context(self.context_path)
        self._recall_count = 0

    def _embedder(self) -> Any:
        if not self.config.embedding_model:
            return None
        key = ""
        if self.config.embedding_api_key_env:
            key = os.environ.get(self.config.embedding_api_key_env, "")
        return Embedder(self.config.embedding_base_url, key, self.config.embedding_model)

    def _select_groups(self, question: str) -> list[Any] | None:
        """Groups to consult, or None to consult all (full sweep)."""
        if not self.config.router_enabled or not self.manifest.groups:
            return None
        self._recall_count += 1
        if (
            self.config.router_full_every
            and self._recall_count % self.config.router_full_every == 0
        ):
            return None
        if self.config.router_mode == "llm":
            selected = select_groups_llm(
                self.tape,
                self.manifest,
                question,
                self.ensure_client_optional(),
                top_k=self.config.router_top_k,
            )
            if selected is not None:
                return selected
        embedder = self._embedder() if self.config.router_mode == "embedding" else None
        return select_groups(
            self.tape,
            self.manifest,
            question,
            top_k=self.config.router_top_k,
            fallback=self.config.router_fallback,
            embedder=embedder,
        )

    def _ensure_client(self) -> Any:
        if self.client is None:
            self.client = LLMClient.from_config(self.config)
        return self.client

    def ensure_client_optional(self) -> Any:
        """Build a client from config/env if possible; returns None otherwise."""
        if self.client is None:
            try:
                self.client = LLMClient.from_config(self.config)
            except LLMError:
                self.client = None
        return self.client

    def save(self) -> None:
        save_manifest(self.manifest, self.manifest_path)
        save_whiteboard(self.whiteboard, self.whiteboard_path)
        save_context(self.context, self.context_path)

    # ------------------------------------------------------------------ state

    def add_memory(self, record: MemoryRecord, *, save: bool = True) -> dict[str, Any]:
        record, group, agent, created = add_memory(
            self.tape, self.manifest, record, model=self.config.model
        )
        if save:
            self.save()
            self._update_session_meta()
        return {
            "ok": True,
            "record": record.to_dict(),
            "group": group.id,
            "agent": agent.id,
            "new_agent": created,
        }

    def set_subject(self, subject: str, objective: str = "", *, save: bool = True) -> dict[str, Any]:
        self.whiteboard.subject = subject
        if objective:
            self.whiteboard.objective = objective
        self.whiteboard.touch()
        if save:
            self.save()
        return {"ok": True, "subject": subject}

    def status(self) -> dict[str, Any]:
        return {
            "root": str(self.root),
            "tape_records": len(self.tape),
            "groups": len(self.manifest.groups),
            "agents": len(self.manifest.agents),
            "capacity": self.manifest.capacity,
            "whiteboard_subject": self.whiteboard.subject,
            "whiteboard_metacognition": self.whiteboard.metacognition,
            "whiteboard_checklist": self.whiteboard.checklist,
            "whiteboard_annotations": len(self.whiteboard.annotations),
            "agents_checklists": [
                {"id": a.id, "checklist": a.checklist}
                for a in self.manifest.agents
                if a.checklist
            ],
            "whiteboard_chars": size_chars(self.whiteboard),
            "consolidate_threshold": self.config.consolidate_threshold,
            "context_turns": len(self.context.turns),
            "context_chars": self.context.total_chars(),
            "context_consolidate_threshold": self.config.context_consolidate_threshold,
        }

    # --------------------------------------------------------------- the cycle

    def run(
        self,
        task: str,
        *,
        temperature: float = 0.0,
        consolidate: bool = True,
        max_workers: int | None = None,
        extra_context: str = "",
        on_token: Any = None,
    ) -> dict[str, Any]:
        client = self._ensure_client()

        if not self.whiteboard.subject:
            self.whiteboard.subject = task[:120]

        selected = self._select_groups(task)
        raw_annotations = run_agents(
            self.tape,
            self.manifest,
            self.whiteboard,
            client,
            groups=selected,
            temperature=temperature,
            max_workers=max_workers,
            include_checklist=not self.config.ablation_no_checklist,
        )
        checklists_updated = [a.id for a in self.manifest.agents if a.checklist]
        kept = merge_annotations(
            self.whiteboard,
            raw_annotations,
            budget=self.config.whiteboard_budget,
        )

        consolidated = False
        if consolidate and whiteboard_needs_consolidation(
            self.whiteboard, self.config.consolidate_threshold
        ):
            consolidate_whiteboard(
                self.whiteboard,
                client=client,
                tape=self.tape,
                manifest=self.manifest,
                model=self.config.model,
                temperature=temperature,
            )
            consolidated = True

        history = self.context.render()
        reply, memories, reasoning = run_main_chatbot(
            client,
            self.whiteboard,
            task,
            history=history,
            extra_context=extra_context,
            temperature=temperature,
            on_token=on_token,
        )

        update_metacognition(
            self.whiteboard,
            client,
            task=task,
            reply=reply,
            temperature=temperature,
        )

        append_turn(self.context, task, reply, subject=self.whiteboard.subject)
        context_consolidated = False
        if needs_consolidation(self.context, self.config.context_consolidate_threshold):
            consolidate_context(self.context, client=client, temperature=temperature)
            context_consolidated = True

        saved: list[dict[str, Any]] = []
        new_agents = 0
        skipped_secrets = 0

        for rec in memories:
            try:
                rec, _group, _agent, created = add_memory(
                    self.tape, self.manifest, rec, model=self.config.model
                )
            except SecretError:
                skipped_secrets += 1
                continue
            saved.append(rec.to_dict())
            if created:
                new_agents += 1

        # Memorize almost everything: record the turn itself on the tape (last).
        turn_record = MemoryRecord(
            type="memory",
            summary=task[:300],
            why=reply[:2000],
        )
        last = self.tape.last()
        duplicate = (
            last is not None
            and last.type == "memory"
            and last.summary == turn_record.summary
        )
        if not duplicate:
            try:
                turn_rec, _tg, _ta, turn_created = add_memory(
                    self.tape, self.manifest, turn_record, model=self.config.model
                )
                saved.append(turn_rec.to_dict())
                if turn_created:
                    new_agents += 1
            except SecretError:
                skipped_secrets += 1

        self.save()

        return {
            "ok": True,
            "subject": self.whiteboard.subject,
            "raw_annotations": len(raw_annotations),
            "kept_annotations": [a.to_dict() for a in kept],
            "consolidated": consolidated,
            "context_consolidated": context_consolidated,
            "reply": reply,
            "reasoning": reasoning,
            "memories_saved": saved,
            "skipped_secrets": skipped_secrets,
            "new_agents": new_agents,
            "checklists_updated": checklists_updated,
            "routed_groups": len(selected) if selected is not None else len(self.manifest.groups),
            "total_groups": len(self.manifest.groups),
            "tape_records": len(self.tape),
            "groups": len(self.manifest.groups),
            "agents": len(self.manifest.agents),
            "context_turns": len(self.context.turns),
            "context_chars": self.context.total_chars(),
        }

    def recall(
        self,
        question: str,
        *,
        cross_session: bool = False,
        views: list[str] | None = None,
        temperature: float = 0.0,
        max_workers: int | None = None,
    ) -> dict[str, Any]:
        """Run the memory agents only (no chatbot) and return the whiteboard.

        Deterministic recall: the agents read the whiteboard, refine their
        checklists and annotate the memories relevant to the current question.

        Optimizations: an identical subject is served from cache, and trivial
        messages reuse the previous recall — both skip the LLM agents. When
        ``cross_session`` is set, relevant memories from *other* sessions are
        searched (BM25) and returned as ``past_hits``.
        """
        trivial = _is_trivial(question)
        cache = self._load_recall_cache()

        if cache and (cache.get("subject") == question or trivial):
            result = dict(cache.get("result") or {})
            result["cached"] = True
            if not trivial:
                self.whiteboard.subject = question
                self.save()
            if cross_session:
                result["past_hits"] = self._cross_session_hits(question)
            return result

        client = self._ensure_client()
        self.whiteboard.subject = question

        selected = self._select_groups(question)
        raw_annotations = run_agents(
            self.tape,
            self.manifest,
            self.whiteboard,
            client,
            groups=selected,
            views_filter=set(views) if views else None,
            temperature=temperature,
            max_workers=max_workers,
            include_checklist=not self.config.ablation_no_checklist,
        )
        kept = merge_annotations(
            self.whiteboard,
            raw_annotations,
            budget=self.config.whiteboard_budget,
        )

        consolidated = False
        if whiteboard_needs_consolidation(
            self.whiteboard, self.config.consolidate_threshold
        ):
            consolidate_whiteboard(
                self.whiteboard,
                client=client,
                tape=self.tape,
                manifest=self.manifest,
                model=self.config.model,
                temperature=temperature,
            )
            consolidated = True

        self.save()
        result: dict[str, Any] = {
            "ok": True,
            "subject": self.whiteboard.subject,
            "understanding": self.whiteboard.metacognition,
            "checklist": self.whiteboard.checklist,
            "annotations": [a.to_dict() for a in kept],
            "attached_content": self._attached_content(kept),
            "rehydrated": self._rehydrated(kept),
            "agents_checklists": [
                {"id": a.id, "checklist": a.checklist}
                for a in self.manifest.agents
                if a.checklist
            ],
            "consolidated": consolidated,
            "views": views or [],
            "routed_groups": len(selected) if selected is not None else len(self.manifest.groups),
            "total_groups": len(self.manifest.groups),
            "tape_records": len(self.tape),
            "agents": len(self.manifest.agents),
            "render": self.whiteboard.render(),
            "cached": False,
        }
        self._save_recall_cache(question, result)
        if cross_session:
            result["past_hits"] = self._cross_session_hits(question)
        return result

    # ---------------------------------------------------------- recall cache

    def _recall_cache_path(self) -> Path:
        return self.root / "recall_cache.json"

    def _load_recall_cache(self) -> dict[str, Any] | None:
        path = self._recall_cache_path()
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else None
        except (json.JSONDecodeError, OSError):
            return None

    def _save_recall_cache(self, question: str, result: dict[str, Any]) -> None:
        try:
            self._recall_cache_path().write_text(
                json.dumps({"subject": question, "result": result}, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError:
            pass

    def _invalidate_recall_cache(self) -> None:
        try:
            self._recall_cache_path().unlink(missing_ok=True)
        except OSError:
            pass

    def _rehydrated(self, kept: list[Any], *, budget: int = 2000) -> list[dict[str, Any]]:
        """Source summaries behind annotated rollups, so originals stay reachable."""
        if not kept:
            return []
        by_id = {r.id: r for r in self.tape.read()}
        out: list[dict[str, Any]] = []
        used = 0
        for a in kept:
            r = by_id.get(a.memory_id)
            if r is None or not r.derived_from:
                continue
            sources = [by_id[s].summary for s in r.derived_from if s in by_id]
            if not sources:
                continue
            cost = sum(len(s) for s in sources) + 40
            if out and used + cost > budget:
                break
            out.append({"memory_id": r.id, "sources": sources[:20]})
            used += cost
        return out

    def _attached_content(self, kept: list[Any], *, budget: int = 2000) -> list[dict[str, Any]]:
        """Full text of annotated attachment chunks, so the chatbot can read them."""
        if not kept:
            return []
        by_id = {r.id: r for r in self.tape.read()}
        out: list[dict[str, Any]] = []
        used = 0
        for a in kept:
            r = by_id.get(a.memory_id)
            if r is None or r.type != "attachment":
                continue
            cost = len(r.why) + 40
            if out and used + cost > budget:
                break
            out.append({"memory_id": r.id, "source": r.source, "text": r.why[:1200]})
            used += cost
        return out

    def _cross_session_hits(self, question: str) -> list[dict[str, Any]]:
        sdir = sessions_dir_for(self.root)
        if sdir is None:
            return []
        return search_sessions(sdir, question, exclude_id=self.root.name, limit=5)

    def _update_session_meta(self) -> None:
        if sessions_dir_for(self.root) is None:
            return
        summary = self.whiteboard.metacognition or self.whiteboard.subject
        if not summary:
            summary = "; ".join(r.summary for r in self.tape.read()[:3] if r.summary)
        try:
            save_session_meta(self.root, session_id=self.root.name, summary=summary)
        except OSError:
            pass

    def checkpoint(
        self,
        question: str,
        summary: str,
        *,
        memories: list[dict[str, Any]] | None = None,
        temperature: float = 0.0,
    ) -> dict[str, Any]:
        """Record a turn back to memory after the assistant has answered.

        Appends the turn record + durable memories to the tape and refreshes
        the chatbot's metacognition and checklist from the exchange.
        """
        client = self._ensure_client()
        saved: list[dict[str, Any]] = []
        new_agents = 0
        skipped_secrets = 0

        def _append(rec: MemoryRecord) -> None:
            nonlocal new_agents, skipped_secrets
            try:
                rec, _g, _a, created = add_memory(
                    self.tape, self.manifest, rec, model=self.config.model
                )
                saved.append(rec.to_dict())
                if created:
                    new_agents += 1
            except SecretError:
                skipped_secrets += 1

        for spec in memories or []:
            rec = memory_from_spec(spec)
            if rec is not None:
                _append(rec)

        turn_record = MemoryRecord(
            type="memory",
            summary=question[:300],
            why=summary[:2000],
        )
        last = self.tape.last()
        duplicate = (
            last is not None
            and last.type == "memory"
            and last.summary == turn_record.summary
        )
        if not duplicate:
            _append(turn_record)

        update_metacognition(
            self.whiteboard,
            client,
            task=question,
            reply=summary,
            temperature=temperature,
        )
        append_turn(self.context, question, summary, subject=self.whiteboard.subject)
        if needs_consolidation(self.context, self.config.context_consolidate_threshold):
            consolidate_context(self.context, client=client, temperature=temperature)

        self.save()
        self._update_session_meta()
        return {
            "ok": True,
            "memories_saved": saved,
            "skipped_secrets": skipped_secrets,
            "new_agents": new_agents,
            "tape_records": len(self.tape),
            "agents": len(self.manifest.agents),
            "understanding": self.whiteboard.metacognition,
            "checklist": self.whiteboard.checklist,
        }

    def list_records(self) -> list[dict[str, Any]]:
        return [r.to_dict() for r in self.tape.read()]

    def attach(self, path: str | Path, *, chunk_size: int | None = None) -> dict[str, Any]:
        """Ingest an attached .txt file into the tape as labeled chunk memories."""
        result = ingest_attachment(
            self.tape,
            self.manifest,
            path,
            chunk_size=chunk_size or self.config.attach_chunk_size,
            model=self.config.model,
        )
        if result.get("ok"):
            self.save()
            self._update_session_meta()
            self._invalidate_recall_cache()
        return result

    def rollup(self, *, keep_recent: int = 20, temperature: float = 0.0) -> dict[str, Any]:
        """Consolidate older active records into one rollup memory.

        The oldest records (all but the ``keep_recent`` newest) are summarized
        into a single ``memory`` record and the sources are archived, so the
        tape stays bounded without losing the essentials.
        """
        records = [r for r in self.tape.read() if r.status == "active"]
        if len(records) <= keep_recent:
            return {"ok": True, "rolled": 0, "reason": "nothing to roll up"}

        old = records[:-keep_recent]
        body = "\n".join(f"- [{r.type}] {r.summary}" for r in old)

        client = self.ensure_client_optional()
        summary = ""
        if client is not None:
            try:
                summary = client.complete(
                    [
                        {"role": "system", "content": ROLLUP_PROMPT},
                        {"role": "user", "content": body},
                    ],
                    temperature=temperature,
                ).strip()
            except Exception:
                summary = ""
        if not summary:
            summary = f"Rollup of {len(old)} older memories: " + "; ".join(
                r.summary for r in old[:10]
            )

        roll_rec = MemoryRecord(
            type="memory",
            summary=summary[:1500],
            why=body[:4000],
            derived_from=[r.id for r in old],
        )
        rec, _g, _a, _created = add_memory(
            self.tape, self.manifest, roll_rec, model=self.config.model
        )
        self.tape.set_status_many([r.id for r in old], "archived")
        self.save()
        self._invalidate_recall_cache()
        return {
            "ok": True,
            "rolled": len(old),
            "rollup_id": rec.id,
            "kept": len(records) - len(old),
            "archived": [r.id for r in old],
        }

    def rehydrate(self, memory_id: str, *, reactivate: bool = False) -> dict[str, Any]:
        """Recover the original memories behind a rollup/consolidation record.

        Archived sources stay on the tape but are invisible to the agents; this
        makes them reachable again (and optionally active) so provenance is not
        a dead end.
        """
        records = {r.id: r for r in self.tape.read()}
        rec = records.get(memory_id)
        if rec is None:
            return {"ok": False, "error": f"{memory_id} not found"}
        if not rec.derived_from:
            return {"ok": False, "error": f"{memory_id} has no derived_from sources"}

        sources = [records[s].to_dict() for s in rec.derived_from if s in records]
        if reactivate:
            self.tape.set_status_many(rec.derived_from, "active")
            self.save()
            self._invalidate_recall_cache()
        return {
            "ok": True,
            "memory_id": memory_id,
            "sources": sources,
            "reactivated": reactivate,
        }

    def consolidate(self, *, temperature: float = 0.0, use_llm: bool = False) -> dict[str, Any]:
        client = self.ensure_client_optional() if use_llm else self.client
        result = consolidate_whiteboard(
            self.whiteboard,
            client=client,
            tape=self.tape,
            manifest=self.manifest,
            model=self.config.model,
            temperature=temperature,
        )
        self.save()
        return result
