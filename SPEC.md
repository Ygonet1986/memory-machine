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
| type | REQUIRED | string | `decision`, `lesson`, `preference`, `bugfix`, `build`, `memory`, ... |
| summary | REQUIRED | string | One-sentence description |
| why | OPTIONAL | string | Reasoning |
| files | OPTIONAL | list | Related file paths |
| created_at | OPTIONAL | string | ISO 8601 timestamp |
| status | OPTIONAL | string | `active` (default), `archived`, `superseded` |

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

*External benchmarks* (evidence-session recall):

| dataset | BM25 | agents (full) | agents + router |
|---------|------|---------------|-----------------|
| LongMemEval (10q) | 0.90 | **1.00** | 0.60 |
| LongMemEval (20q) | 0.85 | **0.95** | 0.75 |
| LoCoMo (10q) | 0.60 | **0.90** | 0.60 |
| LoCoMo (20q) | 0.65 | **0.70** | 0.45 |

The router cuts calls (~10 -> ~5) but loses 5-40 recall points on real
conversational data, because the evidence partition is not always selected.
It is therefore opt-in, recommended only when the tape is large enough that a
full sweep is impractical. Lexical routing is unsafe (measured ceiling 0.61).

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
| `capacity` | 50 | memories per group (per agent) |
| `whiteboard_budget` | 4000 | char budget for annotations |
| `consolidate_threshold` | 6000 | whiteboard size that triggers consolidation |
| `context_consolidate_threshold` | 6000 | chatbot context size that triggers its consolidation |
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
- Optimal `capacity` (default 50; to be calibrated).
- Relevance threshold calibration and prompt tuning.
- Multi-session concurrency over a shared whiteboard.
- Objective evaluation metrics for continuity; ablation study and external
  benchmarks (LongMemEval, LoCoMo).
