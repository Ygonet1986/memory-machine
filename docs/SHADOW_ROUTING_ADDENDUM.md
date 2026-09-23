# Shadow routing addendum — verifiable agent maps on the real window

Status: **pre-registered before the stop**. Date: 2026-09-23. Companion to
`docs/ADMISSION_SHADOW_V2_PREREG.md`; it does not modify that frozen
document and it executes **only at `met: true`**, on the same frozen
snapshot. No new LLM calls: it analyses the already pre-registered judged
subsample and the session tapes.

Declared scope: with **four real agent groups** (G1-G4 in the current
session's manifest), this measures the routing mechanism on real data; it
still does not promote anything - a product claim keeps requiring the
dual-track evaluation.

## 1. Inputs (frozen at the stop)

- The scored recalls and their logged candidate blocks (schema v2),
- the session `manifest.json` (groups G1-G4, ranges, agent ids) and tapes,
- the blind-judge diagnostics of the judged subsample (the pre-registered
  analysis): answering memory per recall, and for the "admission discard"
  class the discarded candidate.

`memory_id -> group` is resolved from the manifest ranges (deterministic).

## 2. Maps built offline (no schema change)

For every session with judged recalls, build per-agent **maps** from the
tapes: term -> record ids with dates (pointers only; no summaries). Map
search = product BM25 of the question against the group's record texts;
group score = best record score in the group.

## 3. Arms (per judged recall)

- **all-agents** - all groups of the session (baseline; 4 in the current
  session, fewer in others - reported per session).
- **map top-1** - best map score.
- **map + verification** - consult groups in map order until the
  question-token coverage of the consulted texts reaches tau = 0.5 or
  K_max = 3 groups were consulted; **tau is a stopping hypothesis, not proof
  of evidence** - gate S1 is the decisive test.
- **map ∪ tape top-3** - map top-1 plus the groups hosting the lexical
  top-3 candidates (reference).

## 4. Metrics and gates

Per judged recall: evidence-bearing group (from the judge's answering
memory, or the discarded candidate in the admission-discard class),
groups chosen by the map, groups rescued by the direct lexical path, final
activations. Aggregates: evidence-preservation rate, mean activations per
recall per arm, degenerate sessions reported (a session with one group has
nothing to route; its recalls are reported separately, not averaged in).

- **S1** evidence preserved: the map+verification arm's consulted groups
  include the evidence-bearing group in **every** judged recall where the
  all-agents arm does (no loss).
- **S2** economy: mean activations for map+verification < all-agents.
- **S3** determinism of map building and routing.
- **S4** pointers present in every map entry.

`all_pass` = S1-S4. Any failure: report, no re-fit; nothing promoted;
windows stay OFF.

## 5. Execution protocol

At `met: true`: freeze the logs (sha256 per file) as already pre-registered,
run the blind judge on the subsample, then run this companion analysis
(harness to be committed before execution:
`eval/shadow_routing_addendum.py`, outputs
`eval/results/shadow_routing_addendum/`), append the record, commit.
