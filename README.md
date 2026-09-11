# Memory Machine

Persistent memory for long-running projects: a conceptually infinite **tape**,
a growing layer of **memory agents** that watch it in parallel, and a shared
**whiteboard** that holds the work happening right now.

```
tape.jsonl (long-term memory)
   |-- G1 --> A1 \
   |-- G2 --> A2  \  all agents read the whiteboard in parallel
   |-- G3 --> A3  /  and write reminders when a memory matters
   ...             /
         whiteboard.json (working memory)
                |
          main chatbot
                |
         durable memories -> tape
```

## Install / run

No dependencies. Python 3.11+ (uses `certifi` for TLS when available).

```bash
cd memory-machine
export PYTHONPATH="$PWD/src"
export DEEPSEEK_API_KEY="..."   # never commit this
```

## Quickstart

```bash
python3 -m memory_machine init

python3 -m memory_machine add --type decision \
  --summary "Use Postgres for the primary datastore" --why "ACID + JSONB"

python3 -m memory_machine subject "migrate the auth service to a database"

python3 -m memory_machine run \
  --task "decide the database and connection strategy"
```

## Commands

| Command | Purpose |
|---------|---------|
| `init` | Create an empty project (config + tape + manifest + whiteboard) |
| `add --type T --summary S [--why W] [--files a,b]` | Append a memory to the tape |
| `subject S [--objective O]` | Set the current whiteboard subject |
| `run --task T` | Run one full cycle (agents -> whiteboard -> chatbot) |
| `consolidate [--llm]` | Consolidate the whiteboard (one consolidator agent) |
| `status` | Show tape / groups / agents / whiteboard state |
| `whiteboard` | Print the whiteboard |
| `context` | Print the main chatbot's conversation context |
| `recall Q [--cross-session] [--views v1,v2]` | Run memory agents for a question (JSON); optionally search other sessions / filter by views |
| `checkpoint Q S [--memories JSON]` | Record a turn back to memory (JSON) |
| `remember --summary S [--type T] [--why W] [--views v1,v2]` | Append a memory (JSON) |
| `list` / `archive ID` / `delete ID` | Manage tape records (JSON) |
| `attach PATH [--chunk-size N]` | Ingest a `.txt` into the tape as labeled chunk memories |
| `sessions` | List sessions (JSON) |
| `views` | List memory views / projections (JSON) |
| `rollup [--keep-recent N]` | Consolidate older tape records into one summary |
| `rehydrate ID [--reactivate]` | Recover the original memories behind a rollup |

Use `-C <dir>` to operate on a specific project directory. Run
`python3 -m memory_machine <cmd> --help` for details.

## Concepts

- **Tape** (`tape.jsonl`) — append-only long-term memory. Each record has a
  stable id (`M0001`, ...) and a type (`decision`, `lesson`, `preference`,
  `bugfix`, `build`).
- **Groups & agents** (`manifest.json`) — the tape is split into contiguous
  groups of `capacity` records; one memory agent watches each group. A new
  group/agent is created automatically as the tape grows.
- **Whiteboard** (`whiteboard.json`) — the bounded working memory: subject,
  objective, a **metacognitive** understanding (what the subject is about and
  what is happening, refreshed every turn), context, pending, and the agents'
  reminders.
- **Cycle** — every agent reads the whiteboard in parallel and writes reminders
  for memories that matter now; the main chatbot consumes the whiteboard and
  continues the task, then durable facts are appended to the tape.
- **Consolidation** — when the whiteboard grows too large, a single consolidator
  agent shrinks it to a compact note after persisting the working state to the
  tape (no loss of continuity).
- **Chatbot context** — the main chatbot also keeps its own conversation
  context (`context.json`) and consolidates it on its own schedule, independent
  of the whiteboard, so it never runs out of context over a long project.
- **Memory router** (opt-in, off by default) — selects the top-K partitions
  (via group digests) instead of consulting every agent, cutting fan-out from
  O(N) to O(K). Modes: `llm` (one routing call, semantic), `embedding` (cosine
  over digests; needs an embeddings provider like Ollama), or `lexical` (BM25;
  cheapest but unsafe for lexically-distant memories). It is opt-in because
  measurements show it trades recall for cost: on external benchmarks the full
  sweep scored 0.83-0.93 evidence recall vs 0.63-0.70 for the router.
- **Evaluation** (`eval/`) — `agent_bench.py` (synthetic, lexically distant),
  `external_bench.py` (LongMemEval / LoCoMo, with BM25, dense vector, full
  agents and routed agents; `--arms` and `--embedding-models` select arms and
  dense models) and `view_router_bench.py` (controlled topology: full vs
  similarity vs view-BM25 vs view-LLM vs view-oracle vs cascades, with view
  recall/precision, evidence and agent recall, reduction, expansion, fallback
  reasons, calls/tokens/latency). Measured: on LongMemEval dense retrieval
  beats BM25 and ties the agents (no agentic advantage); on LoCoMo the agents
  lead (0.90 vs BM25 0.78 and dense 0.56). The agentic advantage is
  benchmark-dependent: it emerges where relevance is contextual, not directly
  similar.
- **Provenance** — rollups record `derived_from`; `rehydrate <id>` recovers the
  original (archived) memories so compression is never a dead end.
- **Views (projections)** — a memory belongs to one canonical tape but can
  appear in several views (`time/…`, `type/…`, `source/…`, `topic/…`,
  `subject/…`) without physical duplication; the view index is a rebuildable
  projection. List with `views`, filter recall with `--views`.
- **Attention state** (opt-in) — `Whiteboard.attention` is a recency-weighted
  prior over views (decay + saturating boost) that keeps the conversation's
  active regions across turns: `prior` blends it into lexical routing,
  `context` shows it to the LLM plan, `state` reuses it for anaphoric
  follow-ups. Measured: anaphora resolved at 5.7 calls vs 10.7 (full sweep),
  and the old topic decays 0.94 -> 0.56 after a topic shift.
- **CLI/app modes** — `recall --agent-mode view --whiteboard-mode dimension
  --dimension-mode auto` switches a single recall to perspective agents and
  per-dimension boards; the app's settings expose the same as a "Memory mode"
  selector. External sessions can be auto-tagged into views with
  `eval/tag_sessions.py` + `external_bench.py --tag` (Fase 2).
- **View router** (opt-in) — uses the write-time organization as a structural
  retrieval prior: `router_mode: views` selects views (BM25 over view digests,
  or an LLM call with the whiteboard) and consults only their records;
  `router_mode: cascade` adds a recall-safe fallback (expand co-occurring
  views → similarity router → full sweep) and records why it fell back. An
  explicit `recall --views` overrides routing. With `view_dimension_mode:
  auto` the router plans dimensions first (semantic/temporal/structural) and
  intersects their record sets with progressive relaxation; `coverage_mode`
  adds a recall-local coverage signal (agents/structural/both/judge) that the
  cascade uses to expand. Controlled benchmarks (32 tasks): dimension-aware
  view-BM25 raises view recall 0.67 -> 0.81 and reduction 0.63 -> 0.70 at 9.6
  calls; the ground-truth-views oracle reaches 1.00 at 7.7 calls / 0.84
  reduction, so the router and the coverage signal — not the topology — are the
  bottleneck (manual 40.4/40.5).

## Configuration

`config.json` (see `config.json.example`):

| Key | Default | Meaning |
|-----|---------|---------|
| `capacity` | 50 | memories per group (per agent) |
| `whiteboard_budget` | 4000 | char budget for reminders on the whiteboard |
| `consolidate_threshold` | 6000 | whiteboard size that triggers consolidation |
| `context_consolidate_threshold` | 6000 | chatbot context size that triggers its own consolidation |
| `router_enabled` | `false` | enable partition routing (opt-in) |
| `router_mode` | `llm` | `lexical` / `embedding` / `llm` / `views` / `cascade` |
| `router_top_k` | 5 | partitions selected by the similarity router |
| `view_router_mode` | `lexical` | view selection: `lexical` (BM25) / `llm` (contextual) |
| `view_top_k` | 5 | views selected by the view router |
| `view_dimension_mode` | `off` | `auto` = dimension-aware plan (semantic/temporal/structural) with intersection |
| `view_prune` | `none` | `subject` = drop broad `subject/*` views when a topic matched |
| `agent_mode` | `group` | `view` = one perspective agent per selected view |
| `whiteboard_mode` | `single` | `dimension` = one working board per dimension |
| `attention_mode` | `off` | persistent attention prior: `prior` / `context` / `state` |
| `attention_decay` / `boost` / `found_boost` | 0.6 / 0.8 / 0.3 | attention decay and saturation boosts |
| `attention_weight` | 0.5 | weight of the attention prior in view scoring |
| `attention_gate_min` / `margin` | 0.5 / 0.1 | concentration required for the `state` gate |
| `coverage_mode` | `off` | recall-local coverage signal: `agents` / `structural` / `views` / `judge` |
| `cascade_min_score` | 0.0 | selection score below which the cascade expands |
| `cascade_expand_top_k` | 5 | co-occurring views added on expansion |
| `model` | `deepseek-v4-flash` | LLM model for agents, chatbot and consolidators |
| `base_url` | `https://api.deepseek.com` | OpenAI-compatible endpoint |
| `api_key_env` | `DEEPSEEK_API_KEY` | env var that holds the API key |

The API key is read from the environment only; it is never written to disk.

## Tests

```bash
python3 -m pytest tests/
```

## Evaluation

```bash
python3 eval/gen_fixture.py --records 300 --out /tmp/mm-fixture
python3 eval/bench.py /tmp/mm-fixture
```

Compares naive full-tape context vs deterministic recall vs memory agents on
recall and token economy.

## Docs

- [SPEC.md](SPEC.md) — the formal specification.

## Desktop app (macOS)

A native macOS menu-bar + window chatbot that runs the Memory Machine in
process (PySide6), packaged as a self-contained `.app`.

### Install

1. Open `dist/Memory Machine.dmg`, drag `Memory Machine.app` to `/Applications`.
2. First launch: right-click the app → **Open** (ad-hoc signed, not notarized —
   Gatekeeper requires this once).

### Build from source

```bash
./app/build.sh        # creates dist/Memory Machine.app (and re-verifies icon)
```

### App specifics

- The DeepSeek API key is stored in the **macOS Keychain**
  (`security find-generic-password -s memory-machine`), never in a file. The
  model and memory root live in
  `~/Library/Application Support/MemoryMachine/settings.json` (chmod 600,
  never in the repo). Edit them in the app's **Settings** dialog.
- Persistent memory is stored under
  `~/Library/Application Support/MemoryMachine/data/`.
- **Each topic owns its own tape.** A topic is a self-contained memory store
  (`data/topics/<id>/`) named by its creation date/time (with an optional
  label); memory agents are created per topic as that topic's tape grows.
- **Auto topic (multi-topic)** — when enabled, an LLM router infers which topic
  each message refers to (by time reference like "yesterday" and by subject)
  and switches tapes internally, falling back to today's topic when nothing
  matches. When disabled, use the topic selector manually.
- **Automatic topic creation** — by default one topic per day is created
  automatically (`auto_topic: day`). Alternatives in Settings: `idle` (a new
  topic after N hours without activity) or `off` (fully manual).
- **RAG documents + tape attachments** — the **Add files** button imports `.txt`
  files: they are added as RAG reference material (`data/documents/`, retrieved
  per message with BM25) **and** split into chunks that are appended to the
  session's tape as labeled `attachment` memories, so the memory agents can
  recall them. Attached chunks are secret-scanned and deduplicated by file
  hash. (This is the one intentional exception to "external context never
  touches the tape".)
- **Web search** — a keyless DuckDuckGo lookup for the current message. In
  **Auto** mode (default) it runs only when the question looks like it needs
  current info; the checkbox forces it on. Results go to the chatbot for that
  turn only (kept out of long-term memory).
- The app runs in the menu bar; closing the window hides it. Use the tray menu
  to reopen, open Settings, or quit.
- Each reply shows **Remembered** memory ids (from the memory agents) and
  **Saved to tape** ids (durable memories the chatbot produced).
