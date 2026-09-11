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
| `recall Q [--cross-session]` | Run memory agents for a question (JSON); optionally search other sessions |
| `checkpoint Q S [--memories JSON]` | Record a turn back to memory (JSON) |
| `remember --summary S [--type T] [--why W]` | Append a memory (JSON) |
| `list` / `archive ID` / `delete ID` | Manage tape records (JSON) |
| `attach PATH [--chunk-size N]` | Ingest a `.txt` into the tape as labeled chunk memories |
| `sessions` | List sessions (JSON) |
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
- **Evaluation** (`eval/`) — `agent_bench.py` (synthetic, lexically distant) and
  `external_bench.py` (LongMemEval / LoCoMo, with BM25, dense vector, full
  agents and routed agents). The agentic advantage over similarity retrieval is
  benchmark-dependent: it holds where the lexical/semantic gap is large.
- **Provenance** — rollups record `derived_from`; `rehydrate <id>` recovers the
  original (archived) memories so compression is never a dead end.

## Configuration

`config.json` (see `config.json.example`):

| Key | Default | Meaning |
|-----|---------|---------|
| `capacity` | 50 | memories per group (per agent) |
| `whiteboard_budget` | 4000 | char budget for reminders on the whiteboard |
| `consolidate_threshold` | 6000 | whiteboard size that triggers consolidation |
| `context_consolidate_threshold` | 6000 | chatbot context size that triggers its own consolidation |
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
