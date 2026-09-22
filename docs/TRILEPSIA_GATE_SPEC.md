# trilepsia gate (B2 vs B2+) — fixture specification

**Status: specification only.** No corpus generation, no harness, no LLM call
may run before E2 closes at 300/300 and its frozen gate (§11 of
COMPOSITION_V1.md) is applied and committed. This document prepares the
transition authorized by the user (2026-09-16); it executes nothing.

Frozen contract it operationalizes: `docs/TRILEPSIA_V1.md` §8 (T0, commit
33c8075), ressalva **R1** — the gate must be **B2 vs B2+**, never B1 vs B2,
because the Memory Machine already has the graph (B2 exists without Trilepsia).
The question the gate answers: *does the Trilepsia add retrievable analytical
evidence beyond the graph, under a matched budget?* If Δ ≈ 0, the verdict is
"provenance layer" and T3 does not run.

## 1. Substrate

- A committed machine root `eval/fixtures/trilepsia_gate_v1/` containing, frozen
  once before any gold is consulted:
  - the planted corpus texts under `documents/` (with the registry + hash gate
    of the document layer);
  - the tape (chunk memories + `trilepsia_unit` records with raw envelopes);
  - the graph projection (graph-v3 defaults, `augment_guarded`, question gate
    OFF) built over the same tape;
  - `manifest.json` with per-file sha256 and one global sha1.
- Deterministic generator `eval/gen_trilepsia_gate.py` (to be written after E2):
  same seed → byte-identical docs, cases and gold.
- Extraction runs **once** at build time: graph extraction (existing) and
  `trilepsia ingest` (T1, declared schema `gate_claims_v1`). T1's temporal
  isolation applies: the extractor sees only its window; no question or gold
  ever enters extraction (asserted by the harness).
- The gate itself runs **no extraction**: only answerer + judge (the raw
  envelopes and the graph are frozen artifacts).

## 2. Corpus (10 documents, 1–2k chars each)

A fictional ops project ("Nimbus") with planted, self-consistent facts:

| doc | content planted | role |
|---|---|---|
| D1 | project log: user **reports** (second-hand claims) | `reported` |
| D2 | measurement log: instrument readings with units/dates | `observed` |
| D3 | incident note: failure after an update (association only) | causal caution |
| D4 | changelog: update 2.3 supersedes an earlier config | `superseded` |
| D5 | support thread: two **contested** reports about one value | `contested` |
| D6 | experiment log: controlled temperature sweep (intervention) | `supported under X` |
| D7 | measurement that **refutes** a claim under a stated condition | `refuted under X` |
| D8 | conventions/spec: local definitions and scope (`V.scope`) | schema/scope |
| D9 | numeric table used by composition joins | factual joins |
| D10 | note where the needed datum is absent | `unknown/indeterminate` |

The planted facts are cross-referenced so composition cases need pieces from
≥2 documents, and epistemic cases need the **state**, not just the text.

## 3. Cases

`cases.jsonl`, one row per case:

```json
{"case_id": "g001", "class": "factual", "type": "join|difference|max_min|...",
 "question": "...", "gold_answer": "...", "gold_state": null,
 "required_refs": ["D1#w01", "D2#w02"], "notes": "..."}
```

- `class=epistemic` carries the canonical `gold_state` token instead of `null`
  (`reported|observed|supported|contested|refuted|superseded|unknown`).

Composition of the set (frozen counts):

- **factual ≈ 20** — joins/arithmetic/comparisons across documents with exact
  gold answers (`gold_state = null`).
- **epistemic 12–16, ≥2 per type** (frozen minimums): `reported vs measured`,
  `contested`, `refuted under X`, `supported under X`, `superseded`,
  `unknown/indeterminate`. Each carries the canonical `gold_state` token;
  "supported"/"refuted" cases also name the condition X in the gold answer.

Design rule (R1 operationalized): for every epistemic case, **B2 lacks the
state by construction** — the evidence may exist in the corpus, but B2's
budgeted text payload does not co-deliver the conflicting pair nor register the
epistemic qualification; B2+ sees the typed unit (`kind`, `state`,
`assumptions`, `unknowns`). If a question is answerable equally well from the
plain text under the same budget, it does not measure the thesis and must not
carry the secondary metric.

## 4. Arms (frozen)

- **B2** — current pipeline: graph recall (`augment_guarded`, question gate OFF)
  + precise payload (4000 chars). No Trilepsia.
- **B2+** — B2 + Trilepsia augment (`trilepsia_recall_mode=augment`, graph-family
  gatekeepers `min_score=0.80`, `max_items=3`, `hub_degree=20`, **one global
  budget applied after the union**, T0 §9).

Identity: same questions, same candidate order, same prompts, same model/judge,
same batch; only the context assembly differs. Both arms read the frozen
fixture; neither calls the extractor.

## 5. Metrics and gate (frozen)

- **Primary**: paired **Δ strict/AUR B2 → B2+** per case (`correct` vs not;
  `partial` ≠ correct). Promotion requires
  `net = repaired − regressed ≥ +3` **and** `net` above the measured
  within-arm oscillation on this fixture.
- **Floor measured on the fixture**: within-arm oscillation at N=3 (same
  protocol as U4.2); effective threshold `max(inherited 0.07–0.08, measured)`,
  registered before arm results are read (T0 §8/R3).
- **Secondary (must point the same way)**: **qualification accuracy** on the
  epistemic cases — exact `gold_state` match (and condition X named where
  applicable). B2+ must strictly exceed B2 on this set.
- **Guards (all required)**: provenance validity 100% on every rendered
  claim; budget parity (calls/query equal; context chars within the same
  4000 budget); deterministic context rebuilds (byte-identical iterations);
  no material drop in atom coverage on factual cases.
- **Refutation (paper §10, frozen)**: Δ ≈ 0, or a text-equivalent memory
  obtains the same benefit ⇒ verdict **"provenance layer"**; T3 does not run.

## 6. Contamination controls (frozen)

1. The corpus and the frozen extractions exist **before** the cases/gold are
   generated; the gold generator is deterministic and never touches the
   extractor.
2. Extraction prompts contain no question (T1 enforces this by construction).
3. One seed, reserved combinations; no case is edited after the first arm
   result; the fixture is committed before execution.
4. B2 and B2+ share the frozen artifacts; no arm sees the other's context.

## 7. Deliverables after E2 closes (none of them now)

1. `eval/gen_trilepsia_gate.py` + committed fixture
   `eval/fixtures/trilepsia_gate_v1/` (+ manifest, sha256).
2. `eval/trilepsia_gate.py` (arms, judge, ledger, gate application).
3. `eval/results/trilepsia_gate_v1/` (raw answers, contexts, ledger, summary).
4. A pre-registration addendum (§12 of TRILEPSIA_V1.md or a new
   `docs/TRILEPSIA_GATE_V1.md`) registering this spec verbatim before execution.

## 8. Non-goals

No runner, generator or fixture implementation before E2 closes; no LLM calls;
no changes to graph defaults, delivery flags or T1; no tuning of cases, prompts,
budget or thresholds after results; no T3 without a passing gate.
