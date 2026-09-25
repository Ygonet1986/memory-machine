# Memory Machine

Persistent memory for long-running projects: a conceptually infinite **tape**,
a growing layer of **memory agents** that watch it in parallel, and a shared
**whiteboard** that holds the work happening right now.

```
tape.jsonl (long-term memory)
   |-- G1 --> A1 \
   |-- G2 --> A2  \  all agents read the whiteboard in parallel
   |-- G3 --> A3  /  write reminders when a memory matters
   ...             /
         whiteboard.json (working memory)
                |
          main chatbot
                |
         durable memories -> tape
```

**The promise.** It does not aim to make the model recall everything at
once; it aims to make the past preservable, traceable and recoverable -
offering the model the right evidence, at the right moment, inside a limited
budget. "Infinite" memory means preserve indefinitely and recover selectively
(see `docs/ROADMAP.md`).

The design separates four problems that long-term agent memory usually
conflates: **preservation** (append-only tape), **organization** (rebuildable
views and graph projections), **discovery** (agents over the tape) and
**admission** (what earns the bounded context). The experimental program
measures one layer at a time and records refutations; the open bottleneck is
admission, instrumented before any policy change (see below).

Two memories now cooperate on the same whiteboard: the **tape** (records the
conversation and is read by the memory agents) and the persistent **graph**
(entities and connections extracted from those same records, each edge
carrying the id of its tape memory). Graph links are navigation hints, not
verified facts; only active tape records can become annotations or evidence.
Both default on (`graph_recall_mode="augment"`), with the P0–P5 guarded mode
available when overload protection matters more than associative reach.

The same core now also powers a **Companion** surface (v0.3.5): fictional
characters with versioned synthetic lives, memory isolated per relationship,
labeled recall of approved fiction, explicit corrections/retirement/deletion
and save-off. The conversation itself is served by two agents (an observer
that keeps the conversation understanding and guides; an answerer that
writes with it). Lab-validated (evaluation v3, all gates), not a pilot
claim — the current architecture and status live in
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Install / run

No dependencies. Python 3.11+.

```bash
pip install .
export DEEPSEEK_API_KEY="..."   # never commit this
```

From a source checkout without install:

```bash
cd memory-machine
export PYTHONPATH="$PWD/src"
```

## Quickstart

```bash
memory-cli init

memory-cli add --type decision \
  --summary "Use Postgres for the primary datastore" --why "ACID + JSONB"

memory-cli subject "migrate the auth service to a database"

memory-cli run --task "decide the database and connection strategy"

memory-cli recall "which database did we choose?" --cross-session
```

## Architecture (short)

- **Tape** (`tape.jsonl`) — append-only long-term memory; stable ids
  (`M0001`, ...), types (`decision`, `lesson`, `preference`, `bugfix`,
  `build`), and provenance (`derived_from` + `rehydrate`).
- **Groups & agents** (`manifest.json`) — contiguous groups of `capacity`
  records, one memory agent each; new groups appear as the tape grows.
- **Whiteboard** (`whiteboard.json`) — bounded working memory: subject,
  objective, metacognitive understanding, checklist and agents' reminders.
- **Cycle** — agents read the whiteboard in parallel and write reminders; the
  chatbot consumes the whiteboard, then durable facts are appended to the tape.
- **Views / graph** — rebuildable projections over the canonical tape (`views`
  for `time/…`, `type/…`, `source/…`, `topic/…`, `subject/…`; the graph adds
  entities, paths and document windows). Never a factual source by themselves.
- **Evidence payload** — the agents say *why* a memory matters; the payload
  delivers *what it says* under a character budget (recall-local, never
  persisted). The open research question is admission: which candidates deserve
  those characters.
- **Turn slots** — what the person said and what was answered as paired tape
  records (`question`/`reply`), deduped and provenance-linked; opt-in via the
  opencode plugin flag.
- **Companion layer** — persona sheets, synthetic-life documents (validated,
  versioned, published atomically), a turn engine with labeled layers and a
  `used`/`memories` trailer, a creator (gallery, timeline, diff, retire with
  impact, AI life proposals) and the desktop window.

## Research status and versioning

- **Scientific phase:** experimental program **v1** — the H1–H6 ledger in
  `docs/PAPER.md` (`RESULTS.md` has the generated tables). Confirmed:
  perspective agents over views (H1), factual-content delivery (H2), budgeted
  evidence at ~-70% context (H3), real timestamps + payload fix
  evidence-complete temporal reasoning (H5'). Refuted: the memory-aware prompt
  (H4), multi-session aggregation as the bottleneck (H5), the
  temporal-computation prompt once timestamps were correct (H6a).
- **Package version:** **0.3.5** — Semantic Versioning for the installable
  package (see `CHANGELOG.md`). The "v1" of the research program and the
  package version are different axes: the code is deliberately `0.x` while the
  research phase is v1.
- **Companion track (C0–C7, lab):** multiple characters with versioned
  synthetic lives, atomic publication with recovery, labeled recall,
  corrections/retirement/deletion with explicit impact decisions, save-off and
  AI life proposals. Evaluation v3 passed every gate in the lab
  (`docs/COMPANION_EVAL_V3_PREREG.md`); v1/v2 stay recorded as failed
  historical lines. Nothing promoted.
- **Current focus:** admission control. The active window is
  `admission-shadow-v2` (`docs/ADMISSION_SHADOW_V2_PREREG.md`), restarted
  under §8 when turn slots were activated; pre-restart logs are archived and
  never counted. Only the coverage-only checker runs until `met:true`
  (`docs/ADMISSION_SHADOW_PAUSE.md` is the paused v1 history).

Detailed measurements moved to `docs/FINDINGS.md`; the paper is the
authoritative narrative.

## Tests and evaluation

```bash
python3 -m pytest -q                 # full suite (751 tests)
python3 -m ruff check src tests scripts
python3 eval/gen_fixture.py --records 300 --out /tmp/mm-fixture
python3 eval/bench.py /tmp/mm-fixture
```

The CI matrix runs on Ubuntu, macOS and Windows with Python 3.11 and 3.14:
static checks, the full suite with a coverage report (not a gate yet), a
conformance proof manifest, an installed-wheel smoke test, deterministic
offline harness checks, and a non-blocking dependency audit. The scientific
evaluation is a separate, non-required workflow.

## Docs

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — current architecture and
  status (the authoritative "where are we now").
- [SPEC.md](SPEC.md) — formal specification.
- [docs/PAPER.md](docs/PAPER.md), [docs/RESULTS.md](docs/RESULTS.md) — the
  paper draft and generated result tables; [docs/RELATED_WORK.md](docs/RELATED_WORK.md).
- [docs/CLI.md](docs/CLI.md) — full CLI reference.
- [docs/CONFIGURATION.md](docs/CONFIGURATION.md) — every `config.json` key.
- [docs/ADMISSION_SHADOW_V2_PREREG.md](docs/ADMISSION_SHADOW_V2_PREREG.md) —
  the active admission window (frozen rules, restart under §8);
  [docs/ADMISSION_SHADOW_V1.md](docs/ADMISSION_SHADOW_V1.md) is the paused
  v1 history and its privacy model.
- Companion: [docs/COMPANION_V0_CONTRACT.md](docs/COMPANION_V0_CONTRACT.md),
  [docs/COMPANION_LIFE_V1_CONTRACT.md](docs/COMPANION_LIFE_V1_CONTRACT.md),
  [docs/COMPANION_MULTI_CHARACTER_PLAN.md](docs/COMPANION_MULTI_CHARACTER_PLAN.md),
  [docs/COMPANION_ENGINE.md](docs/COMPANION_ENGINE.md),
  [docs/COMPANION_EVAL_V3_PREREG.md](docs/COMPANION_EVAL_V3_PREREG.md).
- [docs/DESKTOP_APP.md](docs/DESKTOP_APP.md) — macOS app (install, build).
- [docs/GRAPH_USAGE.md](docs/GRAPH_USAGE.md) — graph projection usage.
- [docs/DOC_GRAPH.md](docs/DOC_GRAPH.md) — the operational document graph.
- [docs/EVIDENCE_RETENTION.md](docs/EVIDENCE_RETENTION.md) — where results and
  proofs live (releases + repository, never only CI artifacts).
- [docs/ROADMAP.md](docs/ROADMAP.md) — the promise and the application
  progression (project memory first, personal longitudinal memory last).
- [docs/EVIDENCE_PORTFOLIO_IDEAS.md](docs/EVIDENCE_PORTFOLIO_IDEAS.md) —
  recorded proposals (typed evidence portfolio, versioned claims,
  contradictions, planner, receipt); not scheduled.
- [docs/DUAL_TRACK_PLAN.md](docs/DUAL_TRACK_PLAN.md) — synthetic lab vs real
  shadow: separation rules and promotion path.
- Closure records: [docs/LIFECYCLE_CLOSURE.md](docs/LIFECYCLE_CLOSURE.md),
  [docs/TWO_TIER_CLOSURE.md](docs/TWO_TIER_CLOSURE.md),
  [docs/ADMISSION_SYNTHETIC_CLOSURE.md](docs/ADMISSION_SYNTHETIC_CLOSURE.md),
  [docs/ADMISSION_CAUSAL_CLOSURE.md](docs/ADMISSION_CAUSAL_CLOSURE.md),
  [docs/HISTORY_REWRITE_2026-09-22.md](docs/HISTORY_REWRITE_2026-09-22.md).

## License

MIT — see [LICENSE](LICENSE).
