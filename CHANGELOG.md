# Changelog

All notable changes to this project are documented here. The project follows
[Semantic Versioning](https://semver.org/) for the installable package; the
manual/whitepaper keeps its own document version.

## [Unreleased]

- **Conversation guard candidate (unwired).** `conversation_rescue` in
  `graph_recall.py` re-admits association-only path evidence cut by the
  promoted guard (floor 0.60, cap 2, `related_to`-only paths). Validated in
  the lab (`docs/GRAPH_CONVERSATION_GUARD_V1_PREREG.md`, gates C1-C5);
  opt-in-unwired - adopting it as a default requires a new §8 restart.

## [0.3.6] - 2026-09-25

- **Association rescue adopted as the conversation default.**
  `graph_recall_mode = "augment_conversation"`: the P0--P5 promoted guard
  (floor 0.80, cap 3, hub-capped traversal) plus a bounded rescue of
  association-only path evidence (`related_to` paths above
  `graph_conversation_min_score` = 0.60, up to
  `graph_conversation_max_items` = 2; `augment_guarded` gates the rescue
  off, `augment` disables the guards). Validated in the lab (gates C1--C5,
  links 3/3 vs 0/3, zero hub noise) and declared with an archived-window
  restart under admission-shadow-v2 §8.

## [0.3.5] - 2026-09-25

- **Graph projection hygiene and dimension-mode merge.** Before each recall
  the graph index is pruned to the tape's active records: entities without an
  active mention and relations whose originating memory is inactive or absent
  no longer route traversal (the store stays append-only). Dimension
  whiteboards now receive the graph annotations (semantic board). Fixes the
  two gaps declared in `CONVERSATION_GRAPH_IMPLEMENTATION.md` §7/§9.
  Declared with an archived-window restart under admission-shadow-v2 §8.

## [0.3.4] - 2026-09-25

- **Persistent conversation graph (two memories, one whiteboard).** Saved
  turns (`question`/`reply`), the chat's `memory` records and
  `entity_definition` descriptions are projected into the persistent graph
  (associative `related_to` edges carry the tape memory id; they are
  navigation hints, not facts). Recall combines graph and agent annotations
  under the same whiteboard budget; inactive tape records are dropped.
  Defaults: `graph_enabled = true`, `graph_conversation_enabled = true`,
  `graph_recall_mode = "augment"`. The P0--P5 promoted guard
  (`augment_guarded`, score floor 0.80 + cap 3) stays available but filters
  association-only evidence, so it is opt-in for conversations. Deduped
  turns are not re-extracted; extraction failures never roll back the tape.
- Activation was declared with an archived-window restart under
  admission-shadow-v2 §8 (pre-restart logs archived, never counted).

## [0.3.3] - 2026-09-25

- **Two conversation agents (observer + answerer).** The observer watches
  the dialogue, refreshes a compact conversation `understanding`
  (persisted in `context.json`; the existing context consolidation compacts
  it on overflow) and gives short guidance; the answerer writes the reply
  with that guidance ("both discuss the answer"). One extra LLM call per
  chatbot turn; `answerer_observer = false` restores the single-call path.
  Recall/agents and the admission window are untouched.

## [0.3.2] - 2026-09-25

- **Answerer context rule: whole whiteboard + last 10 messages under one
  budget.** The conversation agent (CLI/app chatbot) now receives the last
  `answerer_history_messages` turns (10 by default; consolidated summary
  included, each side capped at 320 chars) with priority inside
  `whiteboard_budget`; the whiteboard fills the remainder and is trimmed at
  that remainder (800-char floor). Set 0 to return the whole budget to the
  whiteboard. Recall/agents and the admission window are unaffected.

## [0.3.1] - 2026-09-25

- **Agent conversation window, now active by default (10).**
  `agent_history_messages` (0-50) appends the last N turn slots
  ("Pessoa:"/"Assistente:") to the memory agents' user prompt so their
  digests, checklists and dynamic `understanding` follow the conversation.
  Set 0 to keep prompts byte-identical. Activation was declared with an
  archived-window restart under admission-shadow-v2 §8.

## [0.3.0] - 2026-09-24

- **Companion: multiple characters with synthetic lives.** Versioned life
  documents (draft/history/current), a per-root publication transaction with
  recovery, no-forged-turn `story` admission (batch supersession, ID
  non-reuse), labeled recall ("Passado ficcional da personagem (aprovado)"
  with its own budget), corrections, retirement and deletion with explicit
  impact decisions, save-off with zero canonical bytes, cross-root isolation
  and AI life generation (one LLM call per request, two per approval flow,
  drafts only). Creator backend + "Personagens" dialog in the app.
- **Evaluations.** `companion-eval-v1`/`v2` are recorded as failed historical
  lines (check-design defects); `companion-eval-v3` passed all gates
  (G0-G11) in the lab: calibrated judge, per-step isolation, correction,
  retirement, deletion, fiction separation, no invention, character switch,
  budget, deterministic story trigger and publication-fault recovery.
  Lab scope only; not a pilot result and no readiness claim.
- No changes to opencode paths, admission-shadow-v2 or product defaults.

## [0.2.6] - 2026-09-24

- **Companion is reachable from the main window**: a `Companion` button in the
  toolbar row and a ⌘⇧C shortcut open the same cached window as the menu-bar
  entry (shared `app.companion_launcher`). No memory behavior or default
  changes.

## [0.2.5] - 2026-09-24

- **Companion (experimental surface, opt-in).** The Companion v0 stack: five
  typed memories (`person_report`, `episode`, `persona`, `story`,
  `hypothesis`) with provenance fields, supersession with cache invalidation,
  cascade deletion with ID non-reuse, save-off turns on a temporary clone,
  the headless engine (agent recall, labeled layers, one reply call, and the
  used/memories trailer), the app backend and the Companion window
  (menu bar → **Companion**) with the "what I remember" panel.
- The scripted §7 demonstration is recorded in
  `docs/COMPANION_DEMO_V1_PREREG.md`: single run, `all_pass=false`, findings
  registered (no acceptance claim; nothing promoted).
- Build: `personas/` is bundled and the Companion modules are declared as
  hidden imports so the packaged app can approve the persona; template
  resolution honours the PyInstaller bundle.

## [0.2.4] - 2026-09-23

- **Turn slots (opt-in).** `memory-cli ask` / `memory-cli reply` record both
  sides of a turn on the tape as `question` and `reply` records, deduped by
  opencode message id and paired via `derived_from`; the opencode plugin
  wires them behind `MEMORY_MACHINE_TURN_SLOTS=1` (off by default, so the
  default write path is unchanged). No record-schema changes.
- **Per-agent dynamic understanding.** Each memory agent's system prompt now
  opens with a dynamic `understanding` of what its group's memories are;
  the agent refines it every sweep (JSON response gains `understanding`) and
  it is persisted on the agent next to digest/checklist, so it survives
  across turns. View agents stay out of scope for v1.
- Admission-shadow-v2 window restarted from zero (declared under §8):
  pre-restart logs archived and never counted; rules, schema, candidate and
  thresholds unchanged.

## [0.2.0] - 2026-09-22

First packaged release (L1).

- Installable package (`pip install .`) with the `memory-cli` entry point;
  no `PYTHONPATH` required.
- Single source of version truth (`memory_machine.__version__`), unified with
  the package metadata (previously `0.1.0` in code vs "project 1.0" in docs).
- Core stays dependency-free; extras: `app` (PySide6), `dev` (pytest), `eval`.
- OpenCode integration moved into the repository under `integrations/opencode/`
  with install/uninstall scripts.
- Offline mock LLM (`MEMORY_MACHINE_MOCK=1`) for smoke tests and CI; never for
  evaluation.

## [0.2.1] - 2026-09-22

Public-ready snapshot. No functional change to recall.

- **Admission shadow instrumentation (opt-in).** `MEMORY_MACHINE_ADMISSION_SHADOW=1`
  logs one JSON line per recall with derived admission signals (candidate
  origin/score/rank, lexical overlap, IDF rare-term coverage, entity/date
  matches, character costs, counterfactual admission). No question text,
  summaries or notes; no behavior change. See `docs/ADMISSION_SHADOW_V1.md`.
- **History rewrite.** The author's early personal notes (`.opencode/memory`)
  were purged from all history with `git filter-repo`; all tags and cited
  commit SHAs were rewritten (`docs/HISTORY_REWRITE_2026-09-22.md`).
- **Preflight.** Canonical placeholder excerpts are now accepted by excerpt
  rather than by path; re-run over the rewritten history reports 0 critical
  findings.

## [0.2.2] - 2026-09-22

Maintenance and communication after the external audit; no functional change
to recall.

- **CI hardening.** Actions pinned by full commit SHA
  (`checkout` v7.0.1, `setup-python` v7.0.0, `upload-artifact` v7.0.1) and
  explicit runner images (`ubuntu-24.04`, `macos-14`, `windows-2022`).
- **Static quality.** `ruff` gate over `src/`, `tests/` and `scripts/`
  (research harnesses under `eval/` stay unlinted so frozen artifacts are
  never reformatted); coverage report in the test step (not a gate yet); a
  non-blocking dependency audit job (`pip-audit`).
- **README separation.** Front page is now promise + quickstart + short
  architecture + status + links. Moved verbatim: CLI reference
  (`docs/CLI.md`), configuration (`docs/CONFIGURATION.md`), graph usage
  (`docs/GRAPH_USAGE.md`), macOS app (`docs/DESKTOP_APP.md`), measured notes
  (`docs/FINDINGS.md`).
- **Versioning clarity.** The README now states explicitly that the package
  follows SemVer (`0.x` while the research phase is "experimental program
  v1").
- **Admission shadow privacy.** Log file created with mode `0600`; threat
  model, retention, permissions and planned keyed-HMAC hardening documented
  in `docs/ADMISSION_SHADOW_V1.md`.

## [0.2.3] - 2026-09-22

Admission-shadow-v2 preparation; no functional change to recall.

- **Pre-registration** (`docs/ADMISSION_SHADOW_V2_PREREG.md`): new real-tape
  window starting from zero, frozen P3v4 candidate tied to commit `44c0124`,
  coverage-only stopping rule, judged subsample, joint availability+precision
  gates, window freeze.
- **`admission_p3v4`** (`src/memory_machine/admission_p3v4.py`): the frozen
  candidate as shadow-only product code; proven equivalent to the
  `admission-synthetic-v4` harness on the whole frozen fixture
  (`tests/test_admission_p3v4.py`).
- **`admission_shadow` schema v2**: adds the lexical candidate block with
  P3v4 signals and counterfactual decision, P1/P2 comparators, the
  judged-subsample flag and `retrieval_ms`. Derived data only; off by
  default; the actual payload/behavior is untouched.
- **`scripts/shadow_stop_check_v2.py`**: coverage-only checker for the new
  window (200 scored recalls / 15 sessions / 21 days / category minima / 40
  judged / 1% malformed).
- Collection is **not** activated by this release; it starts only after the
  preregistration, schema and tests are merged (they are), under the window
  freeze.
