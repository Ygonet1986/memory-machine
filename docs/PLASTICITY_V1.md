# plasticity-v1 — pre-registration (Fase P, P0)

**Status: pre-registration frozen · P0 closed: `7cd3251` + `93708e1` (426
green) · P1 observe EXECUTED: `eval/plasticity_observe.py` + run
`eval/results/plasticity_u42_observe/run1` (determinism proven; empty ledger ⇒
**0/30** cases would change — instrument verified) · precedent: doc-graph-v1
gate (`doc-graph-v1` tag, closed), U4.2 oscillation floor, M0150 pre-registration
discipline.

This document registers, before any plasticity experiment or delivery run,
the exact question, layers the system may and may not touch, the `EdgeKey`
identity, the ledger schema, the energy model, the mechanical signals, the
update rule with its constants, the modes, the stop criteria and the
non-goals. Nothing below is chosen after seeing results.

Fase P is the **utilization** line (see `docs/GRAPH_UTIL.md`): it learns
*which paths to navigate*, never what a document "said". It is a navigation
prior over the graph — salience and attention, not truth.

---

## 1. Decision question

> Given a stored Memory Machine project with a built graph, can the system
> learn **which paths to navigate** (edge utility) from mechanical,
> provenance-checked signals — without ever altering the tape, the graph, the
> evidence or the recall contract, and without contaminating the base
> `plasticity_mode="off"` behavior?

The question is narrow by design. It gates **navigation preference**, not
entity extraction, not evidence, not answers. A learned reordering that
degrades delivered gold (any metric below) or that cannot be fully reversed
rejects the phase.

## 2. Layers: what may and may not change

| Layer | Mutability under Fase P |
|---|---|
| Tape (`tape.jsonl`) | **immutable** — never written, never altered |
| Documents / originals | **immutable** — never rewritten |
| Entities & relations (graph projection) | **immutable** — never added, removed or modified by plasticity |
| Evidence | **immutable** — never forged or dropped; all learned state is provenance-gated |
| Recall contract (paths → evidence, `guard_evidence`, `question_gate`) | **immutable** — plasticity only *reorders* candidate paths inside the same search space |
| **Edge utility ledger** (`<root>/plasticity/`) | **the only mutable object** — derived, disposable, replay-reconstructible |
| Query activation state | per-query transient — never persisted |

Documental relations may be used in an experiment but never enter default
recall without a separate evaluation.

## 3. Guards (P0, binding)

1. `plasticity_mode="off"` leaves every prior behavior **byte-equivalent**.
   P0 wires nothing into recall; the ledger exists and is inert.
2. `UtilityLedger` never touches Tape, graph, evidence or recall. It only
   **records events and reconstructs derived state** under `<root>/plasticity/`.
3. `EdgeKey` uses `extraction_scope` as part of identity; `R####`, document
   and memory ids stay **audit-only**, never resolution criteria.

## 4. Edge key identity

A navigable edge is identified by the semantic, stable tuple:

```text
EdgeKey = (source E####, canonical verb, target E####, extraction_scope)
```

Canonicalization (from a graph relation row):

- `source`, `target`: entity ids verbatim (non-empty, else `?`).
- `relation`: verb `strip().lower()`.
- `extraction_scope`: `strip().lower()`; empty → `chunk`.

`R####`, `source_document` and `memory_id` are ignored for identity; they may
appear as audit fields on the ledger line but never participate in matching.
Two relations of the same semantic edge (re-extractions) collapse to one key.

## 5. Ledger schema

Storage, all under `<root>/plasticity/` (a `.gitignore`-enclosable, disposable
project state — never a factual source):

- `events.jsonl` — **append-only source of truth**; one JSON object per
  `record`, carrying `ts, key, signal, query, path_ref, evidenced, reinforced,
  before, after, lam, eta, policy_version`.
- `utility.jsonl` — append-only **materialization**; last row per key wins on
  load (crash-safe, no rewrite on append).
- `rebuild()` — replays `events.jsonl` from scratch (deterministic; event λ/η
  are replayed) and rewrites `utility.jsonl`.
- `delete`/`reset()` — event + materialized files removed ⇒ **baseline
  restored** (full reversibility).

Per-key row: `key, utility, observations, successes, failures,
last_updated, policy_version`.

Every update that changes state is `policy_version`-tagged. Changing the
policy (constants or signal set) is a **re-pre-registration** and starts a new
versioned ledger, never a silent mutation of the archived one.

## 6. Energy model

```text
E(path | q) = D + H − wᵤ · U + R
```

- `D` — mechanical **query distance**; a deterministic score computable from
  query terms and/or frozen snapshot coverage (defined at P1, measured
  off-line; it is the only component that depends on the query).
- `H = hop_cost · max(0, semantic_depth − 1)` — path length cost.
- `U` — mean over the path's edges of the **shrunk utility**
  `u_eff = u · n / (n + k)` (few observations ⇒ low confidence, no self-
  fulfilling loops from a single hit).
- `R` — risk penalties (evidence-gate veto, low-confidence held evidence,
  long hops, cycles, few observations, cross-document mixing without a
  document link), each ≥ 0; a vetoed path is removed from candidates before
  ranking, an otherwise penalized path stays but costs more.

Lower `E` is preferred. The base mode is the frozen control: `observe` ranks
with read-only ledger (no mutation), so the delivered ranking is byte-identical
to `off`.

## 7. Update rule with pre-registered constants

```text
u' = clip((1 − λ) · u + η · s, −min, max)
```

| Constant | Value | Meaning |
|---|---|---|
| `λ` | `0.01` | decay per update |
| `η` | `0.10` | learning rate of the mechanical signal |
| `min` / `max` | `1.0` / `1.0` | bounds → `u ∈ [−1, +1]`: permanent dominance impossible |
| `k` (shrinkage) | `5.0` | `u_eff = u·n/(n+k)` |
| `hop_cost` | `0.15` | per extra hop |
| `wᵤ` | `0.5` | weight of learned utility in `E` |

Signals: negative for harmful outcomes, positive for beneficial; each update
is an aggregated mechanical composite (weights sum to 1, composite clipped to
`[−1, 1]`). `s` is never derived from `answer_correct` or any labeled outcome —
only from objective, reproducible properties of the *search* (M0155).

### 7.1 Provisionally registered mechanical signals (weights pre-fixed here)

P3 applies these composites; P2 measures them on frozen snapshots first.

| Signal | Weight | Definition (mechanical) |
|---|---|---|
| `fact_presence` | `+0.60` | edge on a path whose delivered evidence was present in the answer window |
| `wasted_context` | `−0.40` | edge on a path whose evidence was delivered but unused/trailed the composition |
| `multi_evidence_complete` | `+0.30` | path completed multi-evidence coverage for the fact it served |
| `budget_respected` | `+0.10` | stayed within the recall budget at fixed `graph_top_k` |
| `cross_document_leak` | `−0.60` | path mixed documents without a document link (also blocks reinforcement) |

A composite is only formed for paths with valid provenance; `evidenced=False`
edges are logged but never reinforced (guard: no reinforcement without
provenance).

## 8. Modes

```text
plasticity_mode: off | observe | shadow | update | deliver   (default: off)
```

- `off` — ledger inert; byte-equivalent baseline.
- `observe` — read-only: logs would-be rankings and computes signals against
  frozen snapshots; never mutates the ledger, never changes delivered results.
- `shadow` — full simulation on a copy: ledger evolves in-memory/on a fork,
  delivered results still run from the base; produces the comparison table.
- `update` — live ledger applied to recall, full reversibility audit retained.
- `deliver` — pre-registered, evaluated delivery (gated like doc-graph-v1;
  tagged only after the joint reading of metrics + reversibility).

## 9. Metrics and stop criteria (P2 shadow, then P3/P4)

Primary: **fact-presence** (delivered-evidence-gold, per U-line) and
**wasted-context**; secondary: AUR-gold-delivered, multi-evidence coverage,
budget adherence, ordering stability. Primary query set: **U4.2 (30 cases,
frozen local snapshots)**; optional smoke: committed synthetic 32
(`eval/view_router_bench.py`).

Decision order (P2 shadow, mirrors M0150): (1) no overload regression (any
primary metric — no usability of *all* skills) first; (2) then
`repairs − regressions`; (3) prefer the least invasive winner.

Stop criteria — any one rejects the phase:

- no reproducible, floor-clearing gain on a primary metric
  (U4.2 oscillation floor **0.07–0.08**);
- any primary-metric regression on the frozen base;
- reversibility broken (ledger state not fully reconstructible from events);
- `plasticity_mode="off"` byte-behavior drift.

## 10. Non-goals

- No entity/relation/evidence creation, editing or deletion by plasticity.
- No answer-quality labels as signals (`answer_correct` is never a signal).
- No change to `guard_evidence`, `question_gate`, admission or I5 promotion—
  these stay non-learned controls above the plastic layer.
- No defaults, PAPER/RESULTS figures or historical behavior change; doc-graph-v1
  and the U-line remain closed.
- No secrets or credentials in the ledger (events carry queries/paths only).

## 11. Harness and result convention

Harness lives in `eval/` per phase (`eval/plasticity_shadow.py`, `--fake`
deterministic self-check included); results are archived under
`eval/results/<run>/` as `json` + `summary.md`, committed with the
`results:` prefix like doc-graph-v1. This section is where run tables are
appended as phases execute. Nothing below overrides §3 guards.

### 11.1 Operational definition of D (P1) and P1 execution record

**D (P1).** `D(path) = 1 − base_score`, where `base_score =
bottleneck_edge_confidence · 0.85^(depth−1)` already carries the hop and
evidence-gate penalties. In P1 `H = R = 0`: with an empty ledger
`U_eff = 0 ⇒ E = 1 − base_score`, so the plastic ordering is provably
byte-identical to the base ordering; any divergence a future run reports is
purely learned-nav driven. H and R enter live ranking in later phases **only**
by re-pre-registration.

**Harness.** `eval/plasticity_observe.py` (read-only): frozen U4.2 snapshots
(`eval/graph_out/graphs/longmemeval/case_*` + frozen `graph_bench_*` benches),
`--fake` synthetic self-check (empty-ledger identity + ledger-loaded order
flip), per-case base-vs-plastic paths/energy/evidence/targets/budget table,
two identical iterations per run for determinism, and a mutation guard that
aborts (exit 2) if anything under the snapshot or ledger dirs changed.

**Run `plasticity_u42_observe/run1`** (`git_commit 93708e1`, ledger empty,
config default depth/top_k/max_paths + `wᵤ=0.5`, `hop_cost=0`):

- cases: 30 (U4.2 u3a 12–26 + u3b 27–41); 24/30 resolve a non-empty search
  space (cases 17, 20, 33, 34, 37, 41 have no seeds — empty under both arms).
- determinism: **True** — both iterations byte-identical
  (sha1 `3d9df4dc…`).
- **changed: 0/30** — order, evidence set, delivered targets, missing targets
  and budget all equal with the empty ledger; the auditable "what would
  change" table shows nothing would change yet, as designed.

P2 may now measure whether a populated ledger clears the 0.07–0.08 historical
floor against this instrument.