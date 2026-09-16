# trilepsia-v1 — pre-registration (T0)

Frozen 2026-09-16, before any Trilepsia LLM call, after the T0 review approved
2026-09-16 with five binding reservations (R1–R5). This is the binding record;
the code implements no rule absent from it. Any change after the T0 commit is a
new pre-registration.

## 1. Decision question

Does a typed **investigation projection over .txt ingestion** (Trilepsia) add
retrievable evidence **beyond the existing graph**, under a matched budget?

Scope: the **B2 half of T2TC** — structured investigation memory, typed
evidence, epistemic discipline, provenance (paper §3–§5, §7). Parametric
adaptation (φt/LoRA, §4/§6) is **out of scope**; the Memory Machine does not
train networks and no parametric-transfer claim may be made. The mapping to
the manual: Trilepsia is a projection like `views/` and `graph/` (§44), and
its query policies are the prospective memory of §13.4.

## 2. Sources of record

- Paper: `~/Downloads/transformer-2-trilepsia-cognitiva.pdf` (v1.0,
  2026-09-16): §3 (Trilepsia formulation), §4 (architecture: typed memory,
  extractor, epistemic states, causal edge rule), §5 (causality and
  identification limits), §7 (operational cycle), §10 (baselines, metrics,
  refutation criteria, contamination rules).
- Manual: `~/Downloads/Memory-Machine-Manual-e-Whitepaper.txt` §44 (graph as
  reconstructable projection; extractor contract; atomic rebuild; document
  layer/originals hash gate) and §13.4 (prospective memory).
- This doc pins what was read; if the sources move or change, that is a new
  pre-registration.

## 3. Frozen schema (R1/R2/R5)

**X is declared at ingestion** (`trilepsia ingest --schema <id>`; the paper
treats X as problem data, §3). `auto` exists only as an explicit opt-in; when
used, the chosen schema **is persisted in the raw JSON** and never recomputed.
The schema vocabulary for the gate corpus is frozen before any gold is seen.

Fields (a Trilepsia unit, paper §3): `X` typed schema id · `O` objects/entities
· `E` events · `Q` qualifications · `D` observations · `H` competing
hypotheses · `Π` query policies · `Ω` observability/unknowns · `V`
versions/provenance/permissions/validity.

Epistemic states (paper §4): `reported` · `under_investigation` · `supported`
(under the registered conditions — never "universal truth") · `contested` ·
`refuted` (under the registered conditions). An observation about a measurement
**remains a report** until the measurement itself is available. Absence of
evidence is not a negative observation. For multiple qualifiers the record
states which were **actually evaluated**; the rest remain unknown.

Typed relations (paper §4): `refers_to`, `precedes`, `contradicts`, `supports`,
`tests`, `causes_under_assumptions`. **Only the last may carry causal
meaning, and only with a registered intervention or explicit `assumptions[]`**
(paper §4/§5). Textual and causal relations are not interchangeable; a system
prediction is not new external evidence.

## 4. Provenance invariants (R2)

- **Selects; does not supply.** A unit and its typed records carry
  **references**: `derived_from: [M####]`, `source_id: D####`,
  `source_span: (start,end)`. The factual text delivered to any answerer is
  **rehydrated from the tape / preserved original** (the `graph explain`
  pattern), never a second free-text copy.
- `trilepsia_observation.content` is validated as an **exact excerpt within
  its `source_span`** of the preserved original: character-exact, reversible
  offsets (`original[start:end] == content`; the E0 atom validator is the
  tool). Normalization or paraphrase invalidates the record.
- T2 proves **100% provenance**: every claim rendered to an answerer has a
  rehydration path unit → ref → memory → original, and every excerpt passes
  the exact-substring check.

## 5. Raw JSON and rebuild determinism (R4)

- The extractor's raw JSON is stored **on the tape** in the unit record, in a
  stable envelope: `{schema_version, extractor, extractor_version, raw}`;
  `raw` is opaque to consumers. It survives archive/rollup and needs no
  second artifact.
- Idempotency key: `(memory_id, extractor, extractor_version)`. Same version
  is a no-op; a different version requires an explicit `--rebuild`.
- **Rebuild is deterministic and never invokes the LLM**: the projection is
  derived from tape units + raw envelopes only. (The extraction happened once,
  at write time; its instability cannot leak into rebuilds.)

## 6. Temporal isolation (R5)

1. The extractor sees **only the current window** (no later windows, no
   document-level future context).
2. **The question never enters the extraction prompt** (ingestion ≠ recall).
3. The **schema vocabulary is frozen before the gate**; an `auto` choice is
   persisted in the raw and not recomputed.
4. For the gate corpus, extraction runs once and the raw is frozen **before
   any gold is consulted**; the gate's only LLM calls are answerer + judge.

## 7. Capacity policy (R4)

- Caps per window (extractor output; excess is **counted** in `dropped` on the
  unit — never silently truncated): entities ≤12, events ≤12, qualifications
  ≤12, observations ≤10, hypotheses ≤6, query_policies ≤6.
- Rollup: Trilepsia units, hypotheses and observations are **excluded from
  age-based rollup** (§15.3). Any consolidation groups by `schema + scope +
  validity`, preserves `derived_from`, and **never merges epistemic states**
  (contested/refuted do not expire).
- Coverage limits of an approximate hypothesis search are **recorded in the
  unit's `Ω`** (no uniqueness claims; paper §3/§5).

## 8. Gate B2 vs B2+ (R1 + R3) — frozen

- Substrate: a **purpose-built planted corpus** (deterministic generator,
  ~8–12 documents of 1–2k chars) containing: factual composition cases
  (~20) and **12–16 epistemic cases** (≥2 per type: `reported vs measured`,
  `contested`, `refuted under X`, `supported under X`, `superseded`,
  `unknown/indeterminate`).
- Arms: **B2** = current pipeline (graph + precise payload), **B2+** = B2 +
  Trilepsia augment. Same questions, same candidate order, same budget
  (**calls/query and chars matched**), same model/judge/batch.
- Primary: **paired Δ strict/AUR B2 → B2+** (not absolute values).
- Secondary (operationalized): **qualification accuracy** on the epistemic
  cases — B2+ must get the epistemic state right where B2 lacks the facts to.
- **Floor measured on this fixture**: within-arm oscillation at N=3 per case
  (same replication protocol as U4.2, whose identical-context pair flip rate
  was A 0.082 / B 0.073, `eval/graph_out/u4_replication_summary.md`); the
  effective threshold is `max(inherited 0.07–0.08, measured-on-fixture)`,
  registered before looking at arm results.
- Refutation (paper §10): if Δ ≈ 0, or if a text-equivalent memory obtains the
  same benefit, the verdict is **"provenance layer"**, not "recall" — and T3
  does not run.
- Contamination (paper §10): train/validation/test separated by mechanism and
  evidence lineage; the question never enters extraction; the gold never
  enters extraction or the schema choice.

## 9. Operational surface (T1+)

- Config (defaults off; flag-off byte-equivalent): `trilepsia_enabled=false`,
  `trilepsia_recall_mode=off`, `trilepsia_window_chars=12000`,
  `trilepsia_batch_size=8`, `trilepsia_max_attempts=3`; augment gatekeepers
  reuse the **graph family** (`min_score=0.80`, `max_items=3`,
  `hub_degree=20`).
- CLI: `trilepsia ingest|status|show|pending|failed|retry` (T1) and
  `query|explain|rebuild|review` (T2/T4).
- Permissions (`local_memory`, `local_training`, `shared_training`; default
  `{true,true,false}`) are **filtered before retrieval**, not alongside it.
- Recalls read a **versioned snapshot** of the projection.

## 10. Phases and deliverables

- **T1**: `src/memory_machine/trilepsia.py` — extractor (window 12k, batch 8,
  attempts 3; the `graph_extract` pattern), item-wise validator, unit + typed
  records on the tape with raw envelopes, CLI `ingest|status|show`, pending/
  failed queues; deterministic validator tests (no LLM).
- **T2**: `trilepsia/` projection (units/entities/events/observations/
  hypotheses/queries/versions/meta), atomic rebuild with the originals hash
  gate, `explain` (edge → entity → memory → span → original), and the
  round-trip test mirroring `tests/test_document_rebuild.py` (ingest →
  snapshot → drop projection → rebuild → equivalence; missing/altered
  original aborts; re-run idempotent).
- **GATE**: B2 vs B2+ on the planted corpus (the only honest kill point).
- **T3**: recall `off|augment|only` + the three gatekeepers + telemetry
  (`trilepsia_only`, `overlap`, `fallback_rate`); open hypotheses into the
  whiteboard's understanding and query policies into the checklist.
- **T4**: append-only review (`reviews.jsonl` with `derived_from`), retention
  checks; no regression of the existing suite.
- **T5**: benchmarks `epistemic_accuracy` and `provenance_completeness` under
  matched budget.

## 11. Non-goals (frozen)

Parametric adaptation / T2TC training claims; inferred schema vocabulary
changing after gold; factual payload copies in units; age-based rollup of
investigations; multimodal inputs; any change of existing defaults.
