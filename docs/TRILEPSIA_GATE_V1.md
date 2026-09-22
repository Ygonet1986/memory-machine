# trilepsia gate B2 vs B2+ — execution pre-registration (V1)

Frozen 2026-09-16 before any gate LLM call. Registers the execution details of
`docs/TRILEPSIA_GATE_SPEC.md` (40dccd6) and T0 (`docs/TRILEPSIA_V1.md`,
33c8075, R1–R5). Any change after this commit is a new pre-registration.

## 1. Fixture build (one-time, frozen before any arm runs)

`eval/gen_trilepsia_gate.py`, frozen order (spec §6 contamination rule):

1. `--phase docs` — 10 planted documents under `documents/` (deterministic).
2. `--phase build` — **one** LLM extraction pass over the documents:
   `Machine.ingest_document` per file (tape chunks + registry + originals +
   graph, graph-v3 defaults) and `trilepsia ingest` per file
   (declared schema `gate_claims_v1`, window 12000, extractor `trilepsia/v1`).
   The extractor never sees a question or the gold.
3. `--phase cases` — `cases.jsonl` (deterministic, offline; never reads the
   extraction).
4. `--phase manifest` — sha256 of every frozen file + one global sha1.

Offline phases are byte-reproducible (verified twice: cases sha1
`d62105d232dfe435d7c57fc71bb886b735140222`, manifest sha1
`2efa70854823beaae6493c4fd91b0a5dd05ba23b`). The build output (tape, graph,
units, originals) is committed and is the only substrate both arms read.

## 2. Cases (frozen inventory: 36)

- **20 factual** (`gold_state = null`): joins/arithmetic/max-min/values across
  D2/D4/D6/D7/D9/D3/D8 (`g001`–`g020`).
- **16 epistemic**, gold state token: `reported_vs_measured` 3 (`e001`,`e002`,
  `e016`), `contested` 2 (`e003`,`e004`), `refuted_under_X` 2 (`e005`,`e006`),
  `supported_under_X` 2 (`e007`,`e008`), `superseded` 2 (`e009`,`e010`),
  `unknown` 2 (`e011`,`e012`), `causal_caution` 2 (`e013`,`e014`),
  `domain_scope` 1 (`e015`).
- Each epistemic case's qualifying evidence is planted late in its document
  (beyond the precise payload's head), so the B2 arm cannot co-deliver it;
  B2+ reads the typed unit. This is the operationalization of R1
  ("B2 lacks the state by construction") and it is a design property of the
  frozen corpus, not an outcome-dependent choice.

## 3. Arms (frozen)

- **B2** — graph recall (`augment_guarded`: `min_score=0.80`, `max_items=3`,
  `hub_degree=20`, question gate OFF) → annotations merged with the frozen
  agent side → `build_evidence_payload` (budget 4000, no window) → context.
- **B2+** — the same B2 context plus the **Trilepsia augment**:
  - unit selection: units whose `derived_from` intersects the B2 candidate
    memory ids (or whose document is among the candidates), ranked by
    (−overlap, unit memory id), capped at 3 units (graph-family `max_items`);
  - rendering per unit: `[M#### | schema | scope]` + for each observation
    `(kind) "<exact content>"`, hypotheses `(state) statement`,
    qualifications `attr=value (evaluated)`, unknowns `unknown: …` — exact
    quotes only, no paraphrase;
  - **one global 4000-char budget**: B2 items keep their allocations; unit
    blocks fill the remainder in rank order; blocks that do not fit are
    dropped and counted. Calls/query identical in both arms (no extra LLM).
- Same questions, order, prompts, temperature, model, judge, batch; only the
  context differs.

## 4. Measurement (frozen)

- **N = 5** replicates per case-arm (covers the spec's N=3 oscillation
  minimum; modal verdicts).
- **Primary**: paired Δ strict (correct vs not; `partial` ≠ correct) between
  B2 and B2+. Promotion requires `net = repaired − regressed ≥ +3` **and**
  `net` above the measured identical-context pair flip rate on this fixture
  (measured from the same N=5 replicates; `max(inherited 0.07–0.08, measured)`).
- **Secondary**: **qualification accuracy** on the 16 epistemic cases — the
  judge returns a state token and the exact `gold_state` must match; B2+ must
  strictly exceed B2.
- **Guards**: atom retention on factual required refs (no material drop);
  provenance validity 100% of rendered unit claims (exact-span re-check);
  budget parity (≤4000 chars, equal calls); deterministic context rebuilds.
- **Refutation (paper §10)**: Δ ≈ 0 or no qualification gain ⇒ verdict
  "provenance layer"; T3 does not run.

## 5. Judge prompts (frozen)

- Verdict prompt: the frozen `e2e_bench.judge` (correct/partial/incorrect)
  against `gold_answer`.
- State prompt (epistemic cases only, second call): the judge receives the
  question, the candidate answer and the allowed tokens; it returns one token
  from `{reported, observed, contested, refuted, supported, superseded,
  unknown}`; exact match to `gold_state` scores 1. Unknown/indeterminate is
  not free: a determined wrong answer or an unjustified token scores 0.

## 6. Outputs and closure

`eval/results/trilepsia_gate_v1/`: `answers.jsonl` (raw answer + both judge
outputs + reasons), `contexts.jsonl`, `atoms.jsonl`, `paired_ledger.jsonl`,
`e4_summary.json`, `summary.md`, `run_manifest.json`. Results and the gate
decision are committed together; no criterion is adapted after execution; T3
stays blocked unless the gate passes.

## 7. Non-goals

No changes to T1, graph/delivery defaults or the corpus after the first arm
result; no T3; no tuning of cases/prompts/budget/thresholds; no re-use of the
E1/E2 substrates for this gate.

## 8. Execution record (registered verbatim, no criterion re-fit)

Run `eval/results/trilepsia_gate_v1` (harness + fixture commit `f65970b`;
fixture sha1 `cec309defe1acecb82adbf57e08a6e8f76cfe533`; N=5; model/judge
`deepseek-v4-flash`; 360/360 case-arm-replicates). One harness hang occurred
mid-run (urllib connection held; known mode) and the run was resumed from the
written rows — resume-safe by design, protocol unchanged. Raw answers+jurors:
`answers.jsonl` (sha1 `719e0612…`); summary `e4_summary.json` (sha1
`6314c6e5…`) + `summary.md` (sha1 `70fe4acd…`); ledger in
`paired_ledger.jsonl`.

**Results:**

| metric | B2 | B2+ |
|---|---:|---:|
| strict modal | 25 correct | 24 correct |
| qualification accuracy (16 epistemic cases) | 0.5625 | 0.5500 |
| factual atom retention | 0.825 | 0.825 |

- paired ledger: `stayed_correct 24`, `stayed_incorrect 11`, `regressed 1`,
  `repaired 0` ⇒ **net −1** (the single change, e011, went correct → partial).
- measured identical-context pair flip rate: **0.1389** (effective floor
  `max(0.07, measured) = 0.1389`).
- guards: provenance failures 0 · deterministic True · budget_ok True ·
  atom guard True.

**Gate (frozen §4): primary false (net −1, below both +3 and the measured
floor); secondary false (qualification 0.5625 → 0.5500).** Promotion
conditions fail ⇒ **verdict: provenance layer only — no demonstrated
analytical gain; T3 is blocked** (paper §10 refutation path).

**Honest reading:** the B2+ augment changed the modal answer in only 1 of 36
cases, and the typed epistemic blocks did not improve qualification accuracy —
B2 already reached 0.5625 on the state token task from plain text under the
same budget, so on this substrate/model the added structure did not convert
into measurable analytical value. The structural T1 guarantees (provenance,
exact spans, budget) all held. No criterion or case was changed after
results; the full ledger (including oscillations) is preserved.
