"""Dimension-aware structural routing: RoutingPlan + progressive relaxation.

Views are grouped into dimensions with different cognitive roles:

    semantic    topic/*, subject/*   — what the memory is about
    temporal    time/*               — when it happened
    structural  type/*, source/*     — what kind / where it came from

The router first selects the *dimensions* a question needs (recording which
trigger fired), then the views inside each dimension, and combines their record
sets by intersection. When the strict intersection is empty, constraints are
relaxed progressively (``relaxed_semantic`` -> ``relaxed_temporal``) before
falling back to a union, so an over-constrained plan does not immediately
destroy the reduction the topology offers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .attention import blend, classify, normalize
from .llm import extract_json_object
from .tape import Tape
from .views import build_index, rank_views

SEMANTIC_PREFIXES = ("topic/", "subject/")
TEMPORAL_PREFIXES = ("time/",)
STRUCTURAL_PREFIXES = ("type/", "source/")

DIMENSIONS = ("semantic", "temporal", "structural")

SOURCE_DEFAULT = "default_semantic"
SOURCE_MARKER = "lexical_marker"
SOURCE_TEMPORAL = "temporal_parser"
SOURCE_TYPE = "type_marker"
SOURCE_SOURCE = "source_marker"
SOURCE_LLM = "llm"

MONTHS = {
    "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3,
    "april": 4, "apr": 4, "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7,
    "august": 8, "aug": 8, "september": 9, "sep": 9, "sept": 9,
    "october": 10, "oct": 10, "november": 11, "nov": 11, "december": 12, "dec": 12,
}
TEMPORAL_WORDS = {
    "when", "since", "before", "after", "changed", "change", "timeline",
    "recent", "recently", "last", "latest", "earlier", "later", "first",
    "between", "during", "month", "week", "year", "ago", "previous", "prior",
    "history", "evolve", "evolution", "now",
}
RECENCY_WORDS = {"recent", "recently", "latest", "last", "now", "current", "lately"}
TYPE_WORDS = {
    "decision": "decision", "decisions": "decision", "decide": "decision",
    "decided": "decision", "lesson": "lesson", "lessons": "lesson",
    "preference": "preference", "preferences": "preference", "bugfix": "bugfix",
    "build": "build", "convention": "convention", "conventions": "convention",
    "rule": "convention", "rules": "convention", "policy": "convention",
}
SOURCE_WORDS = {
    "attachment", "attachments", "file", "files", "document", "documents",
    "spec", "specs", "specification", "pdf",
}
_ISO_RE = re.compile(r"\b(20\d{2})-(\d{2})\b")
_YEAR_RE = re.compile(r"\b(20\d{2})\b")
_MONTH_RE = re.compile(r"\b(" + "|".join(sorted(MONTHS, key=len, reverse=True)) + r")\b")


def dimension_of(view: str) -> str | None:
    if view.startswith(SEMANTIC_PREFIXES):
        return "semantic"
    if view.startswith(TEMPORAL_PREFIXES):
        return "temporal"
    if view.startswith(STRUCTURAL_PREFIXES):
        return "structural"
    return None


def views_of_dimension(tape: Tape, dimension: str) -> list[str]:
    return [v for v in build_index(tape) if dimension_of(v) == dimension]


def parse_time_views(query: str, available: list[str]) -> list[str]:
    """Time views a query points at (explicit dates, ranges, or 'recent')."""
    q = (query or "").lower()
    avail = set(available)
    found: list[str] = []
    years = [int(y) for y in _YEAR_RE.findall(q)]
    for year, month in _ISO_RE.findall(q):
        view = f"time/{year}-{month}"
        if view in avail:
            found.append(view)
    for name in _MONTH_RE.findall(q):
        mm = f"{MONTHS[name]:02d}"
        candidates = [v for v in available if v.endswith(f"-{mm}")]
        if years:
            found.extend(f"time/{y}-{mm}" for y in years if f"time/{y}-{mm}" in avail)
        elif candidates:
            found.append(sorted(candidates)[-1])
    found = sorted(set(found))
    if found:
        if any(w in q for w in ("since", "after", "from", "later", "onwards")):
            start = found[0]
            return sorted(v for v in available if v >= start)
        if any(w in q for w in ("before", "prior", "earlier", "until")):
            end = found[0]
            return sorted(v for v in available if v < end)
        return found
    # Recency words alone imply "the latest months"; generic temporal markers
    # without a date (e.g. "after the benchmarks") must NOT restrict the range.
    if any(w in q for w in RECENCY_WORDS):
        return sorted(available)[-2:]
    return []


def detect_dimensions(query: str, *, available_time: list[str] | None = None) -> dict[str, str]:
    """Dimensions the query needs, each with the trigger source that fired."""
    q = (query or "").lower()
    tokens = set(re.findall(r"[a-z0-9_]+", q))
    out: dict[str, str] = {"semantic": SOURCE_DEFAULT}
    if parse_time_views(q, available_time or []):
        out["temporal"] = SOURCE_TEMPORAL
    elif tokens & TEMPORAL_WORDS:
        out["temporal"] = SOURCE_MARKER
    if tokens & set(TYPE_WORDS):
        out["structural"] = SOURCE_TYPE
    elif tokens & SOURCE_WORDS:
        out["structural"] = SOURCE_SOURCE
    return out


@dataclass
class RoutingPlan:
    """A structural access plan: which dimensions, which views, how combined."""

    mode: str = "views"
    dimensions: list[str] = field(default_factory=list)
    dimension_sources: dict[str, str] = field(default_factory=dict)
    views_by_dimension: dict[str, list[str]] = field(default_factory=dict)
    candidate_views: list[str] = field(default_factory=list)
    candidate_scores: dict[str, float] = field(default_factory=dict)
    combination: str = "single"
    intersection_mode: str = ""
    intersection_size: int = 0
    confidence: float | None = None
    score: float | None = None
    view_scores: dict[str, dict[str, float | str]] = field(default_factory=dict)
    attention_before: dict[str, float] = field(default_factory=dict)
    attention_after: dict[str, float] = field(default_factory=dict)
    anaphoric: bool = False
    attention_gate: str = ""
    # execution metadata, filled while running
    level: int = 1
    fallback_reasons: list[str] = field(default_factory=list)
    coverage: list[dict[str, Any]] = field(default_factory=list)
    coverage_signal: str = ""
    coverage_missing: list[str] = field(default_factory=list)
    level1_coverage_signal: str = ""
    level1_coverage_missing: list[str] = field(default_factory=list)
    consulted_ids: list[str] = field(default_factory=list)
    level1_ids: list[str] = field(default_factory=list)
    records_consulted: int = 0
    records_total: int = 0
    records_level1: int = 0
    groups_consulted: int = 0

    @property
    def selected_views(self) -> list[str]:
        return [v for d in DIMENSIONS for v in self.views_by_dimension.get(d, [])]

    def to_dict(self) -> dict[str, Any]:
        data = {
            "mode": self.mode,
            "dimensions": list(self.dimensions),
            "dimension_sources": dict(self.dimension_sources),
            "views_by_dimension": {k: list(v) for k, v in self.views_by_dimension.items()},
            "candidate_views": list(self.candidate_views),
            "candidate_scores": dict(self.candidate_scores),
            "combination": self.combination,
            "intersection_mode": self.intersection_mode,
            "intersection_size": self.intersection_size,
            "confidence": self.confidence,
            "score": self.score,
            "view_score": self.score,
            "view_scores": {k: dict(v) for k, v in self.view_scores.items()},
            "attention_before": dict(self.attention_before),
            "attention_after": dict(self.attention_after),
            "anaphoric": self.anaphoric,
            "attention_gate": self.attention_gate,
            "level": self.level,
            "fallback_reasons": list(self.fallback_reasons),
            "coverage": list(self.coverage),
            "coverage_signal": self.coverage_signal,
            "coverage_missing": list(self.coverage_missing),
            "level1_coverage_signal": self.level1_coverage_signal,
            "level1_coverage_missing": list(self.level1_coverage_missing),
            "consulted_ids": list(self.consulted_ids),
            "level1_ids": list(self.level1_ids),
            "records_consulted": self.records_consulted,
            "records_total": self.records_total,
            "records_level1": self.records_level1,
            "groups_consulted": self.groups_consulted,
            "selected_views": self.selected_views,
        }
        return data


def _ids_of_views(tape: Tape, views: list[str]) -> set[str]:
    want = set(views)
    if not want:
        return set()
    return {
        r.id
        for r in tape.read()
        if r.status == "active" and r.id and want & set(r.views)
    }


def _intersect(sets: list[set[str]]) -> set[str]:
    out = set(sets[0])
    for s in sets[1:]:
        out &= s
    return out


def ids_for_plan(tape: Tape, plan: RoutingPlan) -> tuple[set[str], str]:
    """Records selected by the plan, relaxing an empty intersection step by step.

    Order: ``strict`` -> ``relaxed_semantic`` (next semantic candidate) ->
    ``relaxed_temporal`` (drop the time constraint) -> ``union_fallback``.
    """
    candidates: dict[str, list[set[str]]] = {
        "semantic": [_ids_of_views(tape, [v]) for v in plan.views_by_dimension.get("semantic", [])],
        "temporal": [_ids_of_views(tape, plan.views_by_dimension.get("temporal", []))]
        if plan.views_by_dimension.get("temporal")
        else [],
        "structural": [_ids_of_views(tape, [v]) for v in plan.views_by_dimension.get("structural", [])],
    }
    candidates = {d: [c for c in cs if c] for d, cs in candidates.items()}
    dims = [d for d in DIMENSIONS if candidates[d]]
    if not dims:
        return set(), "empty"
    if len(dims) == 1:
        union: set[str] = set()
        for candidate in candidates[dims[0]]:
            union |= candidate
        return union, "single"

    strict = _intersect([candidates[d][0] for d in dims])
    if strict:
        return strict, "strict"

    for candidate in candidates.get("semantic", [])[1:]:
        trial = _intersect([candidate if d == "semantic" else candidates[d][0] for d in dims])
        if trial:
            return trial, "relaxed_semantic"

    if "temporal" in dims:
        remaining = [d for d in dims if d != "temporal"]
        if remaining:
            trial = _intersect([candidates[d][0] for d in remaining])
            if trial:
                return trial, "relaxed_temporal"

    union: set[str] = set()
    for d in dims:
        for c in candidates[d]:
            union |= c
    return union, "union_fallback"


def _apply_attention(
    plan: RoutingPlan,
    index: dict[str, list[str]],
    attention: dict[str, float],
    weight: float,
    *,
    view_top_k: int,
    candidate_k: int,
) -> None:
    """Re-rank the plan with the attention prior; active views are guaranteed."""
    active = {v: w for v, w in attention.items() if w > 0 and v in index}
    if not active:
        return
    router = dict(plan.candidate_scores)
    views = list(dict.fromkeys(list(plan.candidate_views) + list(active)))
    final = blend(router, active, weight)
    router_norm = normalize(router)
    by_dim: dict[str, list[str]] = {}
    for view in views:
        dim = dimension_of(view)
        if dim:
            by_dim.setdefault(dim, []).append(view)
    new_selected: dict[str, list[str]] = {}
    new_candidates: list[str] = []
    scores: dict[str, dict[str, float | str]] = {}
    for dim, dim_views in by_dim.items():
        ranked = sorted(dim_views, key=lambda v: (-final.get(v, 0.0), v))
        # Active views are guaranteed *candidates* (they are in ``views`` via the
        # union above) but not guaranteed slots: on a topic shift the new topic's
        # router score must be able to outrank the decaying prior.
        selected = ranked if dim == "temporal" else ranked[:view_top_k]
        new_selected[dim] = selected
        new_candidates.extend(ranked[:candidate_k])
        for view in selected:
            weighted = weight * active.get(view, 0.0)
            scores[view] = {
                "router": round(router_norm.get(view, 0.0), 4),
                "attention": round(active.get(view, 0.0), 4),
                "attention_weighted": round(weighted, 4),
                "final": round(final.get(view, 0.0), 4),
                "contribution": classify(router_norm.get(view, 0.0), weighted),
            }
    plan.views_by_dimension = new_selected
    plan.candidate_views = list(dict.fromkeys(new_candidates))
    plan.dimensions = [d for d in DIMENSIONS if new_selected.get(d)]
    plan.view_scores = scores


def select_plan_lexical(
    tape: Tape,
    query: str,
    *,
    view_top_k: int = 5,
    candidate_k: int = 6,
    attention: dict[str, float] | None = None,
    attention_weight: float = 0.0,
) -> RoutingPlan:
    """Deterministic dimension-aware plan (no LLM).

    ``candidate_views`` keeps the ranked regions beyond the selected ones, so a
    coverage check can detect a plausible view the router did not select.
    """
    index = build_index(tape)
    time_views = [v for v in index if dimension_of(v) == "temporal"]
    sources = detect_dimensions(query, available_time=time_views)
    plan = RoutingPlan(
        mode="views",
        dimensions=list(sources),
        dimension_sources=sources,
    )
    top_score = 0.0
    candidates: list[str] = []
    scores: dict[str, float] = {}

    if "semantic" in sources:
        hits = rank_views(tape, query, limit=candidate_k, prefixes=SEMANTIC_PREFIXES)
        if hits:
            plan.views_by_dimension["semantic"] = [v for v, _s in hits[:view_top_k]]
            for view, score in hits:
                candidates.append(view)
                scores[view] = score
            top_score = max(top_score, hits[0][1])

    if "temporal" in sources:
        views = parse_time_views(query, time_views)
        if views:
            plan.views_by_dimension["temporal"] = views
            for view in views:
                candidates.append(view)
                scores[view] = 1.0

    if "structural" in sources:
        tokens = set(re.findall(r"[a-z0-9_]+", query.lower()))
        views = [f"type/{TYPE_WORDS[t]}" for t in tokens if t in TYPE_WORDS]
        views = [v for v in dict.fromkeys(views) if v in index]
        marker = bool(views)
        if not views:
            hits = rank_views(tape, query, limit=candidate_k, prefixes=STRUCTURAL_PREFIXES)
            views = [v for v, _s in hits]
            for view, score in hits:
                scores[view] = score
        if views:
            plan.views_by_dimension["structural"] = views[:view_top_k]
            for view in views:
                candidates.append(view)
                scores.setdefault(view, 1.0 if marker else scores.get(view, 1.0))

    plan.candidate_views = list(dict.fromkeys(candidates))
    plan.candidate_scores = scores
    if attention and attention_weight > 0:
        _apply_attention(
            plan,
            index,
            attention,
            attention_weight,
            view_top_k=view_top_k,
            candidate_k=candidate_k,
        )
    if not plan.view_scores:
        router_norm = normalize(plan.candidate_scores)
        plan.view_scores = {
            view: {
                "router": round(router_norm.get(view, 0.0), 4),
                "attention": 0.0,
                "attention_weighted": 0.0,
                "final": round(router_norm.get(view, 0.0), 4),
                "contribution": classify(router_norm.get(view, 0.0), 0.0),
            }
            for view in plan.selected_views
        }
    active = [d for d in DIMENSIONS if plan.views_by_dimension.get(d)]
    plan.combination = "intersection" if len(active) > 1 else "single"
    plan.score = top_score if top_score > 0 else None
    return plan


DIMENSION_ROUTER_PROMPT = """You plan how to access a memory tape. Memories are \
indexed by views grouped into three dimensions:

- semantic (topic/*, subject/*): what a memory is about
- temporal (time/YYYY-MM): when it happened
- structural (type/*, source/*): what kind it is and where it came from

Available views, by dimension:

{views}

{attention}

Current working context:

{whiteboard}

Query: {query}

Return ONLY JSON, nothing else:
{{"dimensions":["semantic","temporal"],"views":["topic/router","time/2026-09"],"confidence":0.0}}

Pick the dimensions the query needs (semantic is usually needed; add temporal \
for when/before/since/recent questions and structural for questions about a \
kind of memory or a document) and the specific views within them that could \
hold the answer. Prefer a few precise views over many broad ones. confidence is \
0.0-1.0 for how well the plan covers what the query needs."""


def select_plan_llm(
    tape: Tape,
    query: str,
    client: Any,
    *,
    whiteboard: Any = None,
    attention: dict[str, float] | None = None,
    top_k: int = 5,
    max_views: int = 40,
) -> RoutingPlan | None:
    """Contextual dimension-aware plan via one LLM call (or None on failure)."""
    if client is None:
        return None
    index = build_index(tape)
    if not index:
        return None
    by_dim: dict[str, list[str]] = {d: [] for d in DIMENSIONS}
    for view in index:
        dim = dimension_of(view)
        if dim:
            by_dim[dim].append(view)
    lines: list[str] = []
    for dim in DIMENSIONS:
        views = sorted(by_dim[dim], key=lambda v: (-len(index[v]), v))[:max_views]
        if views:
            lines.append(f"{dim}: " + ", ".join(f"{v} ({len(index[v])})" for v in views))
    board = ""
    if whiteboard is not None:
        board = (
            whiteboard.render(include_annotations=False)
            if hasattr(whiteboard, "render")
            else str(whiteboard)
        )
    attention_block = ""
    if attention:
        active = sorted(
            ((v, w) for v, w in attention.items() if w > 0), key=lambda x: -x[1]
        )[:8]
        if active:
            attention_block = (
                "Currently active views (previous turn; the new message may refer to them):\n"
                + ", ".join(f"{v} ({w:.2f})" for v, w in active)
            )
    messages = [
        {
            "role": "system",
            "content": DIMENSION_ROUTER_PROMPT.format(
                views="\n".join(lines),
                attention=attention_block,
                whiteboard=board or "(empty whiteboard)",
                query=query,
            ),
        },
        {"role": "user", "content": query},
    ]
    try:
        content = client.complete(messages, temperature=0.0)
    except Exception:
        return None
    obj = extract_json_object(content)
    known = set(index)
    candidates = [v for v in (obj.get("views") or []) if isinstance(v, str) and v in known][:10]
    if not candidates:
        return None
    selected = candidates[:top_k]
    views_by_dimension: dict[str, list[str]] = {}
    for view in selected:
        dim = dimension_of(view)
        if dim:
            views_by_dimension.setdefault(dim, []).append(view)
    requested = [d for d in (obj.get("dimensions") or []) if d in DIMENSIONS]
    dims = list(dict.fromkeys(requested + list(views_by_dimension)))
    try:
        confidence = float(obj.get("confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    active = [d for d in DIMENSIONS if views_by_dimension.get(d)]
    return RoutingPlan(
        mode="views",
        dimensions=dims,
        dimension_sources={d: SOURCE_LLM for d in dims},
        views_by_dimension=views_by_dimension,
        candidate_views=candidates,
        combination="intersection" if len(active) > 1 else "single",
        confidence=max(0.0, min(1.0, confidence)),
    )


COVERAGE_JUDGE_PROMPT = """You judge whether the memories retrieved for a query \
are sufficient to answer it.

Retrieved memories (what the agents chose to remember):

{memories}

Other regions of the memory that were NOT retrieved (view: what it covers):

{candidates}

Current working context:

{whiteboard}

Query: {query}

Return ONLY JSON, nothing else:
{{"coverage":"complete","missing":[],"reason":"<short>"}}

coverage is "complete" (the retrieved memories contain what the query needs), \
"partial" (something relevant is missing — name it in missing, e.g. a region \
above that the query needs) or "uncertain" (you cannot tell). missing lists \
what is missing, empty when complete. Judge coverage, not relevance: a relevant \
memory that does not answer the query is partial. Pay attention to wording \
differences: a region may cover what the query asks even when it does not share \
the query's words."""


def _candidate_digest(
    tape: Tape | None,
    plan: RoutingPlan,
    *,
    limit: int = 4,
    max_chars: int = 220,
    manifest: Any = None,
) -> list[str]:
    """Compact digests of plausible views the plan did not select.

    Prefers the view agent's persisted digest when it is current, so the router
    and the judge see the region's own summary rather than raw member lines.
    """
    if tape is None:
        return []
    records = {r.id: r for r in tape.read() if r.status == "active"}
    index = build_index(tape)
    selected = set(plan.selected_views)
    view_agents = getattr(manifest, "view_agents", {}) if manifest is not None else {}
    out: list[str] = []
    for view in plan.candidate_views:
        if view in selected or view not in index:
            continue
        agent = view_agents.get(view)
        if agent is not None and agent.digest and agent.digest_records == len(index[view]):
            out.append(f"{view}: {agent.digest[:max_chars]}")
        else:
            summaries = [
                records[i].summary for i in index[view] if i in records and records[i].summary
            ]
            out.append(f"{view}: {' | '.join(summaries[:3])[:max_chars] or '(no summaries)'}")
        if len(out) >= limit:
            break
    return out


def judge_coverage(
    question: str,
    annotations: list[Any],
    client: Any,
    *,
    whiteboard: Any = None,
    plan: RoutingPlan | None = None,
    tape: Tape | None = None,
    manifest: Any = None,
    temperature: float = 0.0,
) -> tuple[str, list[str]]:
    """One LLM call judging whether the retrieved memories cover the query.

    With a ``plan``/``tape`` the judge also sees the plausible regions the
    router did NOT select (v2), so it can flag a semantic gap the candidate
    ranking alone cannot express.
    """
    if client is None:
        return "uncertain", []
    lines = [f"{a.memory_id}: {a.note}" for a in annotations if getattr(a, "note", "")]
    candidates = (
        _candidate_digest(tape, plan, manifest=manifest) if plan is not None else []
    )
    board = ""
    if whiteboard is not None:
        board = (
            whiteboard.render(include_annotations=False)
            if hasattr(whiteboard, "render")
            else str(whiteboard)
        )
    messages = [
        {
            "role": "system",
            "content": COVERAGE_JUDGE_PROMPT.format(
                memories="\n".join(lines) or "(none)",
                candidates="\n".join(candidates) or "(none)",
                whiteboard=board or "(empty whiteboard)",
                query=question,
            ),
        },
        {"role": "user", "content": question},
    ]
    try:
        content = client.complete(messages, temperature=temperature)
    except Exception:
        return "uncertain", []
    obj = extract_json_object(content)
    level = str(obj.get("coverage") or "").strip().lower()
    if level not in {"complete", "partial", "uncertain"}:
        level = "uncertain"
    raw_missing = obj.get("missing")
    missing: list[str] = []
    if isinstance(raw_missing, list):
        missing = [str(m).strip() for m in raw_missing if str(m).strip()]
    elif isinstance(raw_missing, str) and raw_missing.strip():
        missing = [raw_missing.strip()]
    return level, missing


def coverage_signal(
    plan: RoutingPlan,
    annotated_ids: set[str],
    agent_signals: list[Any],
    tape: Tape,
    *,
    structural: bool = True,
) -> tuple[str, list[str]]:
    """Recall-local coverage judgment: complete | partial | uncertain.

    Combines the agents' own coverage telemetry with a free structural check
    (do any annotated memories live in the plan's selected views?). Never
    persisted on the agent. ``structural=False`` uses agent telemetry only.
    """
    missing: list[str] = []
    levels: set[str] = set()
    for signal in agent_signals:
        levels.add(getattr(signal, "coverage", "") or "")
        missing.extend(getattr(signal, "missing", []) or [])
    missing = [m for m in dict.fromkeys(missing) if m]
    if "partial" in levels or missing:
        return "partial", missing
    if not annotated_ids:
        return "uncertain", ["no annotated memory"]
    if "uncertain" in levels:
        return "uncertain", missing
    if not structural:
        return "complete", []
    selected = set(plan.selected_views)
    covered: set[str] = set()
    for record in tape.read():
        if record.id in annotated_ids:
            covered |= set(record.views)
    if selected and not (selected & covered):
        return "partial", ["annotated memories are outside the selected views"]
    return "complete", []


def view_coverage_signal(
    plan: RoutingPlan,
    annotated_ids: set[str],
    tape: Tape,
    *,
    candidate_k: int = 6,
    min_ratio: float = 0.6,
) -> tuple[str, list[str]]:
    """Coverage of the plan's *candidate* views: did we leave a plausible region out?

    Unlike :func:`coverage_signal`, this detects a region the router did NOT
    select: candidate views ranked for the query (beyond the selected ones)
    with no annotated memory are reported as gaps, so the cascade can expand
    straight to them. Returns the raw view names in ``missing``.
    """
    covered: set[str] = set()
    for record in tape.read():
        if record.id in annotated_ids:
            covered |= set(record.views)
    scores = plan.candidate_scores or {}
    top = max(scores.values()) if scores else 1.0
    required = [
        v
        for v in plan.candidate_views[:candidate_k]
        if v not in plan.selected_views and scores.get(v, 1.0) >= min_ratio * top
    ]
    gaps = [v for v in required if v not in covered]
    if gaps:
        return "partial", gaps
    return "complete", []
