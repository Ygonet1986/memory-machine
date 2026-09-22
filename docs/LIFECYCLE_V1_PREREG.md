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
| H-L2 | Evidence recall does not degrade beyond noise | probe recall ≥ arm A − measured floor (see §5) |
| H-L3 | Precision of retrieved memories increases | precision (required ∩ retrieved / retrieved) strictly > arm A |
| H-L4 | Recall cost drops proportionally | `calls_online` and payload chars strictly lower, no category above floor |
| H-L5 | Retroactive retrieval restores false negatives | ≥ **80%** of planted false negatives recovered by the event-log search |
| H-L6 | Hybrid beats rules only at justified cost | hybrid preferred over rules only if it gains ≥ 10 pp active-set reduction **or** ≥ floor of future-utility precision, at ≤ 1 extra LLM call per 5 candidates |

The 40% target is an **initial gate, revisable before execution**; once the
run starts it is not re-fit. Numbers are hypotheses, not scientific truth.

## 3. Substrate

- **Primary (committed, deterministic):** `eval/fixtures/lifecycle_v1/` built by
  `eval/gen_lifecycle_fixture.py` (seed `20260922`): synthetic project sessions
  whose records carry planted ground-truth classes, plus ~24 probe questions
  with `required_ids` mapping. The fixture fixes:
  - `records.jsonl` — record text, tape `type`, planted class, session id;
  - `probes.jsonl` — question, required record ids;
  - `manifest.json` — hashes; `lifecycle_mode=off` reproduces the untagged
    `0.2.0` behaviour on the same records.
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

Per arm: active-set size and reduction; probe evidence recall (required record
retrievable); precision; payload chars; `calls_online`; admission cost
(calls); promotion rate per class; **false-descart** (semantic gold classified
`event_only`/`reject`); **false-semantic** (event/episodic gold classified
`semantic`); semantic duplication; introduced contradictions; time-to-promote;
**P(used later | promoted)** and **P(promoted | used later)** where "used" =
required by at least one probe; retroactive recovery rate of planted false
negatives; raw tape growth vs active-set growth.

The decisive metric is `P(required by a probe | promoted)` — whether the gate
learns future utility, not whether its classifications look plausible.

**Noise floor:** measured on the fixture with the same protocol as the E/U
lines (identical-input oscillation). The floor is `max(7%, measured)` and is
registered before arms are read.

## 6. Protocol and stop rules

1. Freeze fixture hashes; run arm B twice (must be byte-identical).
2. Run arm D on the small subset (ceiling only).
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
- decisions reproducible (rules: identical rebuilds; hybrid: frozen outputs);
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
