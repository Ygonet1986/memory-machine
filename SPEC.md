# Memory Machine Specification

**Version:** 0.2
**Status:** Draft
**Date:** 2026-09-09

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

## 12. Topics, Router and Auto-topic

- Each topic owns its own tape, manifest, whiteboard and context
  (`topics/<id>/`), named by creation date/time with an optional label.
- The **router** is a single LLM call that, given the message and the topic list
  (id, name, label, summary), returns the matching topic id or `null`.
- **Auto-topic** policy (configurable): `day` (one topic per day, default),
  `idle` (new topic after N hours of inactivity) or `off` (manual). When the
  router returns `null`, the auto-topic policy decides the "current" topic.

## 13. RAG and Web Search (external context)

- **RAG**: `.txt` documents stored under `documents/`; relevant chunks are
  retrieved by deterministic keyword scoring for the current message.
- **Web search**: a keyless DuckDuckGo lookup for the current message (manual
  opt-in per message).
- External context is handed ONLY to the main chatbot, in a separate
  `## External context` section. It MUST NOT touch the tape, the whiteboard or
  the memory agents. It is not treated as settled memory.

## 14. Failure Modes

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

## 15. Configuration

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

## 16. Open Questions

- Agent retirement / rebalancing when the tape is reorganized or shrunk.
- Optimal `capacity` (default 50; to be calibrated).
- Tape deduplication / compaction for near-identical turn records.
- Relevance threshold calibration and prompt tuning.
- Multi-session concurrency over a shared whiteboard.
- Embedding-based RAG (currently keyword-based).
- Objective evaluation metrics for continuity.
