# Memory Machine — current architecture and status

Date: 2026-09-24 · Package **v0.3.0** · Research program **v1** (frozen
ledger) + active **admission-shadow-v2** window + **Companion** track
(lab-validated, pilot not started).

This is the authoritative "where are we now" document. Frozen instruments
(pre-registrations, results, the v1.0 paper snapshot) keep their original
contents; this file indexes them and states what is live.

## 1. The promise

Memory Machine does not put all the past into the context. It makes the past
**preservable, traceable and recoverable** — offering the right evidence, at
the right moment, inside a limited budget ("infinite memory = preserve
indefinitely, recover selectively"). The measured hard problem is
**admission**: a memory can keep everything and still fail by retrieving too
much, too late, or the wrong remembrance.

## 2. Layers

| Layer | Artifact | Role |
|---|---|---|
| Tape | `tape.jsonl` (per root) | Append-only truth: stable ids (`M0001`…), status (`active/archived/superseded`), types, provenance (`source`, `derived_from`, `supersedes`, optional `origin`/`author`/`event_time`), rebuildable views. |
| Groups & agents | `manifest.json` | Contiguous groups; one memory agent per group; new groups as the tape grows; each agent keeps a digest, a checklist and a dynamic `understanding` of its memories, refreshed every sweep. |
| Whiteboard | `whiteboard.json` | Bounded working memory: subject, understanding (metacognition), checklist, annotations; attention state. |
| Views / graph | `views`, `graph/` | Rebuildable projections over the tape (`time/…`, `type/…`, `source/…`, `topic/…`); never a factual source themselves. |
| Retrieval / payload / delivery | `retrieval.py`, `payload.py`, `context.py` | BM25 default (optional embeddings), evidence payload under a character budget, delivery windows. |
| Admission | `admission_shadow.py`, `admission_p3v4.py`, `lifecycle.py` | Shadow-only instrumentation and candidates; **nothing promoted**. |
| Turn slots | `turns.py` | The user message and the assistant reply as paired `question`/`reply` records (opt-in via the opencode plugin flag; `companion#` namespace for the Companion). |
| Companion | see §5 | Persona, synthetic life, creator, engine; new roots, own record kinds. |
| Surfaces | `memory-cli`, macOS app, opencode plugin/tools | CLI, desktop chat + Companion window, per-session memory tools. |

## 3. Data model (records)

- Project kinds: `decision`, `lesson`, `preference`, `bugfix`, `build`.
- Operational kinds: `attachment` (labeled exception for ingested text),
  `question`/`reply` (turn slots), rollups with `derived_from`.
- Companion kinds: `person_report`, `episode`, `persona`, `story`,
  `hypothesis`. Synthetic-life `story` records carry
  `origin.kind="synthetic_life_event"` (event id, life version, continuity,
  sheet version); improvised `story` carries a turn source.
- Optional fields (`origin`, `author`, `event_time`, `supersedes`) are
  serialized only when set — old tape lines round-trip byte-identically.
- Corrections are new records with a supersession edge; deletions cascade
  (`derived_from` closure, source turns, dependent corrections, caches) and
  reuse no ids (root-local high-water mark).

## 4. Turn flows

**Project chat (CLI/app).** Agents read the whiteboard in parallel → reminders
(annotations) → payload + whiteboard go to the chatbot → durable memories
appended to the tape.

**opencode sessions.** On every user message the plugin runs `memory-cli
recall` (agents + whiteboard + cross-session hits) and injects the recalled
block; with `MEMORY_MACHINE_TURN_SLOTS=1` it also records the paired
question/reply slots (after recall, so a turn never retrieves itself).

**Companion chat.** One root per relationship
(`<base>/companion/<person>/<character>/<continuity>/`), isolated at storage
level. `CompanionEngine.reply` runs the core recall inside the root, filters
cards to the four conversational kinds, renders labeled layers (Relatos /
Episódios / **Passado ficcional da personagem (aprovado)** / Histórias
imaginadas / Hipóteses) with provenance, adds the persona prompt and the
epistemic policy, makes **one reply call** and parses a `used`/`memories`
trailer. Eligible writes (turn slots + validated extraction) happen only
with saving on; `save=False` runs everything on a disposable clone (zero
canonical bytes).

## 5. Companion track (C0–C7, lab)

- **Contracts**: `COMPANION_V0_CONTRACT.md` (roots, five kinds, corrections,
  deletion, save-off, evaluation), `COMPANION_LIFE_V1_CONTRACT.md`
  (synthetic-life schema, no forged turns, idempotency, batch supersession,
  generation budget), `COMPANION_MULTI_CHARACTER_PLAN.md` (C0–C7 plan).
- **Core modules**: `companion_memory` (active surface, supersede, cascade
  delete, caches), `companion_extract` (admission contract), `companion_life`
  (life validator), `companion_creator` (draft/preview/approve transaction),
  `companion_life_admission` (**atomic publication**: journal + idempotent
  halves + `recover_publication`), `companion_gallery` (listings, timeline,
  diff, retire, impact, copy, create-from-template), `companion_persona`
  (sheet + revisions), `companion_session` (root validation, save-off clone),
  `companion_engine` (turn engine), `companion_generation` (one LLM call per
  request; drafts only, max two per approval flow).
- **App**: `CompanionWindow` (chat, "O que eu lembro", no-save toggle),
  `CreatorDialog` (gallery, create/copy, sheet, timeline with structured
  event forms, diff, approve+publish, retire with impact, "Gerar vida (IA)…").
  Entry points: menu bar → Companion / **Personagens**, a Companion button and
  ⌘⇧C in the main window.
- **Evaluation board** (lab; all fixtures/harnesses frozen):
  `companion-demo-v1` **failed** (registered), `companion-eval-v1`
  **failed**, `companion-eval-v2` failed on two check-design defects
  (registered), `companion-eval-v3` **passed G0–G11** (56 calls, calibrated
  judge, per-step isolation, correction/retirement/deletion, fiction
  separation, no invention, switch, budget, story trigger, publication-fault
  recovery). Scope: lab only — **not a pilot and no readiness claim**.

## 6. Research program v1 (frozen) and closed lines

The v1.0 ledger (`docs/PAPER.md`, `docs/RESULTS.md`) is frozen. Canonical
values (post harness fix): H1 confirmed (view agents), H2 confirmed (factual
content), H3 confirmed-relative (budget ~4000), H4 refuted (memory-aware
prompt), H5 refuted (multi-session was not the bottleneck), **H5' confirmed**
(temporal 0.29→0.64; temporal|evidence-complete 9/9; AUR 0.76→0.89), **H6a
refuted** (temporal 0.64→0.64). Pre-fix readings are quarantined
(`*_BUGGY.jsonl`) and must never be cited.

Closed later lines (all recorded, nothing promoted): lifecycle v1–v4
(correction slot; closure doc), two-tier retrieval (frontier; closure doc),
admission synthetic v1–v4 (closure doc), admission causal v1/v2 + holdout
(relation slot validated in the lab; closure doc), portfolio (negative),
delivery/window line (anchors, combined, diagnostic, phrase, numerals,
money v1/v2, component, multi-component), annotation line (coverage, union,
snippet), agent index/map and gap-recall (all lab-only with declared scope).

## 7. Active admission window (admission-shadow-v2)

- Restarted under §8 on 2026-09-23 when turn slots activated; **pre-restart
  logs archived** (`*.prerestart_20260923.jsonl`) and never counted.
- Frozen: P3v4 candidate (`44c0124`), comparators, schema, thresholds,
  stopping rule, retrievers, prompts, defaults. Sole instrument:
  `scripts/shadow_stop_check_v2.py` (coverage-only); only the owner reads
  outcome metrics, and only at `met:true`.
- Stop rule: 200 unique scored recalls / 15 sessions / 21 days / ≥30
  event-log / ≥100 `lexical_two_plus` / ≥10 zero-candidate / ≥40 judged /
  ≤1% malformed. Current: collecting (far below thresholds).
- At `met:true`: freeze logs + SHA-256 → blind judge on the
  `sha256(question_hash)%5==0` subsample → three diagnostics (ranking did
  not present / admission discarded / delivered but unused) → G1–G6 gates.
  Never automatic promotion.

## 8. Defaults, flags and invariants

- On by default since v0.3.1: `agent_history_messages` = 10 (the agents'
  conversation window; set 0 to disable). Off by default:
  `evidence_payload_window`, `graph_enabled`, router (`opt-in` after
  external benchmarks: agents > BM25 > router).
- Opt-in env flags: `MEMORY_MACHINE_ADMISSION_SHADOW` (window), 
  `MEMORY_MACHINE_TURN_SLOTS` (paired slots; the owner has it set and an
  opencode restart is pending for it to take effect).
- Save-off (Companion) never writes to the canonical root; secret scanning
  gates every tape write; external context (web/datasets/judges) never
  enters the tape/whiteboard/agents.
- Dual-track: the synthetic lab never contaminates window logs; promotion
  requires a new real window from zero.

## 9. Versioning and operations

- Package `0.3.0` (SemVer); research program `v1`; app/DMG `0.3.0`
  (Info.plist stamped from `memory_machine.__version__`). Tags: v0.2.x line
  and v0.3.0.
- Tests: 728 (`python3 -m pytest -q`), ruff on `src/tests/scripts`, CI
  6 required checks (ubuntu/macos/windows × py3.11/3.14) + non-blocking
  audit and scientific workflows. Evidence retention: releases + repo
  (`docs/EVIDENCE_RETENTION.md`).
- App build: `app/build.sh` (PyInstaller, bundles `personas/`, hidden
  imports for the Companion modules, ad-hoc signing) → `/Applications` +
  DMG.

## 10. Document index (status)

| Status | Documents |
|---|---|
| Living | `ARCHITECTURE.md` (this), `ROADMAP.md`, `OPERATIONAL_DECISIONS.md`, `DUAL_TRACK_PLAN.md`, `CLI.md`, `CONFIGURATION.md`, `DESKTOP_APP.md`, `GRAPH_USAGE.md`, `EVIDENCE_RETENTION.md` |
| Frozen contracts | `COMPANION_V0_CONTRACT.md`, `COMPANION_LIFE_V1_CONTRACT.md`, `COMPANION_MULTI_CHARACTER_PLAN.md`, `NORMATIVE_SPEC_V1.md`, `LIFECYCLE_V1_SPEC.md` |
| Frozen results | `PAPER.md`, `RESULTS.md`, `FINDINGS.md`, closure docs (`*_CLOSURE.md`), pre-registrations (`*_PREREG.md`), evaluation records |
| Historical | `ADMISSION_SHADOW_V1.md` + stopping rule + pause, `HISTORY_REWRITE_2026-09-22.md`, `AUDIT_OSS_V1.md`, `PUBLICATION_PREFLIGHT.md` |

Next gates on the table: the owner's real use of the v0.3.0 app, the
opencode restart for turn slots, and — only if pursued — a pilot with its
own consent/provenance/retention contract (public pilot remains out of
scope).
