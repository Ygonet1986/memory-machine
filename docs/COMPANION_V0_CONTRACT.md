# Companion v0 contract

Status: implementation contract, 2026-09-24. F0 is documentation only. F1–F6
are separate, additive changes. The active admission-shadow-v2 window is
frozen under `docs/ADMISSION_SHADOW_V2_PREREG.md`.

## 1. Scope and storage boundary

One relationship has one canonical root:

```text
<base>/companion/<person_id>/<character_id>/<continuity_id>/
```

Each identifier is an opaque, validated path component, never a display name
or arbitrary path. Reject empty components, `.`, `..`, separators, NUL and
symlink escapes. Authentication and authorization select the person before
opening the root. An ID such as `M0001` is local to a root; references outside
the root require an explicit import and cannot be followed by default.

The existing session tape, manifest, whiteboard and context live inside this
root. A continuity survives multiple chat windows. Starting another
continuity creates a separate root; a character may have a separately
versioned template, but its relationship memories are private to the root.
The default adapter performs no cross-root search. Tests must try collisions
of memory IDs across people, characters and continuities.

This contract does not change existing `opencode` sessions or the active
admission-shadow-v2 collection. F1 fields are optional and absent from JSON
when empty. Companion writes occur only under companion roots. No experiment
candidate, prompt, threshold, comparator, logging schema, measured write path
or product default is changed during this work.

## 2. Record kinds and epistemic boundaries

| `type` | Meaning | Authority |
| --- | --- | --- |
| `person_report` | What the person said about their life, tastes or plans | A report by the person, not independent verification |
| `episode` | An event in a real conversation | A source turn or pair of turns |
| `persona` | Fictional character biography, values and voice | A versioned, approved character specification |
| `story` | An imagined event in a chosen narrative continuity | Fiction inside that story |
| `hypothesis` | A tentative interpretation of preference or state | Tentative until explicitly confirmed by a new person report |

Each new Companion record has `origin` (structured reference to a local turn,
approved persona version or story event), `author` (person, character,
system or joint), and `event_time` (ISO 8601 when known). `created_at` is the
write time; `event_time` is when the described event occurred. Existing
`source` remains intact for legacy data and may contain a turn identifier;
`origin` supplies the explicit provenance for Companion. F1 serializes
these fields only when nonempty; old tape lines have an identical round trip.

Every `person_report` and `episode` refers to a specific source turn ID.
An `episode` may derive from two turn slots. Every `persona` refers to an
approved character revision, and superseding a revision preserves the old
version's history without making it active. Every `story` records its
continuity and fictional source. A `hypothesis` has confidence in [0, 1],
supporting turn IDs and a review/expiry policy. Summarization, rollup, or
repetition never changes a record's kind. A hypothesis is not promoted in
place; explicit confirmation creates a sourced `person_report`.

The person can correct a report. The replacement is a new record linked by a
first-class supersession edge, with the prior record marked `superseded`.
Recalling, searching, and assembling evidence exclude inactive records.
Administrative views may show the history with status and provenance.

## 3. Turn cycle

1. Authenticate; resolve the person, character and continuity root.
2. Read active records in this root; recall with bounded time/context.
3. Build labeled layers: person report, conversation episode, persona,
   fictional story and tentative hypothesis. Preserve provenance for each.
4. Generate a reply using the approved persona. Reference a past event only
   when supported by evidence. A story event is never attributed to real life.
   Pauses and returns do not trigger guilt or claims of exclusivity.
5. Return the reply and the IDs/provenance of memories actually used. A recall
   hit is not automatically a used memory.
6. If saving is on, extract eligible records under the policy in §2 and
   commit the turn slots and records, then invalidate dependent caches.

If saving is off, execute against a temporary clone of the selected root.
Replies may use prior authorized memories in the clone. All generated files,
logs, indexes, shadow events, caches, metadata and session updates remain in
the clone; delete it at the end. The canonical root receives **zero bytes**
from that turn. When the root did not exist, the save-off path does not create
it. No callback may independently write to the canonical root.

The v0 user controls are: see a memory with source, correct it, delete it and
choose whether this conversation saves. Save-off covers the entire turn,
including turn slots. The UI states the retention behavior accurately;
backup/provider retention is a separate policy to define before a pilot.

## 4. Corrections, deletion and derived material

`derived_from` means the child can contain information from the parent;
rollups and turn replies may use it. A supersession edge records the
replacement relationship separately from derivation. A correction must not
cause the old record to appear in recall, lexical search, payload,
cross-session results or cached responses. An older correction is retained
only in an administrative history.

Deleting a record walks the transitive `derived_from` closure, including
rollups that mention a deleted source. It also checks supersession
replacements and removes those that depend on the deleted content; a
replacement with an independently sourced new report needs an explicit
survival policy. The operation removes or invalidates recall caches, search
indexes, graph projections, summaries, whiteboard annotations, and any other
material that could reintroduce the content. Rehydration cannot reactivate
deleted or superseded data. A root-local monotonic high-water mark prevents
reuse of a deleted ID. A test deletes a source after rollup, reloads from
disk, recalls, searches and rehydrates to prove non-resurrection.

Deleting an extracted memory also removes its source turn slot and other
records derived from that turn. This deliberately erases more than the one
selected memory when a turn contains several facts; the UI must disclose the
linked deletion. The normal Companion recall surface selects the five typed
memories, while turn slots remain the interaction/provenance layer.

Deleting a whole relationship removes its complete root, including
continuity-specific state. This is a separate, explicit user action.

## 5. Evaluation contract

The F5 demonstration uses the eight steps in the Companion proposal:
report, later recall, correction, later recall of the correction, fictional
story, deletion and renewed recall. It also uses deliberate ID collisions
across roots. Gates are zero fiction↔real attribution, zero resurfacing of
deleted content, zero return to the old report after correction, and zero
cross-root leakage in the declared cases.

Before running the A/B lab, preregister dataset, split, prompts, model,
context budget, randomization, measures and stopping rule. A uses a simple
reference memory and B uses Memory Machine at the same model/context budget.
Report correctness, unsupported past claims, correction regression, fiction
mixing, deletion, isolation, latency and full cost. These are lab gates, not
evidence of general superiority. Pilot and packaging follow F5.

## 6. Small PR sequence

- F0: this contract only.
- F1a: optional `origin`, `author`, `event_time` fields and compatibility tests.
- F1b: atomic supersession with cache invalidation and active filtering tests.
- F1c: cascade deletion and non-resurrection tests.
- F1d: typed extraction and hypothesis policy tests.
- F1e: save-off isolation through temporary root clone, including zero-byte
  canonical-root assertions.
- F2–F6: persona, headless engine, UI, preregistered demo/evaluation, package.

Each PR must pass the repository's required checks before merge. The frozen
shadow run is checked only under its own stopping rule; Companion results
cannot be used to promote an admission policy.
