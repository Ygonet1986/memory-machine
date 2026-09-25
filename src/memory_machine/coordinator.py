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

from .agents import RecallRun, run_agents, run_view_agents
from .attention import confidence, contribution_summary, decay_reinforce, is_anaphoric
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
from .context import split_answerer_budget
from .main_chatbot import (memory_from_spec, observer_pass,
                           run_main_chatbot)
from .metacognition import update_metacognition
from .payload import build_evidence_payload, payload_as_context, payload_chars
from . import admission_shadow
from .retrieval import Embedder
from .router import select_groups, select_groups_llm
from .routing import (
    DIMENSIONS,
    RoutingPlan,
    coverage_signal,
    dimension_of,
    ids_for_plan,
    judge_coverage,
    select_plan_lexical,
    select_plan_llm,
    view_coverage_signal,
)
from .secrets import SecretError
from .sessions import save_session_meta, search_sessions, sessions_dir_for
from .tape import MemoryRecord, Tape, parse_id
from .views import build_index, ids_in_views, rank_views, related_views, select_views_llm
from .whiteboard import (
    Annotation,
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

    def _select_similarity(self, question: str, mode: str | None = None) -> list[Any] | None:
        """Similarity router: LLM first, then lexical/embedding; None = full."""
        mode = mode or self.config.router_mode
        if mode in {"views", "cascade"}:
            mode = "llm"
        if mode == "llm":
            selected = select_groups_llm(
                self.tape,
                self.manifest,
                question,
                self.ensure_client_optional(),
                top_k=self.config.router_top_k,
            )
            if selected is not None:
                return selected
        embedder = self._embedder() if mode == "embedding" else None
        return select_groups(
            self.tape,
            self.manifest,
            question,
            top_k=self.config.router_top_k,
            fallback=self.config.router_fallback,
            embedder=embedder,
        )

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
        return self._select_similarity(question)

    def _select_views(self, question: str) -> tuple[list[str], float]:
        """Legacy (v0.5a) view selection: flat BM25 or contextual LLM."""
        cfg = self.config
        if cfg.view_router_mode == "llm":
            result = select_views_llm(
                self.tape,
                question,
                self.ensure_client_optional(),
                whiteboard=self.whiteboard,
                top_k=cfg.view_top_k,
            )
            if result is not None:
                return result
        hits = rank_views(self.tape, question, limit=cfg.view_top_k)
        if not hits:
            return [], 0.0
        return [v for v, _score in hits], hits[0][1]

    def _attention_gate(self, question: str) -> RoutingPlan | None:
        """Reuse the active attention for an anaphoric follow-up (no router call).

        Fires only when the attention is concentrated (top1 and margin above the
        gate) and the message is anaphoric — a fresh session with residual noise
        must not hijack the routing.
        """
        cfg = self.config
        top1, margin = confidence(self.whiteboard.attention)
        if top1 < cfg.attention_gate_min or margin < cfg.attention_gate_margin:
            return None
        index = build_index(self.tape)
        if not is_anaphoric(question, view_names=list(index)):
            return None
        ranked = sorted(
            ((v, w) for v, w in self.whiteboard.attention.items() if w > 0 and v in index),
            key=lambda x: -x[1],
        )[: cfg.view_top_k]
        if not ranked:
            return None
        by_dim: dict[str, list[str]] = {}
        for view, _w in ranked:
            dim = dimension_of(view)
            if dim:
                by_dim.setdefault(dim, []).append(view)
        plan = RoutingPlan(
            mode="views",
            dimensions=[d for d in DIMENSIONS if by_dim.get(d)],
            dimension_sources={d: "attention" for d in by_dim},
            views_by_dimension=by_dim,
            candidate_views=[v for v, _w in ranked],
            combination="union",
            intersection_mode="union",
        )
        plan.anaphoric = True
        plan.attention_gate = "reused"
        plan.view_scores = {
            view: {
                "router": 0.0,
                "attention": round(weight, 4),
                "attention_weighted": round(weight * cfg.attention_weight, 4),
                "final": round(weight * cfg.attention_weight, 4),
                "contribution": "attention",
            }
            for view, weight in ranked
        }
        return plan

    def _plan_routing(self, question: str) -> RoutingPlan | None:
        """Build the structural access plan (dimension-aware or legacy)."""
        cfg = self.config
        if cfg.view_dimension_mode == "auto":
            if cfg.attention_mode == "state":
                gated = self._attention_gate(question)
                if gated is not None:
                    return gated
            if cfg.view_router_mode == "llm":
                plan = select_plan_llm(
                    self.tape,
                    question,
                    self.ensure_client_optional(),
                    whiteboard=self.whiteboard,
                    attention=(
                        self.whiteboard.attention
                        if cfg.attention_mode in {"context", "state"}
                        else None
                    ),
                    top_k=cfg.view_top_k,
                )
                if plan is not None and plan.selected_views:
                    plan.attention_gate = "routed"
                    return plan
            plan = select_plan_lexical(
                self.tape,
                question,
                view_top_k=cfg.view_top_k,
                attention=(
                    self.whiteboard.attention
                    if cfg.attention_mode in {"prior", "state"}
                    else None
                ),
                attention_weight=cfg.attention_weight,
            )
            if plan is not None:
                plan.attention_gate = "routed"
            return plan if plan.selected_views else None

        views, score = self._select_views(question)
        if not views:
            return None
        candidates = list(views)
        selected = list(views)
        if self.config.view_prune == "subject" and any(
            v.startswith("topic/") for v in views
        ):
            # Specific beats broad: drop subject views when a topic view matched,
            # keeping them as candidates so coverage can expand back to them.
            selected = [v for v in views if not v.startswith("subject/")]
        by_dim: dict[str, list[str]] = {}
        for view in selected:
            dim = dimension_of(view)
            if dim:
                by_dim.setdefault(dim, []).append(view)
        dims = [d for d in DIMENSIONS if by_dim.get(d)]
        return RoutingPlan(
            mode="views",
            dimensions=dims,
            dimension_sources={d: "legacy" for d in dims},
            views_by_dimension=by_dim,
            candidate_views=candidates,
            combination="union",
            intersection_mode="union",
            score=score,
        )

    def _plan_ids(self, plan: RoutingPlan) -> tuple[set[str], str]:
        if self.config.view_dimension_mode == "auto":
            return ids_for_plan(self.tape, plan)
        return ids_in_views(self.tape, plan.selected_views), "union"

    def _active_ids(self) -> set[str]:
        return {r.id for r in self.tape.read() if r.status == "active" and r.id}

    def _consulted_ids(self, groups: list[Any] | None) -> set[str]:
        """Active records the agents would see for the given groups (None = all)."""
        active = [r for r in self.tape.read() if r.status == "active" and r.id]
        if groups is None:
            return {r.id for r in active}
        ids: set[str] = set()
        for r in active:
            try:
                num = parse_id(r.id)
            except ValueError:
                continue
            if any(g.contains(num) for g in groups):
                ids.add(r.id)
        return ids

    def _groups_consulted(self, consulted: set[str]) -> int:
        groups: set[str] = set()
        for i in consulted:
            try:
                num = parse_id(i)
            except ValueError:
                continue
            g = self.manifest.group_for_id(num)
            if g is not None:
                groups.add(g.id)
        return len(groups)

    def _fill_plan(
        self,
        plan: RoutingPlan,
        level: int,
        consulted: set[str],
        total: int,
        level1: int,
        reasons: list[str] | None = None,
    ) -> None:
        plan.level = level
        merged = set(consulted) | set(plan.consulted_ids)
        plan.consulted_ids = sorted(merged)
        if level == 1:
            plan.level1_ids = sorted(consulted)
        plan.records_consulted = len(merged)
        plan.records_total = total
        plan.records_level1 = level1 or len(consulted)
        plan.groups_consulted = self._groups_consulted(consulted)
        if reasons is not None:
            plan.fallback_reasons = list(reasons)

    def _run_level(
        self,
        client: Any,
        *,
        ids: set[str] | None = None,
        views: list[str] | None = None,
        groups: list[Any] | None = None,
        temperature: float,
        max_workers: int | None,
        include_checklist: bool,
    ) -> RecallRun:
        return run_agents(
            self.tape,
            self.manifest,
            self.whiteboard,
            client,
            groups=groups,
            views_filter=set(views) if views else None,
            ids_filter=ids,
            temperature=temperature,
            max_workers=max_workers,
            include_checklist=include_checklist,
            history=self._agent_history(),
        )

    def _agent_history(self) -> str:
        """Opt-in conversation window for the agents (off by default)."""
        limit = int(getattr(self.config, "agent_history_messages", 0) or 0)
        if limit <= 0:
            return ""
        from .turns import render_recent_turns

        return render_recent_turns(self.tape, limit)

    def _merge_by_dimension(self, run: RecallRun) -> list[Any]:
        """Merge annotations into the board of the dimension that produced them.

        View agents carry ``view:<name>`` as agent id, so each dimension keeps
        its own working memory; the primary board receives the union for
        backward compatibility.
        """
        groups: dict[str, list[Any]] = {}
        for annotation in run.annotations:
            agent_id = annotation.agent_id or ""
            view = agent_id.split(":", 1)[1] if agent_id.startswith("view:") else ""
            dimension = (dimension_of(view) if view else None) or "semantic"
            groups.setdefault(dimension, []).append(annotation)
        kept: list[Any] = []
        for dimension, group_annotations in groups.items():
            board = self.whiteboard.for_dimension(dimension)
            kept.extend(
                merge_annotations(board, group_annotations,
                                  budget=self.config.whiteboard_budget)
            )
        self.whiteboard.annotations = kept
        return kept

    def _evidence_payload(self, kept: list[Any]) -> list[dict[str, Any]]:
        """Recall-local evidence payload for the kept annotations (v0.9)."""
        if not kept or self.config.evidence_payload == "off":
            return []
        records = {r.id: r for r in self.tape.read()}
        budgeted = self.config.evidence_payload == "budgeted"
        return build_evidence_payload(
            records,
            kept,
            budget=self.config.evidence_payload_budget if budgeted else 0,
            min_item_chars=self.config.evidence_payload_min_item if budgeted else 0,
            question=self.whiteboard.subject,
            window=self.config.evidence_payload_window,
        )

    def _update_attention(self, plan: RoutingPlan, run: RecallRun) -> None:
        """Decay by neglect, reinforce selected views and those that found evidence.

        Views whose view agent annotated a memory get the extra found boost.
        With no view plan (group/similarity modes) attention only decays.
        """
        found = {
            annotation.agent_id.split(":", 1)[1]
            for annotation in run.annotations
            if annotation.agent_id.startswith("view:")
        }
        found_boost = self.config.attention_found_boost
        signal = plan.level1_coverage_signal
        if self.config.coverage_mode != "off" and signal:
            # complete + evidence reinforces; partial keeps a smaller boost;
            # uncertain does not reinforce.
            if signal == "partial":
                found_boost *= 0.5
            elif signal == "uncertain":
                found_boost = 0.0
        before = dict(self.whiteboard.attention)
        plan.attention_before = before
        self.whiteboard.attention = decay_reinforce(
            before,
            plan.selected_views,
            found,
            decay=self.config.attention_decay,
            boost=self.config.attention_boost,
            found_boost=found_boost,
        )
        plan.attention_after = dict(self.whiteboard.attention)

    def _consolidate_dimension_boards(self, client: Any, temperature: float) -> bool:
        """Consolidate each dimension board independently when it grows too big.

        The board's working state is persisted to the tape first (lossless
        continuity), then shrunk; other boards are untouched.
        """
        consolidated = False
        for board in self.whiteboard.boards.values():
            if size_chars(board) <= self.config.consolidate_threshold:
                continue
            consolidate_whiteboard(
                board,
                client=client,
                tape=self.tape,
                manifest=self.manifest,
                model=self.config.model,
                temperature=temperature,
            )
            consolidated = True
        return consolidated

    @staticmethod
    def _merge_runs(first: RecallRun, second: RecallRun) -> RecallRun:
        return RecallRun(
            annotations=first.annotations + second.annotations,
            coverage=first.coverage + second.coverage,
        )

    def _coverage_of(
        self, plan: RoutingPlan, run: RecallRun, question: str, client: Any
    ) -> tuple[str, list[str]]:
        mode = self.config.coverage_mode
        if mode == "off":
            return "", []
        annotated = {a.memory_id for a in run.annotations}
        if mode == "judge":
            return judge_coverage(
                question, run.annotations, client, whiteboard=self.whiteboard
            )
        if mode == "judge_views":
            return judge_coverage(
                question,
                run.annotations,
                client,
                whiteboard=self.whiteboard,
                plan=plan,
                tape=self.tape,
                manifest=self.manifest,
            )
        if mode == "structural":
            return coverage_signal(plan, annotated, [], self.tape)
        if mode == "agents":
            return coverage_signal(plan, annotated, run.coverage, self.tape, structural=False)
        if mode == "views":
            return view_coverage_signal(plan, annotated, self.tape)
        return coverage_signal(plan, annotated, run.coverage, self.tape)

    def _needs_fallback(
        self, plan: RoutingPlan, run: RecallRun, question: str, client: Any
    ) -> tuple[bool, str]:
        signal, missing = self._coverage_of(plan, run, question, client)
        if self.config.coverage_mode != "off":
            plan.coverage_signal = signal
            plan.coverage_missing = list(missing)
            if not plan.level1_coverage_signal:
                plan.level1_coverage_signal = signal
                plan.level1_coverage_missing = list(missing)
            plan.coverage = [
                {"agent_id": c.agent_id, "coverage": c.coverage, "missing": list(c.missing)}
                for c in run.coverage
            ]
            if signal != "complete":
                return True, f"coverage_{signal}"
            return False, ""
        low = bool(plan.score is not None and plan.score < self.config.cascade_min_score)
        no_ann = not run.annotations
        if not (low or no_ann):
            return False, ""
        if no_ann and low:
            return True, "both"
        return True, "no_annotation" if no_ann else "low_view_score"

    def _resolved(
        self, plan: RoutingPlan, run: RecallRun, question: str, client: Any
    ) -> bool:
        if self.config.coverage_mode != "off":
            signal, missing = self._coverage_of(plan, run, question, client)
            plan.coverage_signal = signal
            plan.coverage_missing = list(missing)
            return signal == "complete"
        return bool(run.annotations)

    def _expand_plan(
        self, plan: RoutingPlan, missing_views: list[str] | None = None
    ) -> RoutingPlan | None:
        """Expand to the detected gaps first, then to co-occurring views.

        Gap strings from a judge are matched back to candidate views (by view
        name or its suffix) before falling back to co-occurrence.
        """
        missing = list(missing_views or [])
        new_views = [
            v
            for v in missing
            if v not in plan.selected_views and dimension_of(v) is not None
        ]
        if not new_views and missing:
            lowered = [m.lower() for m in missing]
            for view in plan.candidate_views:
                if view in plan.selected_views:
                    continue
                name = view.split("/", 1)[-1].lower()
                if any(view.lower() in m or name in m for m in lowered):
                    new_views.append(view)
        if not new_views:
            related = related_views(
                self.tape, plan.selected_views, top_k=self.config.cascade_expand_top_k
            )
            new_views = [v for v in related if v not in plan.selected_views]
        if not new_views:
            return None
        expanded = RoutingPlan(
            mode=plan.mode,
            dimensions=list(plan.dimensions),
            dimension_sources=dict(plan.dimension_sources),
            views_by_dimension={k: list(v) for k, v in plan.views_by_dimension.items()},
            candidate_views=list(plan.candidate_views),
            candidate_scores=dict(plan.candidate_scores),
            combination=plan.combination,
            confidence=plan.confidence,
            score=plan.score,
        )
        expanded.level1_coverage_signal = plan.level1_coverage_signal
        expanded.level1_coverage_missing = list(plan.level1_coverage_missing)
        for view in new_views:
            dim = dimension_of(view)
            if dim:
                expanded.views_by_dimension.setdefault(dim, []).append(view)
                if dim not in expanded.dimensions:
                    expanded.dimensions.append(dim)
        return expanded

    def _run_view_routed(
        self,
        question: str,
        client: Any,
        *,
        temperature: float,
        max_workers: int | None,
        include_checklist: bool,
        total: int,
    ) -> tuple[RecallRun, RoutingPlan]:
        """Dimension-aware view routing with a coverage-driven cascade.

        Level 1 builds a structural plan (dimensions -> views -> intersection).
        In cascade mode, a coverage signal that is not ``complete`` expands to
        co-occurring views (2), then the similarity router (3), then a full
        sweep (4). Fallback reasons are recorded so failures can be attributed
        to the router, the topology or the coverage signal.
        """
        cfg = self.config
        cascade = cfg.router_mode == "cascade"
        reasons: list[str] = []
        plan = self._plan_routing(question)
        if plan is None:
            reasons.append("no_view_selected")
            plan = RoutingPlan(mode="cascade" if cascade else "views", fallback_reasons=reasons)
            if not cascade:
                consulted = self._active_ids()
                run = self._run_level(
                    client, groups=None, temperature=temperature,
                    max_workers=max_workers, include_checklist=include_checklist,
                )
                self._fill_plan(plan, 0, consulted, total, 0, reasons)
                return run, plan
            return self._cascade_fallback(
                question, client, plan, reasons, temperature, max_workers,
                include_checklist, total,
            )

        if cfg.agent_mode == "view":
            ids = ids_in_views(self.tape, plan.selected_views)
            plan.intersection_mode = "views"
            plan.intersection_size = len(ids)
            level1 = len(ids)
            run = run_view_agents(
                self.tape, self.manifest, self.whiteboard, client,
                views=plan.selected_views,
                per_dimension=cfg.whiteboard_mode == "dimension",
                temperature=temperature, max_workers=max_workers,
                history=self._agent_history(),
            )
        else:
            ids, mode = self._plan_ids(plan)
            plan.intersection_mode = mode
            plan.intersection_size = len(ids)
            level1 = len(ids)
            run = self._run_level(
                client, ids=ids, temperature=temperature,
                max_workers=max_workers, include_checklist=include_checklist,
            )
        self._fill_plan(plan, 1, ids, total, level1, reasons)
        if not cascade:
            if cfg.coverage_mode != "off":
                signal, missing = self._coverage_of(plan, run, question, client)
                plan.coverage_signal = signal
                plan.coverage_missing = list(missing)
                plan.level1_coverage_signal = signal
                plan.level1_coverage_missing = list(missing)
                plan.coverage = [
                    {"agent_id": c.agent_id, "coverage": c.coverage, "missing": list(c.missing)}
                    for c in run.coverage
                ]
            return run, plan

        fallback, reason = self._needs_fallback(plan, run, question, client)
        if not fallback:
            return run, plan
        reasons.append(reason)

        expanded = self._expand_plan(plan, plan.coverage_missing)
        if expanded is not None:
            if cfg.agent_mode == "view":
                ids2 = ids_in_views(self.tape, expanded.selected_views)
                expanded.intersection_mode = "views"
                expanded.intersection_size = len(ids2)
                new = run_view_agents(
                    self.tape, self.manifest, self.whiteboard, client,
                    views=expanded.selected_views,
                    per_dimension=cfg.whiteboard_mode == "dimension",
                    temperature=temperature, max_workers=max_workers,
                    history=self._agent_history(),
                )
            else:
                ids2, mode2 = self._plan_ids(expanded)
                expanded.intersection_mode = mode2
                expanded.intersection_size = len(ids2)
                new = self._run_level(
                    client, ids=ids2, temperature=temperature,
                    max_workers=max_workers, include_checklist=include_checklist,
                )
            run = self._merge_runs(run, new)
            if self._resolved(expanded, new, question, client):
                self._fill_plan(expanded, 2, ids2, total, level1, reasons)
                return run, expanded
        reasons.append("expansion_failed")
        return self._cascade_fallback(
            question, client, plan, reasons, temperature, max_workers,
            include_checklist, total, level1=level1, run=run,
        )

    def _cascade_fallback(
        self,
        question: str,
        client: Any,
        plan: RoutingPlan,
        reasons: list[str],
        temperature: float,
        max_workers: int | None,
        include_checklist: bool,
        total: int,
        *,
        level1: int = 0,
        run: RecallRun | None = None,
    ) -> tuple[RecallRun, RoutingPlan]:
        run = run or RecallRun()
        groups = self._select_similarity(question, mode="llm")
        new = self._run_level(
            client, groups=groups, temperature=temperature,
            max_workers=max_workers, include_checklist=include_checklist,
        )
        run = self._merge_runs(run, new)
        if new.annotations:
            plan.level = 3
            self._fill_plan(plan, 3, self._consulted_ids(groups), total, level1, reasons)
            return run, plan
        reasons.append("similarity_failed")
        full = self._run_level(
            client, groups=None, temperature=temperature,
            max_workers=max_workers, include_checklist=include_checklist,
        )
        run = self._merge_runs(run, full)
        self._fill_plan(plan, 4, self._active_ids(), total, level1, reasons)
        return run, plan

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
        self._graph_after_append(record)
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

    def add_turn_slot(
        self,
        slot: str,
        text: str,
        *,
        message_id: str = "",
        pair_message_id: str = "",
        save: bool = True,
    ) -> dict[str, Any]:
        """Append one turn slot (``question``/``reply``) - see turns.py.

        Opt-in only: the opencode plugin calls this behind
        ``MEMORY_MACHINE_TURN_SLOTS=1`` (off by default). The question/reply
        types are not graph-eligible, so no projection runs for them.
        """
        from .turns import add_turn_slot as _add_turn_slot

        result = _add_turn_slot(
            self.tape, self.manifest, slot=slot, text=text,
            message_id=message_id, pair_message_id=pair_message_id,
            model=self.config.model,
        )
        if save and result.get("ok") and not result.get("deduped"):
            self.save()
            self._update_session_meta()
        return result

    def _graph_eligible(self, record: MemoryRecord) -> bool:
        if not self.config.graph_enabled or record.derived_from:
            return False
        from .graph import parse_types

        return record.type in parse_types(self.config.graph_extract_types)

    def _graph_pipeline(self) -> tuple[Any, Any, Any]:
        """Build (store, extractor, resolver) for the current project."""
        from .graph import GraphStore
        from .graph_extract import GraphExtractor
        from .graph_resolve import GraphResolver

        store = GraphStore(resolve_path(self.root, self.config.graph_path))
        extractor = GraphExtractor(self._ensure_client())
        resolver = GraphResolver(
            embedder=self._embedder(),
            auto=self.config.graph_confidence_auto,
            hypothesis=self.config.graph_confidence_hypothesis,
            max_candidates=self.config.graph_resolver_candidates,
        )
        return store, extractor, resolver

    def _graph_after_append(self, record: MemoryRecord) -> None:
        """Project a freshly appended durable memory into the graph (F2/F4).

        Runs strictly after the tape append: failures follow the pending/failed
        policy and never propagate, so the tape is never rolled back. With
        ``graph_enabled=false`` this is a no-op and the old path is untouched.
        """
        self._graph_after_appends([record])

    def _graph_after_appends(self, records: list[MemoryRecord]) -> None:
        """Project one or more freshly appended records (batched transport).

        Each record keeps its own idempotency unit; batching only groups the
        LLM calls. Any failure is recorded in the projection and never
        propagates to the caller.
        """
        eligible = [record for record in records if self._graph_eligible(record)]
        if not eligible:
            return
        from .graph import apply_batch_extraction, apply_record_extraction

        store = None
        try:
            store, extractor, resolver = self._graph_pipeline()
            if len(eligible) == 1:
                apply_record_extraction(
                    store,
                    eligible[0],
                    extractor.extract,
                    tag=extractor.tag,
                    extractor_name=extractor.name,
                    extractor_version=extractor.version,
                    resolver=resolver,
                    max_attempts=self.config.graph_max_attempts,
                )
                return
            apply_batch_extraction(
                store,
                eligible,
                extractor.extract_batch,
                tag=extractor.tag,
                extractor_name=extractor.name,
                extractor_version=extractor.version,
                resolver=resolver,
                max_attempts=self.config.graph_max_attempts,
            )
        except Exception as exc:
            # The tape is already committed; surface the projection failure if
            # possible and never propagate it to the caller.
            try:
                if store is not None:
                    for record in eligible:
                        store.mark_failed(
                            record.id, f"projection error: {exc}", extractor="graph"
                        )
            except Exception:
                pass

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
        ).annotations
        checklists_updated = [a.id for a in self.manifest.agents if a.checklist]
        kept = merge_annotations(
            self.whiteboard,
            raw_annotations,
            budget=self.config.whiteboard_budget,
        )
        payload = self._evidence_payload(kept)
        if payload:
            evidence = payload_as_context(payload)
            extra_context = (extra_context + "\n\n" + evidence).strip()

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

        history = self.context.render_recent(
            int(getattr(self.config, "answerer_history_messages", 10) or 0))
        _, board_budget = split_answerer_budget(
            self.config.whiteboard_budget, len(history))
        guidance_text = ""
        if bool(getattr(self.config, "answerer_observer", True)):
            understanding, guidance = observer_pass(
                client, self.whiteboard, history, task,
                self.context.understanding, temperature=temperature)
            if understanding:
                self.context.understanding = understanding
            guidance_text = "\n".join(f"- {item}" for item in guidance)
        reply, memories, reasoning = run_main_chatbot(
            client,
            self.whiteboard,
            task,
            history=history,
            extra_context=extra_context,
            temperature=temperature,
            on_token=on_token,
            whiteboard_budget=board_budget,
            observer_guidance=guidance_text,
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
        projected: list[MemoryRecord] = []

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
            projected.append(rec)
        self._graph_after_appends(projected)

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
            "evidence_payload_chars": payload_chars(payload),
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

    def _dispatch_agents(
        self,
        question: str,
        client: Any,
        *,
        views: list[str] | None = None,
        temperature: float = 0.0,
        max_workers: int | None = None,
    ) -> tuple[RecallRun, RoutingPlan]:
        """Run the agents under the configured routing and report how it went."""
        cfg = self.config
        include_checklist = not cfg.ablation_no_checklist
        total = len(self._active_ids())

        if views:
            selected = list(views)
            consulted = ids_in_views(self.tape, selected)
            by_dim: dict[str, list[str]] = {}
            for view in selected:
                dim = dimension_of(view)
                if dim:
                    by_dim.setdefault(dim, []).append(view)
            plan = RoutingPlan(
                mode="override",
                dimensions=[d for d in DIMENSIONS if by_dim.get(d)],
                views_by_dimension=by_dim,
                combination="union",
                intersection_mode="union",
            )
            run = self._run_level(
                client, views=selected, temperature=temperature,
                max_workers=max_workers, include_checklist=include_checklist,
            )
            self._fill_plan(plan, 1, consulted, total, len(consulted))
            return run, plan

        if cfg.router_enabled and cfg.router_mode in {"views", "cascade"} and self.manifest.groups:
            return self._run_view_routed(
                question, client, temperature=temperature, max_workers=max_workers,
                include_checklist=include_checklist, total=total,
            )

        selected_groups = self._select_groups(question)
        run = self._run_level(
            client, groups=selected_groups, temperature=temperature,
            max_workers=max_workers, include_checklist=include_checklist,
        )
        consulted = self._consulted_ids(selected_groups)
        plan = RoutingPlan(mode="similarity" if selected_groups is not None else "full")
        self._fill_plan(
            plan, 1 if selected_groups is not None else 0, consulted, total, len(consulted)
        )
        return run, plan

    def recall(
        self,
        question: str,
        *,
        cross_session: bool = False,
        views: list[str] | None = None,
        temperature: float = 0.0,
        max_workers: int | None = None,
        debug: bool = False,
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
            self._record_admission_shadow(
                question, result.get("annotations") or [],
                result.get("evidence_payload") or [], cached=True)
            return result

        client = self._ensure_client()
        self.whiteboard.subject = question

        graph_mode = self._graph_recall_mode()
        graph_result = None
        graph_annotations: list[Annotation] = []
        if graph_mode == "only":
            run = RecallRun()
            plan = RoutingPlan(mode="graph")
            graph_result = self._graph_recall(question)
            graph_annotations = self._graph_annotations(graph_result)
            raw_annotations = graph_annotations
        else:
            run, plan = self._dispatch_agents(
                question, client, views=views, temperature=temperature, max_workers=max_workers
            )
            raw_annotations = run.annotations
            if graph_mode in {"augment", "augment_guarded"}:
                guarded = graph_mode == "augment_guarded"
                graph_result = self._graph_recall(question, guard=guarded)
                graph_annotations = self._graph_annotations(
                    graph_result,
                    weight=self.config.graph_augment_weight if guarded else 1.0,
                )
                raw_annotations = self._union_with_graph(
                    raw_annotations, graph_annotations
                )
        if not debug:
            plan.consulted_ids = []
            plan.level1_ids = []
        if self.config.whiteboard_mode == "dimension":
            kept = self._merge_by_dimension(run)
        else:
            kept = merge_annotations(
                self.whiteboard,
                raw_annotations,
                budget=self.config.whiteboard_budget,
            )
        if self.config.attention_mode != "off":
            self._update_attention(plan, run)
        payload = self._evidence_payload(kept)

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
        if self.config.whiteboard_mode == "dimension":
            consolidated = (
                self._consolidate_dimension_boards(client, temperature) or consolidated
            )

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
            "views": views or plan.selected_views,
            "evidence_payload": payload,
            "evidence_payload_chars": payload_chars(payload),
            "attention": dict(self.whiteboard.attention),
            "attention_contribution": contribution_summary(plan.view_scores),
            "routing": plan.to_dict(),
            "routed_groups": plan.groups_consulted,
            "total_groups": len(self.manifest.groups),
            "tape_records": len(self.tape),
            "agents": len(self.manifest.agents),
            "render": self.whiteboard.render(),
            "boards": (
                {
                    d: b.render()
                    for d, b in self.whiteboard.active_boards(
                        [x for x in DIMENSIONS if x in self.whiteboard.boards]
                    ).items()
                }
                if self.config.whiteboard_mode == "dimension"
                else {}
            ),
            "cached": False,
        }
        if graph_mode != "off":
            agent_ids = {a.memory_id for a in run.annotations}
            graph_ids = {a.memory_id for a in graph_annotations}
            metrics = graph_result.metrics() if graph_result is not None else {}
            metrics["graph_only_memories"] = len(graph_ids - agent_ids)
            metrics["overlap_memories"] = len(graph_ids & agent_ids)
            result["graph_mode"] = graph_mode
            result["graph_evidence"] = (
                [item.to_dict() for item in graph_result.evidence]
                if graph_result is not None
                else []
            )
            result["graph_metrics"] = metrics
        self._save_recall_cache(question, result)
        if cross_session:
            result["past_hits"] = self._cross_session_hits(question)
        self._record_admission_shadow(question, kept, payload, cached=False)
        return result

    def _record_admission_shadow(self, question: str, annotations: list[Any],
                                 payload: list[dict[str, Any]], *,
                                 cached: bool) -> None:
        """Read-only instrumentation; never changes the recall result."""
        if not admission_shadow.enabled():
            return
        try:
            admission_shadow.record(
                root=self.root,
                question=question,
                session_id=self.root.name,
                annotations=annotations,
                records=self.tape.read(),
                payload=payload,
                event_hits=self._cross_session_hits(question),
                cached=cached,
            )
        except Exception:  # instrumentation must never break recall
            pass

    # ------------------------------------------------------------ graph recall

    def _graph_recall_mode(self) -> str:
        """Effective graph recall mode: off unless enabled and configured."""
        if not self.config.graph_enabled:
            return "off"
        mode = self.config.graph_recall_mode
        return mode if mode in {"augment", "augment_guarded", "only"} else "off"

    def _graph_recall(self, question: str, *, guard: bool = False) -> Any:
        """Run graph-side recall; never raises, returns None when unavailable.

        With ``guard`` the evidence passes admission control (score floor and
        a small cap) before it can compete for the single global budget.
        """
        try:
            from .graph import GraphStore
            from .graph_recall import GraphRecall, guard_evidence, question_gate

            store = GraphStore(resolve_path(self.root, self.config.graph_path))
            if not store.exists():
                return None
            hub_degree = self.config.graph_hub_degree
            if guard and not hub_degree:
                hub_degree = self.config.graph_augment_hub_degree
            recall = GraphRecall(
                store.index(),
                embedder=self._embedder(),
                depth=self.config.graph_depth,
                top_k=self.config.graph_top_k,
                hub_degree=hub_degree,
            )
            result = recall.recall(question)
            if guard:
                result.evidence = guard_evidence(
                    result.evidence,
                    min_score=self.config.graph_augment_min_score,
                    max_items=self.config.graph_augment_max_items,
                )
                if self.config.graph_augment_question_gate:
                    records = {record.id: record for record in self.tape.read()}
                    result.evidence = question_gate(
                        result.evidence,
                        records,
                        question,
                        min_cov=self.config.graph_augment_question_min_cov,
                    )
                result.paths_selected = sum(len(item.paths) for item in result.evidence)
            return result
        except Exception:
            return None

    def _graph_annotations(
        self, graph_result: Any, *, weight: float = 1.0
    ) -> list[Annotation]:
        """Turn graph evidence into annotations, rehydratable from the tape.

        Memories that are not active on the tape (orphan relations, archived
        records) are dropped: the graph selects, the tape supplies the facts.
        ``weight`` ranks graph evidence below strong agent evidence when the
        guarded mode asks for it (1.0 = neutral).
        """
        if graph_result is None:
            return []
        active = {record.id for record in self.tape.read() if record.status == "active"}
        out: list[Annotation] = []
        for item in graph_result.evidence:
            if item.memory_id not in active:
                continue
            out.append(
                Annotation(
                    memory_id=item.memory_id,
                    note=item.label or "graph evidence",
                    relevance=max(0.05, float(item.score) * max(0.0, weight)),
                    agent_id="graph",
                )
            )
        return out

    @staticmethod
    def _union_with_graph(
        annotations: list[Annotation], graph_annotations: list[Annotation]
    ) -> list[Annotation]:
        """Union agent and graph annotations, deduped by memory id.

        The single global budget is applied later, after the union, so the two
        recall arms never compete with independent budgets.
        """
        by_id: dict[str, Annotation] = {a.memory_id: a for a in annotations}
        for item in graph_annotations:
            current = by_id.get(item.memory_id)
            if current is None:
                by_id[item.memory_id] = item
                continue
            if item.relevance > current.relevance:
                by_id[item.memory_id] = Annotation(
                    memory_id=current.memory_id,
                    note=current.note or item.note,
                    relevance=item.relevance,
                    agent_id=current.agent_id or item.agent_id,
                )
        return list(by_id.values())

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
        projected: list[MemoryRecord] = []

        def _append(rec: MemoryRecord) -> None:
            nonlocal new_agents, skipped_secrets
            try:
                rec, _g, _a, created = add_memory(
                    self.tape, self.manifest, rec, model=self.config.model
                )
                saved.append(rec.to_dict())
                if created:
                    new_agents += 1
                projected.append(rec)
            except SecretError:
                skipped_secrets += 1

        for spec in memories or []:
            rec = memory_from_spec(spec)
            if rec is not None:
                _append(rec)
        self._graph_after_appends(projected)

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

    def ingest_document(
        self,
        path: str | Path,
        *,
        chunk_size: int | None = None,
        enable_graph: bool | None = None,
    ) -> dict[str, Any]:
        """Ingest a .txt as tape memories + document registry + graph (D3/D4).

        Commit order is strictly tape -> registry -> graph; the graph flags are
        consulted only here (``document_graph_enabled``/``document_structure_level``,
        ``--no-document-graph`` passes ``enable_graph=False``). ``add_memory``
        and ``ingest_attachment`` are untouched.
        """
        from .graph import GraphStore
        from .graph_extract import GraphExtractor
        from .graph_resolve import GraphResolver
        from .ingest_document import ingest_document as _ingest_document

        enabled = self.config.document_graph_enabled if enable_graph is None else enable_graph
        store = extractor = resolver = None
        if enabled:
            store = GraphStore(resolve_path(self.root, self.config.graph_path))
            try:
                extractor = GraphExtractor(self._ensure_client())
            except Exception:
                extractor = None
            resolver = GraphResolver(
                embedder=self._embedder(),
                auto=self.config.graph_confidence_auto,
                hypothesis=self.config.graph_confidence_hypothesis,
                max_candidates=self.config.graph_resolver_candidates,
            )
        result = _ingest_document(
            self.tape,
            self.manifest,
            path,
            chunk_size=chunk_size or self.config.attach_chunk_size,
            model=self.config.model,
            store=store,
            extractor=extractor,
            resolver=resolver,
            enable_graph=enabled,
            batch_size=self.config.graph_batch_size,
            batch_max_chars=self.config.graph_batch_max_chars,
            max_attempts=self.config.graph_max_attempts,
            structure_level=self.config.document_structure_level,
            window_chars=self.config.document_window_chars,
        )
        if result.get("ok") or result.get("skipped"):
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
