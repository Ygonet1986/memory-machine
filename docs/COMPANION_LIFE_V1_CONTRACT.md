# Companion life v1 contract — synthetic life events and the creator

Status: **C0 frozen contract**, 2026-09-24. Documentation only; the C1+ PRs
implement it. Extends `docs/COMPANION_V0_CONTRACT.md` and must not contradict
it: the tape stays the only source of memory, records stay typed and sourced,
and nothing here changes the measured opencode path, the admission-shadow-v2
window or product defaults.

## 1. Authority chain

Catalog template (repo) -> approved sheet snapshot (per root) -> approved life
version (per continuity) -> tape records. A synthetic life event is fiction
about the *character*; it is never a fact about the person and never a shared
episode. Approved events are stored as `story` records with
`origin.kind="synthetic_life_event"`; **no sixth record type** is created and
**no conversation turn is ever forged** to satisfy the extractor. Improvised
fiction from a conversation keeps its current shape (`story` with a turn
source) and is labeled separately (section 7).

## 2. Data layout

```text
personas/<slug>/vN.json                     # versioned template in the repo
<root>/persona/current.json                 # approved sheet snapshot
<root>/persona/history/vN.json              # approved sheet revisions
<root>/synthetic_life/current.json          # active life version (index + seed)
<root>/synthetic_life/history/vN.json       # approved snapshots (incl. retired)
<root>/synthetic_life/draft.json            # recoverable draft (never recalled)
<root>/tape.jsonl                           # story records and relationship memory
```

`character_id` is an opaque, immutable path component; the display name and
any model-provided path are never used as storage identifiers. A life version
is approved **per continuity**. Sharing one approved life across roots would be
an explicit import with independent snapshots (out of scope for v1).

## 3. Event schema (normative)

```json
{
  "event_id": "life-0007",
  "life_version": 1,
  "title": "Primeira apresentação",
  "summary": "Lia apresentou uma composição num festival fictício.",
  "event_time": "2018-06-10",
  "time_precision": "day",
  "place": "cidade ficcional aprovada",
  "participants": ["lia", "avo_lia"],
  "causes": ["life-0003"],
  "effects": ["life-0008"],
  "status": "draft",
  "provenance": {
    "kind": "synthetic_life", "generator": "manual",
    "sheet_version": 1
  },
  "approved_at": "", "approved_by": ""
}
```

Rules:

- `event_id` is stable inside the continuity; `time_precision` is one of
  `year|month|day|unknown`, and an exact day is never invented.
- `causes`/`effects` reference existing local events and form an acyclic,
  time-respecting graph. Participants use local IDs with declared roles.
- The sheet carries a reference date (or explicitly none); age, kinship,
  residence and chronology interlock without contradiction.
- `status` is `draft`, `approved` or `retired`; only approved events may be
  published to the tape; a retired event is never active.
- Provenance records `manual|generated|imported`, the sheet version, and for
  generated text the prompt/model/seed and the approval act. Generated text is
  a **draft** until approved.

Implementation limits (defaults to be enforced and tested in C1): 3-12 bio
facts; 5-30 events per version; at most 500 characters per summary; at most 5
participants and 5 links per event. These are choices, not measured numbers.

## 4. Generation budget

- "Propose life" is **one LLM call per request**, with declared model, seed and
  prompt; it returns a JSON list of at most 30 draft events.
- Generated drafts are written only to `synthetic_life/draft.json`; they never
  reach the tape, `current.json` or recall, and are never auto-approved.
- Generation is refused while a sandbox/save-off turn is running; the preview
  sandbox reads the approved life version only.
- At most two user-triggered generation requests per approval flow (declared
  in C2 tests); the number of events is bounded by the §3 limit.

## 5. Admission (no forged turns)

`approve(life_version)`:

1. validates the schema, the time-respecting acyclic links, the sheet version,
   all referenced IDs, the limits and the secret scan of every field;
2. writes, in **one root-local transaction** (staging, fsync, atomic swap, plus
   a journal for recovery): `history/vN.json`, `current.json`, and exactly one
   tape record per approved event;
3. for each event the record is `type="story"`, `author="joint"`,
   `derived_from=[]`, `source="life#<life_version>#<event_id>"` and

   ```json
   {"kind": "synthetic_life_event", "event_id": "life-0007",
    "life_version": 1, "continuity_id": "main", "sheet_version": 1}
   ```

   with `event_time` carried on the record.

The operation is **idempotent per `(root, life_version, event_id)`**: re-running
an approval writes nothing new. A failure anywhere leaves no half-published
version (journal replay or abort). Rejected drafts never enter the tape.

## 6. Revision and deletion

- A new approved version `vN+1` **supersedes `vN` in one batch**: every `vN`
  story record becomes `superseded`, the new records become active, and the
  history keeps the old snapshot. No per-event rewrite loop.
- An event dropped in `vN+1` becomes `superseded`/removed from recall, with
  cache invalidation; it cannot resurface through rollups or rehydration.
- Deleting an event opens an **impact preview**: derivations and any episodes
  that cite its `event_id`, with explicit user decision about related content
  (chain cascade per the F1c rules; semantic siblings are never assumed away).
  Deleting a whole root remains a separate explicit action.

## 7. Recall and labels

- Recall never crosses roots. Synthetic life cards are labeled **"Passado
  ficcional da personagem (aprovado)"**, distinct from "Histórias imaginadas em
  conversa" (story without the synthetic-life origin) and from reports and
  episodes.
- Cards carry `event_id`, `life_version` and `sheet_version`. Only IDs actually
  used are echoed back (F3 trailer); a recall hit is not a used memory.
- Synthetic life has its **own context budget** (the number is declared and
  tested in C4, not here); a draft or retired event never appears.

## 8. Isolation and identifiers

Record IDs (`M0001`...) are local to a root. No recall, cache, graph or index
crosses roots. Importing content requires an explicit, remapped operation
(not in v1). Deliberate ID collisions across roots are an evaluation case
(C6), not a supported reference.

## 9. Creator flow (normative)

1. **Identity**: display name, language (pt-BR in the first cut), voice,
   values, boundaries, theme, optional fictional age, visible AI declaration.
2. **World and relations**: continuity, places, close fictional people, fixed
   milestones, subjects the character must not claim.
3. **Life**: manual entry or one generated proposal; timeline, links,
   inconsistencies and per-event provenance are shown.
4. **Preview**: sandbox conversation with no writes to the canonical root; it
   shows which events entered the context and which were cited.
5. **Approval**: confirm sheet and selected events; write the versioned
   snapshot with IDs and counts. A later edit creates `vN+1` and never rewrites
   `vN`.

Duplicating a template creates a **new** `character_id` and never inherits
private conversations. The creator states that the life is invented, and
forbids content that presents the character as a real human, pressures for
presence/exclusivity, or claims shared experience without a source turn.
Secret scanning and size limits apply to every field before any write.

## 10. Non-goals

Autonomous characters writing their life without review, global memories
shared between people, automatic transfer of experiences between characters,
voice/avatars, a character social network and any public pilot. Those need
their own consent, provenance and retention contract.

## 11. C-track and proofs

| PR | Delivery | Minimum proof |
| --- | --- | --- |
| C0 | this contract + F0 pointer | contract review, docs only |
| C1 | extended schema and validator, world and events, example templates | rejections: versions, cycles, contradictions, IDs, secrets |
| C2 | creator backend: draft, preview, approval, per-root snapshot | idempotence, mid-failure, isolation, Lia untouched |
| C3 | synthetic-life `story` admission + versioning/supersession | no forged turn; provenance; non-resurrection after reload |
| C4 | labeled recall, budget and event-anchored answers | real `used`, zero attribution to the person, ID collisions |
| C5 | UI: gallery, form, timeline, revision diff, deletion with impact | backend tests and critical UI flows; copy inherits nothing |
| C6 | new pre-registered evaluation + A/B at equal budget | the gates below, costs, failures, single registered run |
| C7 | version, build, installable artifact after the gates | package smoke, templates, creator opens |

Nothing in this track changes opencode paths, the v2 window, defaults or
experimental policies; no version bump before C7. Each PR regenerates
`docs/CONFORMANCE_PROOF.txt` when it adds tests.

C6 gates (frozen there, listed here for scope): zero cross-root leakage, zero
fiction attributed to the person, zero resurrection of a retired/deleted
event, zero draft in recall, stable correction, cost inside the registered
cap, and an **attribution rubric** (citing "irmã" to explain a correction or
naming "astronomia" to deny knowledge is not asserting them), with literal
checks kept for deleted-content leakage. The v1 demo stays recorded as a
failed historical line and is never re-run as confirmation.
