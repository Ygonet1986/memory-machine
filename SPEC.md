# Memory Machine Specification

**Version:** 0.4
**Status:** Draft
**Date:** 2026-09-11

## 1. Abstract

The Memory Machine separates long-term persistent memory from working memory.
A conceptually infinite **tape** stores durable memories. A layer of **memory
agents**, one per group of the tape, watches a shared **whiteboard** that
represents the work happening now. Each agent reads the whiteboard in parallel
and, in a single pass, both (a) updates its own dynamic **checklist** of what it
must not forget and (b) annotates the memories it believes the chatbot should
know right now. The **main chatbot** consumes the whiteboard (subject,
metacognition, checklist and the agents' annotations) and continues the task.

Memory is organized into **topics**, each owning its own tape; a **router** can
infer the topic from each message and switch tapes internally. An optional
**RAG** document store and a **web search** layer feed the chatbot with external
context that never touches long-term memory.

The key words "MUST", "MUST NOT", "REQUIRED", "SHALL", "SHOULD", "SHOULD NOT",
"RECOMMENDED", "MAY", and "OPTIONAL" are interpreted as in RFC 2119.

## 2. Terminology

- **Tape** — the append-only long-term store of memories (one per topic).
- **Memory (record)** — the atomic unit of the tape: a typed fact with a stable
  identity (`M0001`, `M0002`, ...) and a status.
- **Group** — a contiguous range of memory ids watched by one memory agent.
- **Memory agent** — one LLM call per group. It reads the whiteboard, refines
  its checklist and produces annotations.
- **Whiteboard** — the bounded shared working memory (summary of what is
  relevant right now).
- **Annotation** — a reminder an agent writes to the whiteboard, referencing a
  memory id it judges relevant.
- **Metacognition** — a short, always-updated understanding of the current work
  (what the subject is about, what is happening, key facts, open items).
- **Checklist** — a dynamic list of things that must not be forgotten (the
  chatbot has one; each memory agent has one).
- **Main chatbot** — the consumer of the whiteboard; it performs the task and
  emits durable memories.
- **Consolidator** — the step (whiteboard or chatbot context) that shrinks
  working state when it exceeds its budget.
- **Topic** — a self-contained memory store (its own tape, manifest, whiteboard
  and context), named by its creation date/time.
- **Router** — an LLM call that infers which topic a message refers to.
- **RAG** — retrieval of relevant chunks from `.txt` documents (keyword-based).
- **Web search** — a keyless DuckDuckGo lookup for the current message.
- **External context** — RAG + web results handed only to the chatbot, never to
  memory.

## 3. Architecture Overview

```
            topics/<id>/tape.jsonl  (per-topic long-term memory)
                         |
       +--------+--------+--------+---- ...
       G1       G2       G3       G4        (groups, capacity C each)
        |        |        |        |
       A1       A2       A3       A4        (memory agents)
        \        \        /        /
         +-----> whiteboard.json <------+
        (checklist + annotations)       |
                  |                     |
            main chatbot  <---- external context (RAG + web)
                  |
         durable memories + turn record -> tape
```

## 4. The Tape

The tape is an append-only sequence of memory records, conceptually unbounded.
Records MUST NOT be mutated after they are written; **supersession** is
expressed by a later record referencing the old one (or by setting the old
record's status), never by rewriting its content.

### 4.1 Record identity and status

Each record has a stable identity `M<num>`. Each record has a `status`
(`active`, `archived`, `superseded`). Archived/superseded records remain on the
tape for audit but are excluded from the memory agents' context.

### 4.2 Record schema

| Field | Required | Type | Description |
|-------|----------|------|-------------|
| id | REQUIRED | string | Stable identity (`M0001`) |
| type | REQUIRED | string | `decision`, `lesson`, ... |
| summary | REQUIRED | string | One-sentence description |
| why | OPTIONAL | string | Reasoning |
| files | OPTIONAL | list | Related file paths |
| created_at | OPTIONAL | string | ISO 8601 timestamp |
| status | OPTIONAL | string | `active` (default), `archived`, `superseded` |
| source | OPTIONAL | string | Origin (e.g. `spec.txt#hash`), for dedup |
| derived_from | OPTIONAL | list | Source ids of a rollup (provenance) |
| views | OPTIONAL | list | Organizational projections (see 4.4) |

### 4.3 Views (organizational projections)

A record belongs to one canonical tape but MAY belong to several **views**
without physical duplication: `time/<YYYY-MM>`, `type/<type>`,
`source/<file>`, and explicit `topic/…` / `subject/…` tags. The view index is a
**rebuildable projection** derived from the records' `views`; the tape remains
the single source of truth. This separates storage (what happened),
organization (which views it belongs to) and attention (which views are
active) — the foundation of the v0.5 multidimensional topology.

### 4.3 Secret scanning

Before any record is written, its content MUST be scanned for secret-like
patterns (API keys, tokens, private keys, JWTs). If a match is found, the write
MUST be refused. No secrets may reach the memory layer.

## 5. Groups and Memory Agents

### 5.1 Grouping

A group is a contiguous range of record ids `[start, end]` of fixed size
`capacity`. Groups partition the tape in insertion order.

### 5.2 Agent creation

Memory agents are created **as the tape grows**. When a record falls outside
all existing groups, the implementation MUST create a new group and a new
memory agent for it. Each agent is responsible for exactly one group.

### 5.3 Agent context and checklist

Each agent holds the full content of its group's **active** records in its
context, plus its own persistent checklist (stored in the manifest). The
checklist is the agent's metacognition: a distilled, dynamic list of what it
must not forget to remind the assistant about.

## 6. The Whiteboard

The whiteboard is the bounded shared working memory — a summary of what is
relevant right now. It contains:

- `subject` — what is being worked on now.
- `objective` — the current goal (OPTIONAL).
- `metacognition` — the "Understanding": what the subject is about, what is
  happening, key facts, open items (refreshed every turn).
- `checklist` — the chatbot's dynamic list of things it must not forget
  (refreshed every turn).
- `context` — working notes carried forward.
- `pending` — open items and decisions under discussion.
- `annotations` — reminders contributed by memory agents.

The whiteboard does not replace the tape: it is working memory, the tape is
long-term memory.

## 7. The Agent Call (checklist + annotation fused)

Every cycle, each memory agent performs ONE LLM call that does two things:

1. Refines its checklist (from its memories, its previous checklist and the
   current work).
2. Produces annotations for the memories that must be remembered now.

The output is a single JSON object:

```json
{"checklist":["...","..."],
 "annotations":[{"memory_id":"M0001","note":"why this matters now","relevance":0.9}]}
```

### 7.1 Reading

Every memory agent MUST read the whiteboard on each cycle, in **parallel**.
Agents read the whiteboard WITHOUT the annotations (subject, objective,
metacognition, checklist, context, pending) so they do not echo each other.

### 7.2 Relevance and deduplication

`relevance` MUST be clamped to `[0.0, 1.0]`. The implementation MUST deduplicate
annotations by `memory_id` (highest relevance wins) and MUST bound them by a
character budget (lowest relevance dropped first).

## 8. The Cycle

```
1. The main chatbot works on a task; the whiteboard records the subject.
2. (optional) The router picks the topic; the backend switches tapes if needed.
3. Every memory agent reads the whiteboard in parallel and, in one call,
   refines its checklist and annotates relevant memories.
4. Annotations are merged and deduplicated into the whiteboard (budgeted).
5. If the whiteboard exceeds its threshold, the consolidator reduces it.
6. The main chatbot reads the whiteboard (plus its own consolidated context and
   any external context) and continues the task, streaming its reasoning and
   answer.
7. The chatbot's metacognition and checklist are refreshed (one call).
8. The turn is appended to the chatbot context; if full, it is consolidated.
9. The turn is recorded on the tape ("almost everything is memorized"), plus
   any durable memories the chatbot emitted.
10. The tape grows; a new group and agent are created when a group is full.
```

## 9. Metacognition and Checklists

- The **chatbot** has a metacognition ("Understanding") and a checklist,
  produced together by a single metacognitive LLM call after each reply, from
  the previous understanding/checklist, the subject and the latest exchange.
  They survive whiteboard consolidation.
- Each **memory agent** has a checklist, produced in the same fused call that
  produces its annotations (Section 7).
- Both are dynamic: they evolve every turn, dropping what no longer matters and
  adding what is new.

## 10. Scaling and Parallelism

All memory agents run concurrently (bounded by a configurable worker pool).
Because the checklist is fused into the annotation call, there is ONE LLM call
per agent per cycle, not two.

## 11. Consolidation

- **Whiteboard consolidation**: when the whiteboard exceeds its threshold, a
  single consolidator call summarizes the accumulated state into a compact note
  after persisting that state to the tape (lossless continuity). It clears
  `context`, `pending` and `annotations` but keeps `subject`, `objective`,
  `metacognition` and `checklist`.
- **Chatbot context consolidation**: the chatbot's own conversation context is
  consolidated on its own schedule, independently of the whiteboard, when it
  exceeds its threshold.
- **Tape rollup**: the oldest active records (beyond `keep_recent`) are
  summarized into a single `memory` record and the sources are archived
  (`status: archived`), keeping the tape bounded without losing the essentials.
- **Provenance and rehydration**: a rollup record carries `derived_from` (the
  ids of its archived sources). `rehydrate <id>` returns those sources (even
  archived), optionally reactivating them, so physical persistence does not
  become cognitive unavailability. Recall of a rollup also returns its source
  summaries as `rehydrated`.

## 12. Topics, Router and Auto-topic

- Each topic owns its own tape, manifest, whiteboard and context
  (`topics/<id>/`), named by creation date/time with an optional label.
- The **router** is a single LLM call that, given the message and the topic list
  (id, name, label, summary), returns the matching topic id or `null`.
- **Auto-topic** policy (configurable): `day` (one topic per day, default),
  `idle` (new topic after N hours of inactivity) or `off` (manual). When the
  router returns `null`, the auto-topic policy decides the "current" topic.

## 13. RAG, Web Search and Attachments

- **RAG**: `.txt` documents stored under `documents/`; relevant chunks are
  retrieved by **BM25** lexical scoring for the current message. If an
  OpenAI-compatible embeddings model is configured, semantic ranking
  (cosine similarity) is used instead, falling back to BM25.
- **Web search**: a keyless DuckDuckGo lookup for the current message. The
  desktop app supports `auto` (a heuristic decides when the question needs
  current info), `off`, or `always`.
- **Attachments** (explicit exception): an attached `.txt` file is read, split
  into chunks, and each chunk is appended to the session's tape as a record of
  type `attachment` whose summary says it is an attached text. Chunks are
  secret-scanned and deduplicated by file + content hash (`source`). When a
  memory agent annotates an attachment chunk, recall returns its full text as
  `attached_content` so the chatbot can read it.
- External context (RAG/web) is handed ONLY to the main chatbot, in a separate
  `## External context` section; it MUST NOT touch the tape. Attachments are the
  one intentional, labeled exception.

## 14. Sessions and Cross-session Recall

- A **session** is a self-contained memory store (`sessions/<id>/`) with its own
  tape, manifest, whiteboard and context. Each opencode session owns one tape.
- A **session index** (metadata: id, created/updated time, summary, record
  count) is maintained per session (`session.json`).
- **Cross-session recall**: when enabled, recall also searches the *other*
  sessions' tapes with BM25 and returns the top hits as `past_hits`, so a new
  session can recall decisions made in previous ones. The current session's
  tape/whiteboard/agents remain primary; past hits are advisory context.

## 15. Recall Optimizations

To avoid running the LLM agents on every message unnecessarily:

- **Cache**: an identical subject is served from the previous recall result
  without any LLM call.
- **Trivial filter**: short/acknowledgement messages reuse the previous recall.
- **Empty tape**: with no active memories there are no agents, so recall makes
  no LLM calls.

### 15.1 Memory Router (opt-in)

Consulting every agent each turn costs O(N / capacity) LLM calls. The router is
an optional layer that selects which partitions to consult:

- Each group carries a **digest** (a short summary), produced by the agent's
  fused call (`agent.digest`) or derived deterministically when stale.
- `router_mode`:
  - `llm` (default when enabled) — one LLM call ranks the digests and returns
    the relevant group ids. Semantic; works with the existing chat provider.
  - `embedding` — cosine similarity between the query and the digests
    (requires an OpenAI-compatible embeddings provider, e.g. a local Ollama).
  - `lexical` — BM25 over the digests (no extra call; opt-in only).
- No match → full sweep (`router_fallback: full`), or the most recent K.

`router_enabled` is **false by default**. The semantic router is a cost
optimization, and measurements show it trades recall for calls:

*Synthetic benchmark* (topically-pure partitions; 24-48 memories):

| arm | recall | calls/query |
|-----|--------|-------------|
| BM25 retrieval | 0.33 | 0.0 |
| agents (full sweep) | 1.00 | 12.0 |
| agents + lexical router | 0.39 | 5.5 |
| agents + embedding router (`nomic-embed-text`) | 1.00 | 5.0 |
| agents + LLM router | 1.00 | 3.0 |

*External benchmarks* (evidence-session recall; cheap arms over all questions,
agents over subsamples; dense = local embeddings):

| dataset | BM25 | vector (dense) | agents (full) |
|---------|------|----------------|---------------|
| LongMemEval (100q) | 0.85 | 0.94 | - |
| LongMemEval (50q) | 0.76 | 0.92-0.96 | - |
| LongMemEval (30q) | 0.80 | 0.93 | 0.93 |
| LoCoMo (150q) | 0.74 | 0.45-0.63 | - |
| LoCoMo (50q) | 0.78 | 0.56 | 0.90 |
| LoCoMo (30q) | 0.70 | 0.53 | 0.83 |

The agentic advantage over similarity retrieval is **benchmark-dependent**:
on LongMemEval the dense retriever beats BM25 and ties the agents (no agentic
advantage); on LoCoMo the agents lead clearly while dense retrieval is the
weakest arm. The advantage emerges where relevance is contextual/conversational
rather than directly similar — not as a universal win over RAG. The router
cuts calls (~10 -> ~5) but loses recall, so it stays opt-in; lexical routing is
unsafe (measured ceiling 0.61).

### 15.2 View Router and recall-safe cascade

Instead of inferring relevance from the query alone, the **view router** uses
the write-time organization (section 4.3) as a structural retrieval prior:

- `router_mode: views` — select views, then run agents only on the records in
  them. `view_router_mode`:
  - `lexical` — BM25 over each view's name + member summaries (`rank_views`).
  - `llm` — one LLM call receives the view digests plus the whiteboard and
    returns `{"views":[...],"confidence":0..1}` (contextual selection).
- `router_mode: cascade` — recall-safe fallback. Level 1 selects views; if the
  selection is weak (`no_annotation` OR `low_view_score`), level 2 expands to
  co-occurring views (`related_views`, structural views excluded), level 3
  falls back to the similarity router, level 4 to a full sweep. Fallback
  reasons are recorded (`no_annotation`, `low_view_score`, `both`,
  `expansion_failed`, `similarity_failed`) so failures can be attributed to
  the router or to the topology.
- An explicit `views=[...]` argument overrides routing (used for diagnostics
  and manual filtering).

`recall` returns a `routing` object with `mode`, `level`,
`fallback_reasons`, `selected_views`, `view_score`, `records_consulted`,
`records_total`, `records_level1` and `groups_consulted` (plus `consulted_ids`
when `debug=true`). This separates "the router picked the wrong region" from
"the agents missed the memory" instead of mixing both into one recall number.

Measured on the controlled topology benchmark (`eval/view_router_bench.py`,
synthetic fixture with known views, 71 memories, 24 tasks, `deepseek-v4-flash`):

| arm | view recall | complete evidence | agent recall | calls/query | reduction |
|-----|-------------|-------------------|--------------|-------------|-----------|
| full (ceiling) | - | 1.00 | 1.00 | 15.0 | 0.00 |
| similarity router | - | 0.83 | 0.83 | 3.9 | 0.79 |
| view-BM25 | 0.69 | 0.96 | 0.96 | 10.7 | 0.67 |
| view-LLM (n=15) | 1.00 | 1.00 | 1.00 | 15.5 | 0.46 |
| view-oracle (ceiling) | 1.00 | 1.00 | 1.00 | 7.4 | 0.86 |
| cascade-BM25 | 0.69 | 0.96 | 0.96 | 10.3 | 0.69 |
| cascade-LLM (n=15) | 1.00 | 1.00 | 1.00 | 15.1 | 0.49 |

Readings: the similarity router loses evidence on multi-memory and cross-view
questions (complete evidence 0.83 vs 1.00) while cutting calls to 3.9; the
lexical view router preserves more evidence (0.96) but its view recall is 0.69
(it also selects broad `time/` views, inflating calls); the oracle (ground-truth
views) reaches 1.00 at 7.4 calls and 0.86 reduction, so the gap to the oracle is
the *router*, not the topology. The cascade barely triggered (fallback 0.04)
because "some annotation exists" is a false-confidence signal: agents annotate
something even when the target region was missed, so the fallback did not
recover the 9 view-miss questions. The view-LLM arms were throttled by the
provider at n=15 (no adversarial tasks); calls for the reconstructed arms are
estimated as router calls + groups consulted. Full analysis in the manual,
Part IV.

### 15.3 Dimension-aware routing and coverage (v0.5b)

Views have different cognitive roles, so they are grouped into **dimensions**:
`semantic` (`topic/*`, `subject/*`), `temporal` (`time/*`) and `structural`
(`type/*`, `source/*`). With `view_dimension_mode: auto`, the router builds a
`RoutingPlan` (dimensions + views + combination) instead of a flat view list:

- **Dimension selection**: deterministic markers (`detect_dimensions`:
  default semantic; temporal parser for dates/ranges/recency; type/source
  markers) for `view_router_mode: lexical`, or one LLM call returning
  `{"dimensions":[...],"views":[...],"confidence":...}` for `llm`.
- **Combination**: single dimension -> union of its views; multiple dimensions
  -> **intersection** of their record sets, with progressive relaxation when
  the strict intersection is empty: `strict` -> `relaxed_semantic` (next
  semantic candidate) -> `relaxed_temporal` (drop the time constraint) ->
  `union_fallback`. The mode and size are recorded (`intersection_mode`).
- **Coverage** (`coverage_mode`): a recall-local signal (`complete` /
  `partial` / `uncertain`) that is never persisted on the agent. Sources:
  `agents` (telemetry from the fused agent call), `structural` (are the
  annotated memories inside the planned views?), `both`, or `judge` (one extra
  LLM call over the retrieved memories). In `router_mode: cascade`, a signal
  that is not `complete` triggers expansion -> similarity -> full sweep.

Measured on the frozen 32-task fixture (n=32, `deepseek-v4-flash`):

| arm | view rec | view prec | dim rec | dim prec | recovery | complete evid | calls | reduction |
|-----|----------|-----------|---------|----------|----------|---------------|-------|-----------|
| C1 view-BM25 (v0.5a) | 0.67 | 0.25 | 0.83 | 0.42 | 0.97 | 0.97 | 10.9 | 0.63 |
| C2 view-LLM (v0.5a) | 0.88 | 0.36 | 0.99 | 0.89 | 1.00 | 1.00 | 15.2 | 0.49 |
| C1d dimension-aware | 0.81 | 0.35 | 1.00 | 0.82 | 0.94 | 0.91 | 9.6 | 0.70 |
| C2d dimension-aware | 0.79 | 0.47 | 1.00 | 0.81 | 0.84 | 0.59 | 7.1 | 0.86 |
| C1d + coverage judge | 0.81 | 0.35 | 1.00 | 0.82 | 0.94 | 0.91 | 10.6 | 0.70 |
| D1d cascade + judge | 0.81 | 0.34 | 1.00 | 0.82 | 0.95 | 0.94 | 12.4 | 0.66 |
| C3 oracle | 1.00 | 1.00 | 0.81 | 0.91 | 1.00 | 1.00 | 7.7 | 0.84 |

Readings (v0.5b):

- **M1 — dimensions help the region, cost and temporal tasks**: C1d raises view
  recall 0.67 -> 0.81 and dimension precision 0.42 -> 0.82 while cutting calls
  10.9 -> 9.6 and raising reduction 0.63 -> 0.70; temporal questions are fully
  covered at ~2.6 calls. The strict intersection costs a little evidence
  (0.97 -> 0.91) on cross-view composition and adversarial cases.
- **C2d is a negative result**: the LLM dimension plan over-restricts
  (complete evidence 0.59) even though it is the cheapest arm (7.1 calls,
  0.86 reduction) — cheap is not enough.
- **M2 — free coverage signals are uncalibrated**: agent-declared coverage says
  `partial` on 32/32 queries (100% fallback waste); the structural check says
  `complete` on 32/32 (100% false-safe on the incomplete cases). The judge is
  better but still weak: false-safe 2/3, fallback waste 38%.
- **M3 — the cascade recovers little at real cost**: with the judge, complete
  evidence 0.91 -> 0.94 but calls 9.6 -> 12.4 and reduction 0.70 -> 0.66. The
  primary target (>= 0.98) is not met; the oracle (1.00 at 7.7 calls / 0.84
  reduction) shows the remaining headroom is in the router and the coverage
  signal, not the topology.
- **M3b — per-required-view coverage is waste-calibrated but gap-blind**: the
  plan keeps the ranked candidate views beyond the selected ones
  (`candidate_views`/`candidate_scores`); with a relative score threshold
  (>= 0.6 of the top), an uncovered candidate is a gap and the cascade expands
  straight to it (`coverage_mode: views`). Measured: 31/32 `complete` with only
  1 wasted fallback, but none of the 3 real misses is flagged (false-safe 3/3)
  — the required view never entered the lexical candidate ranking ("retrieval"
  vs "router"). End-to-end it is C1d plus one fallback (0.91 complete evidence
  at 10.0 calls). The remaining gap is *semantic*: detecting a region the
  lexical ranking never proposed.
- **M3c — the judge with candidate digests does not fix it either**: giving the
  judge the digests of the plausible unselected views (`coverage_mode:
  judge_views`) improves calibration (false-safe 2/3, waste 4/29 vs v1's 38%)
  but not end-to-end: complete evidence stays 0.91 (10.6 calls), and on the
  cascade the expansion fails (0.91 at 11.5 calls).
- **M3d — pruning the broad selection is a precision lever**: with
  `view_prune: subject`, the view-LLM selection drops `subject/*` views when a
  `topic/*` view matched (they stay as candidates for coverage). Measured:
  complete evidence 1.00 -> 0.97, calls 15.2 -> 13.3, reduction 0.49 -> 0.63.
  A judge-driven cascade on top costs +4.6 calls with no evidence gain (the
  judge says `partial` on 6 tasks, 4 expansions fail, and temporal tasks
  explode to ~31 calls), so pruning alone is the better operating point.
- **Frontier on the frozen fixture (n=32)**: similarity 0.72 @ 4.0 calls / 0.79
  reduction; C1 view-BM25 0.97 @ 10.9 / 0.63; C1d dimension-aware 0.91 @ 9.6 /
  0.70; **C2 pruned view-LLM 0.97 @ 13.3 / 0.63**; C2 view-LLM **1.00 @ 15.2 /
  0.49**; oracle 1.00 @ 7.7 / 0.84. The recall-safe operating point is the
  view-LLM arm; pruning trades 3pp evidence for a 14pp reduction gain. Every
  cheap coverage signal tested either over-triggers (agents 100% partial) or is
  false-safe on the semantic gaps (structural 3/3, candidates 3/3, judge v2
  1/3 in the pruned cascade); precision without an oracle remains the open
  problem.

### 15.4 View agents (v0.6)

Instead of one agent per chronological group, `agent_mode: view` dispatches one
**perspective agent per selected view**: the same memory can be examined by
several perspectives without being duplicated (a topic agent looks for domain
facts and decisions; a temporal agent for evolution and sequence; a structural
agent for kinds and provenance). Each view agent sees every active memory in
its view, annotates what must be remembered and reports recall-local coverage.
The consulted set is the union of the selected views' records — the routing
intersection is not applied, because arbitration happens across the agents on
the whiteboard.

Measured on the frozen fixture (n=32, `deepseek-v4-flash`):

| arm | complete evidence | agent recall | calls | reduction |
|-----|-------------------|--------------|-------|-----------|
| C1d dimension (group agents) | 0.91 | 0.94 | 9.6 | 0.70 |
| C2 view-LLM (group agents) | 1.00 | 1.00 | 15.2 | 0.49 |
| C2 pruned (group agents) | 0.97 | 0.97 | 13.3 | 0.63 |
| view agents (lexical plan) | 0.97 | 0.98 | 3.0 | 0.57 |
| view agents (LLM plan) | 0.94 | 0.95 | 3.2 | 0.67 |
| **view agents (LLM + pruned)** | **1.00** | **1.00** | **5.0** | 0.59 |
| C3 oracle (ground-truth views, group agents) | 1.00 | 1.00 | 7.7 | 0.84 |

Readings: view agents dominate the frontier. The LLM plan + subject pruning +
view agents reaches complete evidence 1.00 in all seven categories at 5.0
calls/query — 3x fewer than the best group-agent arm and below the oracle's 7.7
calls. The perspective prompts make the per-view annotation stronger than the
per-group annotation (the pruned group-agent arm scored 0.97 on the same
selection). The lower reduction (0.59) reflects deliberate perspective
redundancy: overlapping views let the same memory be examined by more than one
agent.

**Persistent view state.** Each view keeps its own state in the manifest
(`view_agents`): digest, checklist and record counts, mirroring the group
agents. The fused view call refines the checklist and rewrites the digest every
turn, and the coverage judge prefers the persisted digest when describing
unselected candidate regions. Coverage itself is stored only as a diagnostic
(`last_coverage`), never fed back into the prompt. A re-run with persistence
measured 0.97 @ 4.9 calls / 0.64 reduction (one task short of 1.00); the
difference is router variance, not a persistence regression — see below.

**Router stability limitation.** Across two identical runs of the same arm, the
LLM view selection differed on **20/32 tasks** (temperature 0). Evidence stayed
0.97-1.00 because the selected views still covered the required memories, but
the selection itself is not stable; the lexical plan is deterministic (0.97 @
3.0 calls). Reproducibility-sensitive deployments should prefer the lexical
plan or pin the selection.

### 15.5 Dimension boards (v0.6c)

With `whiteboard_mode: dimension`, each dimension keeps its own working board
(`Whiteboard.boards`): a semantic board, a temporal board and a structural
board. View agents read the board of their dimension and their annotations are
merged back into it, so each dimension maintains a different working memory of
the same work while the primary board keeps the union for compatibility.
Boards persist inside `whiteboard.json` (old files load with no boards) and are
excluded from the primary's consolidation size — each board is bounded by the
per-board annotation budget.

Measured (n=32, deterministic lexical plan): view agents with dimension boards
score 0.97 complete evidence @ 3.1 calls / 0.57 reduction — identical to the
single-board arm (0.97 @ 3.0 / 0.57), i.e., no retrieval regression. The value
is architectural: per-dimension understanding, checklist and annotations are
now separate and inspectable, ready for dimension-specific consolidation and
for multiple active boards selected by context.

### 15.6 Per-dimension consolidation and multi-turn continuity

- **Per-dimension consolidation**: in `whiteboard_mode: dimension`, each board
  is consolidated independently when it exceeds the threshold: its working
  state is persisted to the tape first (lossless continuity), then shrunk;
  other boards are untouched. Dimension boards are excluded from the primary's
  consolidation size.
- **Multi-turn continuity benchmark** (`eval/continuity_bench.py`): 3 scenarios
  x 3 turns on the same machine, comparing persistent state with a stateless
  arm (state cleared every turn). Both arms scored complete evidence 1.00 and
  agent recall 1.00 on all turns; persistence accumulated more state
  (checklists 6375 vs 4577 chars; board annotations 48 vs 34) at a similar cost
  (4.1 vs 3.9 calls). On this fixture persistence is a continuity guarantee,
  not an evidence gain — the turns do not *learn* new memories (the chatbot
  path is what writes them), which is the next continuity experiment.

### 15.7 External data (Fase 2): write-time auto-tagging

`eval/tag_sessions.py` labels LongMemEval/LoCoMo sessions with a coarse topic
taxonomy (12 reusable topics) plus a free subject slug, in batched LLM calls
(8 sessions per call) cached per session id under `eval/data/tags_*.json`.
`external_bench.py --tag` applies the labels as `topic/*`/`subject/*` views at
build time, so the dimension-aware view router and the view agents run on
external data with inferred views.

First look (LongMemEval, n=8 questions, 389 tagged sessions):

| arm | evidence recall | calls/query |
|-----|-----------------|-------------|
| bm25 | 0.88 | 0.0 |
| agents (full) | 1.00 | 10.1 |
| agents (view, lexical plan) | 0.88 | 3.0 |

The pipeline works end-to-end (inferred views + dimension routing + view
agents) at 3x lower cost, but the coarse taxonomy loses one question (7/8).
This is a small sample and the taxonomy is deliberately reusable; a finer
tagger or a larger sample is the next step.

### 15.8 CLI and app integration

- CLI: `recall --agent-mode {group,view} --whiteboard-mode {single,dimension}
  --dimension-mode {off,auto}` override the config for a single recall; choosing
  `view` enables the view router automatically.
- Desktop app: the settings dialog exposes a **Memory mode** selector
  (partition agents / view agents / view agents + dimension boards) that maps
  to `agent_mode`/`whiteboard_mode` (and enables the view router for view
  modes).

### 15.9 Attention state (v0.7)

`Whiteboard.attention` is a session-level, recency-weighted prior over views:
`{view: weight 0-1}`, global and independent (not normalized per dimension).
It decays by neglect and saturates on reinforcement:

    w[v] *= decay
    w[v] += boost * (1 - w[v])        # selected this turn
    w[v] += found_boost * (1 - w[v])  # its agent annotated evidence

`attention_mode`:
- `prior`: the lexical plan blends the normalized router score with
  `attention_weight * attention[v]`; active views are guaranteed **candidates**
  (not slots — a new topic's router score must be able to outrank the prior).
- `context`: the LLM plan prompt lists the active views ("the new message may
  refer to them").
- `state`: `prior` plus a gate: if the message is anaphoric AND the attention
  is concentrated (`top1 >= attention_gate_min`, `margin >= attention_gate_margin`),
  the active views are reused without a router call.

Every selected view records `router` / `attention` / `final` scores and a
`contribution` (`router` | `attention` | `both`), so a view chosen by continuity
can be told apart from one chosen by similarity. Coverage feedback: `complete`
keeps the found boost, `partial` halves it, `uncertain` drops it.

Measured (frozen fixture, `deepseek-v4-flash`):

**Stability** (N=5 repetitions x 8 focused tasks, fresh session each):

| arm | modal selection | mean Jaccard | complete evidence |
|-----|-----------------|--------------|-------------------|
| view-LLM | 0.75 | 0.80 | 0.90 |
| view-BM25 | 1.00 | 1.00 | 0.875 |
| view-BM25 + attention prior | 1.00 | 1.00 | 0.875 |

The LLM plan's selection is not reproducible (modal 0.40-1.00 per task); the
lexical plan, with or without the prior, is deterministic. The prior does not
change single-turn stability because the lexical router already resolves the
query — its value is on follow-ups.

**Conversation** (2 scenarios x 4 turns, anaphoric follow-ups and a topic shift):

| arm | anaphora evidence | anaphora calls | shift evidence | old-topic residual |
|-----|-------------------|----------------|----------------|--------------------|
| lexical, attention off | 1.00 | 10.7 | 1.00 | 0.00 |
| lexical + prior | 1.00 | 5.7 | 1.00 | 0.56 |
| lexical + state | 1.00 | 5.7 | 1.00 | 0.56 |
| LLM, attention off | 0.67 | 3.3 | 1.00 | 0.00 |
| LLM + state | 1.00 | 3.3 | 1.00 | 0.56 |

Readings: with attention off, an anaphoric follow-up ("e por que mudamos
isso?") falls back to the full sweep (15-16 calls) or the LLM router misses it
(0.67 evidence). The prior/state resolves the reference from the active views
at ~5.7 calls with complete evidence, and LLM+state recovers the anaphora the
LLM router missed. After a topic shift the new topic is covered (1.00) and the
old topic's attention decays 0.94 -> 0.56. An earlier version that *forced*
active views into the selection starved the new topic (0.00 evidence); the fix
was to guarantee active views as candidates, not slots — exactly the
attention-stickiness failure the benchmark was designed to catch.

### 15.10 End-to-end answer accuracy (v0.8)

`eval/e2e_bench.py` closes the loop: `recall -> whiteboard -> main chatbot ->
answer -> LLM judge (vs gold)`. Six arms isolate the contribution of each
layer: `no_memory` (floor), `bm25` (flat RAG), `agents_group` (v0.4 group
agents), `agents_view` (view agents + dimension plan + attention), and
`agents_view_ctx` (same retrieval plus the **full text** of the annotated
memories). `oracle` injects the gold evidence directly (ceiling). Every boundary
is snapshotted to `eval/out/e2e_<arm>.jsonl` (`retrieved_ids`,
`whiteboard_rendered`, `attention`, `answer_prompt_final`, `answer`, `judge`),
so a wrong answer is attributable to retrieval, context loss, the answerer or
the judge. The judge is 3-way (`correct|partial|incorrect`) with a frozen
prompt (`v1`), pointwise and blind to the arm; a stratified ~25% sample gets a
second pass for agreement.

Measured on the frozen fixture with 32 authored gold answers
(`eval/gold_answers.json`; questions and routing ground truth unchanged):

| arm | evidence | strict | lenient | AUR | fact_cov | calls |
|-----|----------|--------|---------|-----|----------|-------|
| no_memory | 0.00 | 0.00 | 0.12 | - | 0.15 | 1.0 |
| bm25 | 0.28 | 0.31 | 0.66 | 1.00 | 0.48 | 1.0 |
| agents_group | 1.00 | 0.62 | 0.88 | 0.62 | 0.72 | 16.1 |
| agents_view | 0.97 | 0.72 | 0.94 | 0.74 | 0.73 | 4.1 |
| **agents_view_ctx** | 0.97 | **0.88** | 0.97 | **0.90** | 0.99 | 4.0 |
| oracle | 1.00 | 0.94 | 0.97 | 0.94 | 1.00 | 1.0 |

Readings:

- **H1 confirmed**: view-agent retrieval raises final-answer accuracy far above
  no-memory and BM25, and beats group agents (0.72-0.88 vs 0.62) at ~4x fewer
  calls (4.1 vs 16.1).
- **H2 confirmed — the bottleneck was context loss, not retrieval**: with the
  same retrieval (evidence 0.97) and cost, adding the full memory content
  raises strict accuracy 0.72 -> 0.88 and the **Answer Utilization Rate**
  `P(correct | evidence complete)` 0.74 -> 0.90, with `fact_cov` 0.73 -> 0.99.
  The annotation notes lose the factual payload (Phase 0 showed notes turning
  facts into meta-rules and dropping details such as "500-question").
- **Failure taxonomy** (strict-incorrect): `agents_view` had 3 context-loss
  errors; `agents_view_ctx` has 0. The remaining `agents_view_ctx` misses are
  answerer errors (a temporal misreading) and one retrieval gap (the known
  lexical "retrieval" vs "router" miss). `agents_group` had 9 answerer + 3
  context-loss errors.
- **Oracle caveat**: 0.94 is a lower bound — the answerer refuses facts passed
  as "external context" on temporal questions (its prompt treats extra_context
  as documents, not long-term memory), so the true answerer ceiling is higher.
- **Judge audit**: 7-8/8 agreement per arm (0.88-1.00) on the stratified
  sample; the disagreements fall on the hard partial/incorrect cases.

The "rehydrated evidence payload" is therefore justified by H2 but not yet
implemented: the next step is to deliver the needed slice of a memory's content
(not only the note) under a budget, rather than whole memories.

### 15.11 Budgeted evidence rehydration (v0.9)

The annotation says *why* a memory matters; the evidence payload delivers *what
it says*. `evidence_payload: budgeted|full|off` builds a deterministic,
recall-local payload for the kept annotations:

- **Ordering**: by relevance (then id), so the most important facts come first.
- **Allocation**: a floor per item (`evidence_payload_min_item`, default 200)
  then water-filling proportional to relevance, capped at each item's actual
  size — the budget is used fully when the content is larger.
- **Content**: `[id | type | date]` + summary + why; the summary is preserved
  whole whenever possible and the `why` is truncated first. Rollups
  (`derived_from`) are **rehydrated** from their archived sources instead of a
  second copy.
- **Ephemeral**: the payload is returned in the recall result
  (`evidence_payload`, `evidence_payload_chars`) and never merged into the
  persistent whiteboard; `run()` appends it to the assistant's context when
  enabled. Each item records `allocated_chars`, `used_chars`, `truncated` and
  `source` for budget analysis.

Measured with the v0.8 harness (judge v1):

**Controlled fixture (32 tasks)** — `agents_view_payload` vs the v0.8 arms:

| arm | evidence | strict | AUR | context chars |
|-----|----------|--------|-----|---------------|
| agents_view (notes only) | 0.97 | 0.72 | 0.74 | 0 |
| agents_view_ctx (full) | 0.97 | 0.88 | 0.90 | 1632 |
| **agents_view_payload (4000)** | 0.97 | **0.97** | **1.00** | 1928 |
| oracle | 1.00 | 0.94 | 0.94 | 242 |

The payload matched/exceeded full-injection accuracy and fixed tasks 11, 15 and
24 (partial/incorrect under full). The gain came from **relevance-ordered,
typed/dated evidence**, not from compression: the fixture's memories are short
(total < budget), so the budget never binds and the payload is not smaller.

**LongMemEval (12 questions, tagged sessions)**:

| run | strict | context chars | truncated items |
|-----|--------|---------------|-----------------|
| full (6000) | 0.33 | 3767 | 0 |
| payload (4000) | 0.33 | 4000 | 32 |
| payload (2500) | 0.25 | 2458 (65% of full) | 33 |

Readings: the payload adds a **hard context cap** (bounded by construction)
and preserves accuracy at 4000; at 65% of the full context the strict accuracy
dropped by one task (12-question sample). **H3 is partially confirmed**: the
accuracy claim holds on the controlled fixture, but the efficiency claim
(payload <= 70% of full with parity) is not cleanly demonstrated — the fixture
never exceeds the budget and the external sample is too small. The absolute
external accuracy (0.33 for both arms) is a downstream/ingestion limitation to
investigate separately.

### 15.12 External ingestion ablation (v0.9b)

The external harness ingested each session as `summary = text[:300]` and
`why = text[:2000]`. LongMemEval sessions have a median of ~10.4k characters,
so ~80% of every session was being discarded **before** retrieval. The ablation
varies only that cap (`--ingest-why 2000|4000|8000|0`) while holding everything
else fixed (same 12 questions, view agents + payload 4000, answerer and judge
v1), and measures **Gold Fact Retention** (GFR): does the fact needed to answer
survive ingestion? (one judge call over the evidence session's ingested text).

| ingestion | GFR | evidence | strict | AUR | context chars |
|-----------|-----|----------|--------|-----|---------------|
| 2000 (current) | 0.42 | 0.75 | 0.33 | 0.44 | 3170 |
| 4000 | 0.50 | 0.75 | 0.33 | 0.44 | 3782 |
| 8000 | 0.58 | 0.75 | 0.42 | 0.56 | 3782 |
| full text | **0.83** | 0.75 | **0.50** | **0.67** | 4003 |

Readings:

- **The ingestion cap was a real bottleneck**: at 2K only 42% of the gold facts
  survived ingestion; with the full session text, 83% survive and strict
  accuracy rises 0.33 -> 0.50 (AUR 0.44 -> 0.67).
- **Evidence recall stayed constant (0.75)**, confirming the loss was upstream
  of retrieval, not in the router: the right session was still found, but its
  content had been cut at write time.
- The low external accuracy reported earlier (0.23-0.33) is therefore **partly
  a harness artifact**, not purely an architecture limit. The product's
  attachment ingestion chunks text (600-char overlapping chunks) instead of
  truncating, so it does not lose content this way.
- GFR 0.83 < 1.00 at full text: some facts are spread across sessions or the
  judge is strict; the remaining downstream gap (GFR 0.83 vs strict 0.50)
  points to the answerer/prompt as the next target (v0.9a).

`external_bench.py` now exposes `--ingest-why` (default 2000 keeps historical
comparability; future runs should use 8000 or 0).

### 15.13 H3 at scale — the compression curve (v0.9c)

LongMemEval 50 questions, **full ingestion** (`--ingest-why 0`), everything else
frozen (same questions, tagging, view agents, answerer, judge v1). Only the
payload budget varies. Gold Fact Retention is measured as a control.

| arm | GFR | evidence | strict | lenient | AUR | context chars | Δstrict | reduction |
|-----|-----|----------|--------|---------|-----|---------------|---------|-----------|
| full (v0.9 ctx) | 0.86 | 0.74 | 0.58 | 0.66 | 0.78 | 12947 | - | 0% |
| payload 6000 | 0.80 | 0.74 | **0.60** | 0.64 | 0.78 | 5539 | +0.02 | **57%** |
| payload 4000 | 0.84 | 0.74 | 0.56 | 0.62 | 0.76 | 3836 | -0.02 | **70%** |
| payload 2500 | 0.80 | 0.74 | 0.52 | 0.66 | 0.68 | 2430 | -0.06 | **81%** |

Readings:

- **H3 is confirmed on the relative criterion**: payload 6000 matches the full
  context (0.60 vs 0.58 strict; AUR 0.78 both) with a **57% context reduction**,
  and payload 4000 is within noise (-0.02 strict, -0.02 AUR) at a **70%
  reduction**. The user's "≤70% with parity" target is met at 4000.
- **There is a compression knee around 4000**: 2500 loses real accuracy
  (-0.06 strict, -0.10 AUR), so the payload cannot shrink indefinitely; the
  saturation point sits between 4000 and 6000 (6000 adds nothing over 4000).
- **Controls held**: evidence recall identical (0.74) and GFR ~0.80-0.86 across
  arms (the small spread is judge noise on identical ingested text).
- **Absolute targets (strict >= 0.85, AUR >= 0.88) are not met on LongMemEval**
  even by the full context (0.58 / 0.78) — the remaining gap is downstream
  (answerer/prompt), which is exactly what v0.9a targets. As anticipated, the
  informative criterion for the external benchmark is relative parity, not the
  absolute threshold.
- The full arm's 12,947 chars reveal that `full_text`'s first block bypasses
  its 6,000-char cap (the budget check only applies after the first item), so
  the baseline is effectively unbounded for one long session.
- Judge audit: 0.92 / 0.92 / 0.83 / 0.75 agreement (the 2500 arm produces more
  partial/vague answers, where the judge disagrees more).
- One session per machine was skipped by the secret scanner (M0005); the
  harness records `ingest_skipped` and never bypasses the gate.

### 15.14 H4 — memory-aware answer prompt (v0.9a, refuted)

Hypothesis H4: with the same retrieval and evidence payload, a prompt that
explicitly tells the answerer that the context contains recalled persistent
memory (history, not external documents) would raise final accuracy. Arms:
`agents_view_payload` (payload 4000, current prompt), `agents_view_payload_memory`
(same + memory-aware prompt), and `oracle_memory` (gold evidence + memory-aware
prompt), all on LongMemEval 50q with full ingestion; `oracle` (base prompt) was
added afterwards as the ceiling.

| arm | evidence | strict | AUR | context chars | dominant error kinds |
|-----|----------|--------|-----|---------------|----------------------|
| payload 4000 (base) | 0.74 | **0.56** | 0.76 | 3836 | 16 insufficient evidence, 4 temporal, 1 reasoning, 1 abstention |
| payload 4000 (memory prompt) | 0.74 | 0.50 | 0.68 | 3791 | 19 insufficient evidence, 5 temporal, 1 abstention |
| oracle (base) | 1.00 | 0.52 | 0.52 | ~14k | 19 insufficient evidence, 2 temporal, 1 reasoning, 2 abstention |
| oracle (memory prompt) | 1.00 | 0.52 | 0.52 | 14751 | 22 insufficient evidence, 1 temporal, 1 ignored |

Readings:

- **H4 is refuted**: the memory-aware prompt did not improve accuracy — it
  slightly hurt the payload arm (0.56 -> 0.50 strict, AUR 0.76 -> 0.68) and
  changed nothing for the oracle (0.52 both). The controls held (evidence 0.74,
  GFR ~0.78-0.86).
- **The LongMemEval answerer ceiling is ~0.52-0.56**, and the payload arm even
  edges out the oracle (0.56 vs 0.52), which only receives the gold evidence
  sessions — the whiteboard understanding and the broader annotated context
  help.
- **The dominant remaining failure is evidence insufficiency** (16-22 of the
  ~22-25 errors per arm), even for the oracle with the full evidence session.
  Temporal misreading — the phenomenon that motivated H4 — is small (1-5).
  The bottleneck is therefore *evidence sufficiency/aggregation* (answers that
  span sessions or need reasoning), not the answerer's interpretation of
  memory.
- Negative results are recorded as such: the prompt variant is implemented
  (`memory_aware=True` in `run_main_chatbot`) but not enabled by default.

### 15.15 H5' — Temporal provenance restoration (confirmed)

The external loader dropped `haystack_dates` and `question_date`, so every
session fell into the ingestion month and the payload header showed the
ingestion date. `--ingest-dates` restores the real timestamps (ISO, to the
minute), makes the `time/*` views real, and appends the question date to the
task as provenance. Everything else is frozen (full ingestion, prompt, model,
judge v1, budget 4000).

| arm | evidence | strict | lenient | AUR | temporal total | temporal \| evidence complete |
|-----|----------|--------|---------|-----|----------------|-------------------------------|
| payload 4000 (base) | 0.74 | 0.56 | 0.62 | 0.76 | 0.29 (4/14) | 0.44 (4/9) |
| payload 4000 + dates | 0.72 | **0.64** | 0.70 | **0.89** | **0.64 (9/14)** | **1.00 (9/9)** |
| oracle (base, 6k cap) | 1.00 | 0.52 | 0.58 | 0.52 | - | - |
| oracle + dates (no cap) | 1.00 | 0.54 | 0.56 | 0.54 | - | - |

> **Correction (harness bug).** The first H5'/H6a runs did not deliver the
> evidence payload to the answerer (the new arms were missing from the
> context-building branch), so they measured whiteboard-only answers; the
> numbers were 0.56/0.72 and `fact_coverage` 0.16. After the fix the payload is
> delivered (`fact_coverage` 0.83) and the results reverse: the date
> restoration is the fix. The buggy snapshots are kept as `*_BUGGY.jsonl`.

By question type (base -> dates):

| type | base | dates | n |
|------|------|-------|---|
| **temporal-reasoning** | 0.29 | **0.64** | 14 |
| single-session-user | 0.60 | 0.60 | 15 |
| multi-session | 0.77 | 0.77 | 13 |
| knowledge-update | 0.33 | 0.00 | 3 |
| single-session-assistant | 1.00 | 1.00 | 3 |

Readings:

- **H5' is confirmed**: with the payload delivered, restoring the real session
  timestamps and the question date lifts temporal-reasoning 0.29 -> 0.64
  (4 -> 9 of 14) and **temporal | evidence complete 0.44 -> 1.00 (9/9)**; all
  four audited arithmetic/anchor errors are fixed. Overall strict 0.56 -> 0.64
  and AUR 0.76 -> 0.89 at equal evidence (0.72 vs 0.74), cost (4.4 calls) and
  fact coverage (0.83); GFR 0.84 -> 0.86.
- Controls held: GFR 0.84-0.86 and evidence recall 0.72-0.74 across arms.
- **Unlimited context is not a valid ceiling**: the oracle with *all* expected
  sessions and no cap collapses on multi-session (0.08 base, 0.00 dates) and
  scores below the 4000-char payload. More evidence can hurt; the payload's
  budget is protective. Earlier "oracle ceiling" readings need this caveat.
- The residual temporal failures (5/14) are all **evidence-incomplete**
  (retrieval misses): every temporal question whose evidence was complete was
  answered correctly (9/9). The next bottleneck for temporal reasoning is
  therefore retrieval, not the answerer.

### 15.16 H6a — temporal computation prompt (v0.11, refuted on temporal)

Hypothesis: with the same memories, real dates and 4000-char payload, an
explicit temporal-computation procedure (list timestamps → resolve relative
expressions against the session timestamp → use the question date as "now" →
compute → verify) improves temporal reasoning. The procedure is gated by
conservative markers (`how many days/weeks/months/...`, `how long`, `ago`,
`between ... and`, `how long/many ... before/after`, `days/weeks/... before/after`,
`what/which happened/came before/after`, `since`, `last week/month/year`), so
unrelated questions keep the base prompt.

| arm | evidence | strict | lenient | AUR | temporal total | temporal \| evidence complete |
|-----|----------|--------|---------|-----|----------------|-------------------------------|
| dates (base) | 0.72 | 0.64 | 0.70 | 0.89 | 0.64 (9/14) | **1.00 (9/9)** |
| dates + temporal prompt | 0.72 | 0.70 | 0.76 | 0.97 | 0.64 (9/14) | **1.00 (9/9)** |

Readings:

- **H6a is refuted on its own hypothesis**: on temporal questions the procedure
  adds nothing beyond the corrected dates (0.64 -> 0.64; temporal | evidence
  complete stays 1.00, 9/9). The dates alone fixed all four audited errors.
- The overall gain (0.64 -> 0.70 strict, AUR 0.89 -> 0.97) comes from
  non-temporal categories (knowledge-update 0.00 -> 0.67 on n=3;
  single-session-user 0.60 -> 0.67 on n=15) and is within small-n variance.
- Controls held: evidence 0.72 and GFR 0.86 both arms.
- The gate fired on 12/14 temporal questions and on 8/36 others (20/50 total),
  so the change was narrow as designed.
- Together with H4, the pattern is consistent: **prompt-only interventions do
  not move the answerer**; the remaining errors are composition/arithmetic
  capability, not instruction-following.

The pre-declared contingency (H6b, a dedicated temporal solver call) was NOT
executed: experiments stop here and the project moves to the v1.0 consolidation.

## 16. Failure Modes

| Failure | Required behavior |
|---------|-------------------|
| Memory agent call fails | SKIP that agent; continue with the others |
| Agent returns invalid JSON | Treat as an empty annotation set; checklist falls back to a deterministic list |
| Agent returns an unknown memory id | Ignore the annotation |
| LLM API key missing | Report a clear error; do not run the cycle |
| LLM 429/5xx | Retry with exponential backoff, then fail |
| Whiteboard parse error | Re-initialize an empty whiteboard |
| Corrupt tape line | SKIP the line; log a warning |
| Secret detected in a record | REFUSE the write; skip that record in the cycle |
| Concurrent writes | Serialized by a reentrant lock per process |

## 17. Configuration

| Key | Default | Meaning |
|-----|---------|---------|
| `capacity` | 500 | memories per group (per agent) |
| `whiteboard_budget` | 4000 | char budget for annotations |
| `consolidate_threshold` | 6000 | whiteboard size that triggers consolidation |
| `context_consolidate_threshold` | 6000 | chatbot context size that triggers its consolidation |
| `router_enabled` | `false` | enable partition routing |
| `router_mode` | `llm` | `lexical` / `embedding` / `llm` / `views` / `cascade` |
| `router_top_k` | 5 | partitions selected by the similarity router |
| `router_fallback` | `full` | fallback when the router finds nothing |
| `view_router_mode` | `lexical` | view selection: `lexical` (BM25) / `llm` (contextual) |
| `view_top_k` | 5 | views selected by the view router |
| `view_dimension_mode` | `off` | `auto` = dimension-aware plan with progressive intersection |
| `coverage_mode` | `off` | recall-local coverage signal: `agents` / `structural` |
| `cascade_min_score` | 0.0 | below this selection score the cascade expands |
| `cascade_expand_top_k` | 5 | co-occurring views added on expansion |
| `model` | `deepseek-v4-flash` | LLM model |
| `base_url` | `https://api.deepseek.com` | OpenAI-compatible endpoint |
| `api_key_env` | `DEEPSEEK_API_KEY` | env var holding the API key |

Values are validated and clamped on load.

On macOS, the desktop app stores the DeepSeek API key in the **Keychain**
(service `memory-machine`, account `api_key`), never in the settings file; the
CLI wrapper reads the key from the Keychain first, then the environment.

## 18. Open Questions

- Semantic (embedding) routing for the memory router; lexical routing is unsafe
  for lexically-distant queries (measured).
- Router false-negative rate and calibration of the full-sweep fallback.
- Agent retirement / rebalancing when the tape is reorganized or shrunk.
- Optimal `capacity` (default 500; prompts grow with it — see the
  per-agent full-text rendering in `agents.py`).
- Relevance threshold calibration and prompt tuning.
- Multi-session concurrency over a shared whiteboard.
- Objective evaluation metrics for continuity; ablation study and external
  benchmarks (LongMemEval, LoCoMo).

## 19. Experimental summary (v1.0)

The v0.5-v0.11 program tested one layer at a time, each result determining the
next experiment. Hypotheses and outcomes:

| # | Hypothesis | Outcome | Key numbers |
|---|------------|---------|-------------|
| H1 | Perspective agents over views retrieve better than partition agents | confirmed | 1.00 complete evidence @ 5.0 calls (all 7 categories) vs 15.2 for group agents; lexical plan 0.97 @ 3.0 |
| H2 | Delivering the factual content (not only the note) improves answers | confirmed | strict 0.72 -> 0.88 and AUR 0.74 -> 0.90 at the same evidence (0.97) and cost (4.0-4.1) |
| H3 | A budgeted payload preserves accuracy with far less context | confirmed (relative) | payload 6000 0.60 @ 5.5k vs full 0.58 @ 12.9k (-57%); 4000 0.56 @ 3.8k (-70%); knee at ~4000 |
| H4 | A memory-aware answer prompt fixes the remaining gap | refuted | payload 0.56 -> 0.50; oracle 0.52 both |
| H5 | Multi-session evidence aggregation is the bottleneck | refuted | multi-session was the easiest category (0.77); temporal-reasoning the worst (0.29) |
| H5' | Restoring real session/question timestamps improves temporal reasoning | confirmed | temporal-reasoning 0.29 -> 0.64; temporal \| evidence complete 0.44 -> 1.00 (9/9); overall 0.56 -> 0.64, AUR 0.76 -> 0.89 |
| H6a | An explicit temporal-computation procedure fixes the rest | refuted (on temporal) | temporal 0.64 -> 0.64; overall 0.64 -> 0.70 from small-n non-temporal cases |

Additional findings:

- **Ingestion is part of the system**: the external harness stored only 2k of
  each ~10.4k-char session (Gold Fact Retention 0.42); full text lifted GFR to
  0.83 and strict from 0.33 to 0.50 with evidence recall constant (0.75) — the
  loss was at write time, before retrieval.
- **More memory is not better memory**: an oracle that receives *all* expected
  sessions with no context cap (14.7k+ chars) collapses on multi-session
  (0.08 -> 0.00) and scores below the 4000-char payload. The budget is a
  protective filter, not only a cost optimization.
- **Prompt-only interventions do not move the answerer**: framing the context
  as memory (H4) was refuted; a task-specific temporal procedure (H6a) added
  nothing on temporal questions once the timestamps were correct, though a few
  small-n non-temporal cases moved. The measured fixes were architectural
  (payload delivery, real timestamps), not prompt-only.
- Remaining open problems: temporal-reasoning retrieval misses (all 5 remaining
  temporal errors are evidence-incomplete), the answerer ceiling on LongMemEval
  (0.64-0.70 with the corrected evidence), external tagger coarseness, and
  multi-turn continuity that actually *learns* new memories.

The central architectural statement:

> A good memory for an LLM is not the one that puts the most history into the
> context; it is the one that preserves, finds and delivers the right amount of
> evidence, with its provenance, at the right moment.
