# Memory Lifecycle v1 — pre-registration

Frozen before any execution. Branch `memory-lifecycle-v1`; baseline `v0.2.0`
(`181441d`). Spec: `docs/LIFECYCLE_V1_SPEC.md`. Any change after this commit is
a new pre-registration.

## 0. Governance (provisional, 2026-09-22)

- Repository stays **private**; no GitHub Pro. Discipline substitutes for
  branch protection: every change lands via PR and merges only after the six
  CI checks are green; architectural changes record the run id.
- `scientific.yml` stays without a repository secret until this
  pre-registration is frozen and a run is explicitly authorized.
- The `0.2.0` tape and recall paths are untouched by this phase.

## 1. Question

Does an admission layer (event → episodic/semantic) reduce the consultable
memory set while preserving retrieval quality and future utility, compared
with the current "almost everything is memorized" behaviour?

## 2. Hypotheses and frozen gates

| # | Hypothesis | Operational gate (frozen for this run) |
|---|---|---|
| H-L1 | Lifecycle reduces the active (consultable) set | **≥ 40%** reduction on the fixture vs arm A |
| H-L2 | Promotion recall does not degrade beyond noise | `promotion_recall` ≥ arm A − measured floor (see §5) |
| H-L3 | Precision of promotions increases | `promotion_precision` strictly > arm A |
| H-L4 | Recall cost drops proportionally | `calls_online` and payload chars strictly lower, no category above floor |
| H-L5 | Retroactive retrieval restores false negatives | `retroactive_recovery_rate` ≥ **80%** of **recoverable** false negatives (see §5) |
| H-L6 | Hybrid beats rules only at justified cost | hybrid preferred over rules only if it gains ≥ 10 pp active-set reduction **or** ≥ floor of future-utility precision, at ≤ 1 extra LLM call per 5 candidates |

The 40% target is an **initial gate, revisable before execution**; once the
run starts it is not re-fit. Numbers are hypotheses, not scientific truth.

## 3. Substrate

- **Primary (committed, deterministic):** `eval/fixtures/lifecycle_v1/` built by
  `eval/gen_lifecycle_fixture.py` (seed `20260922`; the seed only composes and
  orders — the gold stays deterministic and inspectable):
  - `records.jsonl` — **classifier input only**: `memory_id`, `session`,
    `seq`, `text`, `tape_type`. It must never carry gold fields.
  - `gold.jsonl` — **separate file**: `gold_class`, hard-case markers and the
    planted pattern per record; never read by any rule or prompt.
  - `probes.jsonl` — question, `required_ids`, and the temporal position
    (`after_seq`): the admission decision always precedes the probe that
    measures utility.
  - `manifest.json` — hashes, counts, and the anti-leakage assertions.
- **Hard cases the fixture must contain** (one or more each):
  useful memory with low apparent importance (false-descart test); apparently
  important fact never used by any probe (precision test); semantic duplicates
  (paraphrase, not only identical text); corrections; negations; temporary
  preferences; decision changes; a valid repetition of a decision in a later
  period; a probe whose required evidence was never ingested
  (`unrecoverable_due_to_ingestion`, excluded from the H-L5 denominator).

### 3.1 Anti-leakage rules (binding)

- No rule, prompt or report computation of arms B/C may read `gold.jsonl`,
  `required_ids` or future probes. The classifier receives only
  `records.jsonl` content and its own history (previous decisions).
- A validator (`eval/validate_lifecycle_fixture.py`) fails if the input file
  contains gold keys, if probes reference unknown records, or if a probe's
  `after_seq` precedes its required records.
- Gold files stay out of the harness working directory used by the classifier.
- **Secondary (replay, qualitative):** the frozen `composition_u4` case tapes
  classified by tape `type` only (approximate; never used for gates).

## 4. Arms

| Arm | Consultable set | LLM |
|---|---|---|
| A | all records (baseline) | none |
| B | rules policy of the spec §4 | none |
| C | rules + LLM on ambiguous records (frozen prompt) | ≤ 30% of candidates, N=3 modal, `deepseek-v4-flash` |
| D | gold classes, small subset only | none |

## 5. Metrics (all computed on the fixture)

### 5.1 Frozen metric names and definitions

| Metric | Definition |
|---|---|
| `promotion_precision` | P(required by a probe \| promoted) — of the promoted records, how many were later required |
| `promotion_recall` | P(promoted \| required by a probe) — of the required records, how many had been promoted |
| `active_set_reduction` | 1 − (consultable set size / arm-A consultable set size) |
| `retroactive_recovery_rate` | `retroactively_found` / `recoverable_false_negative` |

Both precision and recall are frozen **separately**: a very conservative policy
must not look good merely because it promotes few, obvious memories.

- Final evidence recall (required record retrievable through the arm's recall
  path) is also reported and is the recall the H-L2 floor ultimately protects.
- `calls_online`, payload chars, admission calls, promotion rate per class,
  `false-descart` (semantic gold classified `event_only`/`reject`),
  `false-semantic` (event/episodic gold classified `semantic`), semantic
  duplication, introduced contradictions, time-to-promote, raw tape growth vs
  active-set growth are secondary.
- The decisive metric for whether the gate learns future utility is
  `promotion_precision`, read **jointly** with `promotion_recall`.

### 5.2 Retroactive counters (H-L5)

| Counter | Meaning |
|---|---|
| `recoverable_false_negative` | required record classified non-promotable **and** present in the event log |
| `retroactively_found` | recovered by the event-log search of the protocol |
| `retroactively_missed` | recoverable but not found |
| `unrecoverable_due_to_ingestion` | required evidence never ingested; excluded from the denominator |

An ingestion failure is never counted as a retroactive-mechanism failure.

**Noise floor:** measured on the fixture with the same protocol as the E/U
lines (identical-input oscillation). The floor is `max(7%, measured)` and is
registered before arms are read.

## 6. Protocol and stop rules

**Commit order (frozen):** (1) fixture + anti-leakage validator; (2) schemas and
deterministic normalisation; (3) arm B (rules only); (4) A/B/D report;
(5) arm C (hybrid); (6) retroactive retrieval; (7) frozen execution + gate
report. **A/B/D run before C**: if the rules arm already reaches the gates, the
hybrid must justify its extra call explicitly (H-L6).

1. Freeze fixture hashes; run arm B twice (normative content must be identical).
2. Run arm D on the small subset (ceiling only, excluded from promotion).
3. Run arm C (N=3 modal) within the call budget.
4. Apply gates of §2; report every metric in §5; commit results and the
   decision together.
5. **Stop rules:** if reduction ≥ 40% but recall falls beyond the floor →
   lifecycle stays shadow-only; if false-descart > 5% or false-semantic > 10%
   → policy is rejected for promotion regardless of reduction; if H-L6 fails →
   rules arm is preferred and hybrid is dropped; in every outcome the tape and
   defaults remain unchanged.

## 7. Promotion criteria for the main path (all required)

- active-set reduction ≥ target (H-L1);
- evidence recall within the floor (H-L2);
- no critical category regression beyond the floor;
- false negatives recoverable via the retroactive protocol (H-L5);
- total cost (admission + recall) improves over arm A;
- decisions reproducible: rebuilding the projection must be identical in
  **normative content** (decisions, classes, reason codes, input hashes,
  policy/config hashes) with `decided_at` excluded from the comparison, or the
  clock injected deterministically; hybrid outputs are frozen and re-read;
- `lifecycle_mode=off` reproduces `0.2.0` byte-for-byte;
- projection rebuild produces an identical `lifecycle/` tree.

## 8. Budget and seeds

- Fixture seed `20260922`; no stochastic component in arms A, B, D.
- Arm C budget: ≤ 30% of candidate records × 3 replicates; hard cap in the
  harness; provider failures are `INCONCLUSIVE_INFRASTRUCTURE` and are retried
  at most once (no silent spend).
- No dataset outside the committed fixture is touched; external datasets play
  no role in v1.

## 9. What this run may and may not claim

- May claim: measured effect on the committed fixture, under the frozen gates,
  with full per-class breakdowns and raw artifacts.
- May not claim: general utility on real session tapes, production readiness,
  or "better memory" beyond the fixture; those require the external phase
  (E4-style) after a promoted default.
