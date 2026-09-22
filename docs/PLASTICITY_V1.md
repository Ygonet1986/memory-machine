# plasticity-v1 — pre-registration (Fase P, P0)

**Status: pre-registration frozen · P0 closed: `1e764ab` + `f7232d3` (426
green) · P1 observe EXECUTED (`eval/plasticity_observe.py` + run1; determinism
proven; empty ledger ⇒ **0/30** changed) · **P2 shadow EXECUTED**
(`eval/plasticity_shadow.py` + `plasticity_u42_shadow`; §12.5 budgeted-payload
addendum `f551d5d`; leak-guarded population train 0–11 + eval 12–41; negative
control reproduced P1 byte-identically; A/B replication perfect) — **result:
net +0 (0/30) ⇒ fails the 0.07–0.08 floor (§12.9), not promoted** · precedent:
doc-graph-v1 gate (`doc-graph-v1` tag, closed), U4.2 oscillation floor, M0150
pre-registration discipline.

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

**Run `plasticity_u42_observe/run1`** (`git_commit f7232d3`, ledger empty,
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

### 11.2 P2 shadow execution record

**Harness:** `eval/plasticity_shadow.py` (populate → freeze → paired eval →
negative control → two from-scratch runs A/B). Populated ledger from train
cases **0–11** (disjoint from eval 12–41), frozen single version under the run
(`ledger_frozen/`, deterministic ts mask — timestamps are audit-only), then
evaluated on U4.2 **12–41**.

**Run `plasticity_u42_shadow`** (`git_commit f551d5d`):

- population: 12 train cases, 14 items, 42 paths, **98 edge events → 59 edge
  keys**, 0 leaks, 6 ground-only items skipped (4:M0016, 6:M0036, 7:M0040,
  8:M0015, 11:M0013, 11:M0012 — present in the archive ground but not in the
  train recall evidence ⇒ not candidates, per §12.3).
- negative control: empty ledger reproduced P1 byte-identically
  (**matches P1 run1 sha1 `3d9df4dc…` True**).
- determinism: negative and shadow eval both deterministic (2 identical
  iterations); replication A/B: frozen ledger sha1 equal, eval iteration equal,
  classification equal — **all True**.
- per-case outcome (budgeted payload, §12.5 addendum): `stayed_correct 11`,
  `stayed_incorrect 19`, `repaired 0`, `regressed 0` ⇒ **net = +0 (0/30 cases
  changed)**.
- transfer probe: **0 of the 30 eval cases share a single edge key with the
  frozen ledger** (59 ledger keys × eval path edges 1,508) — with a disjoint
  train pool, the learned navigation prior has no point of contact with the
  evaluation snapshots, so `ΔE = 0` on every case by construction.

**Finding (per §12.9): net +0 < +3 ⇒ the phase fails the pre-registered floor
and is not promoted; P3/P4 do not run on this ledger version.** The null
result is exactly the leak-guard's behavior — a populated ledger learned from
cases 0–11 cannot change any of the 30 disjoint cases — and the instrument is
verified (controls, determinism and replication all green).

### 11.3 P2b shared-graph execution record

**Harness:** `eval/plasticity_shared.py` (populate from train qids over the ONE
shared graph → freeze → exposure classified before outcomes → paired
pool-32/delivery-8 eval → empty-ledger negative control + unexposed control →
runs A/B from scratch). Committed after §13 froze the protocol.

**Fixture:** `eval/plasticity_fixtures/u42_shared/` (graph sha1
`2cc293cfd4280910aa851bc21b02664bbe0298d7`, seed `20260914`); 104 bench qids
(train 20, eval trained-region 60, eval unexposed 24); `disjoint_train_eval
true`.

**Run `plasticity_u42_shared`** (`git_commit c0bc28b`):

- population: 20 train qids, 160 items, 384 paths, **636 edge events → 47 edge
  keys**, 0 leaks, 0 skipped. Global signal tally: **−0.40 × 573, +0.60 × 63**
  (the +0.30 multi-evidence and +0.10 budget-respected signals never fire:
  every ground item has total = 1 and evidence pools are 32 > 8). Every module
  hub edge is net-negative (e.g. `payments|decided_on|kafka` +6/−26,
  net −20): each delivered-but-not-present sibling item that traverses a shared
  edge teaches −0.40, and the depth-2 closure across `integrates_with` makes
  neighbouring modules' qids traverse the hub edges too, so the single +0.60 of
  the truly-present target is swamped.
- exposure (classified before outcomes): **exposed 60, unexposed 24** — exactly
  the trained-region eval qids vs the dedicated unexposed modules.
- negative control: deterministic, `plastic ≡ base` with an empty ledger
  (matches_base True); **unexposed changed = 0** (24/24 delivered and ordering
  identical).
- shadow determinism: 2 identical iterations; replication A/B: frozen ledger
  sha1 equal, eval iteration equal, exposure equal, classification equal —
  **all True** (net identical: −2/−2).
- per-case outcome (exposed): `stayed_incorrect 48`, `stayed_correct 6`,
  `regressed 4`, `repaired 2` ⇒ **net = −2** (6/60 changed). Total net −2.
- ledger replay of the 4 regressions (qids 6, 23, 40, 55): targets sit at base
  rank 2–5 and carry their own edge's learned utility (mean shrunk utility
  ≈ −0.32…−0.58, negative because of the 573 × −0.40), so energy demotes them
  below the 8-item budget cut; module anchors with zero-edge paths (meanU 0)
  and less-negative shadow siblings are promoted past them.

**Finding (per §13.4): exposed net −2 < +3 ⇒ the phase fails the pre-registered
floor and is not promoted.** The result is not a structurally-impossible zero
(the arm discriminated: 2 repairs, 6/60 changed, unexposed byte-unchanged) —
it is a genuine negative measurement: shared-graph population over this
composite-signal choreography drives learned hub edges net-negative, so energy
demotes rather than promotes the served items and the budget cut becomes more,
not less, likely to drop the required memory. A zero **or** negative exposed
net closes the P3/P4 aspiration per the frozen 2026-09-14 decision.

**P3/P4 status (user decision, 2026-09-14): closed.** The plasticity
experimental line ends at the P2b negative measurement; no further excavation
without a new pre-registration (per §13.4). The instrument advances
(the shared-graph P2b fixed the P1/P2 ordering blindness: the delivery budget
now binds), but the populated-ledger mechanism does not raise recall quality on
any measured substrate at the frozen floor.

## 12. P2 shadow — pre-registration (frozen before any P2 execution)

This section registers, **before any P2 execution**, the population design, the
update regime, the arms, the metric and the promotion criterion (M0150:
parameters fixed a priori, never after seeing results).

### 12.1 Question and arms

> Does a ledger populated from **training cases disjoint from the U4.2
> evaluation set** change U4.2 outcomes through the shadow arm enough to clear
> the 0.07–0.08 floor — without breaking any invariant?

- **Evaluation set** (identical to run1): U4.2 = cases **12–41 (30)**,
  snapshots `eval/graph_out/graphs/longmemeval/case_*` +
  `graph_bench_longmemeval_{u3a,u3b}.jsonl`, pinned by `CHECKSUMS_graph.txt`.
- **Baseline arm**: the P1 observer with an **empty ledger** (shadow ranking,
  read-only). **Plastic arm**: the same observer, same evaluation payload and
  context, with the **frozen populated ledger** loaded read-only. Only the
  energy ranking differs — `E = D − wᵤ·U`, `H = R = 0` (§6) — every edge of
  the pipeline (seeds, paths, evidence, `guard_evidence`, `question_gate`,
  budget) is byte-identical. **No LLM step** anywhere in P2.

### 12.2 Leak guard and population source (disjoint by construction)

- The ledger is populated **only** from the archived **train cases 0–11**
  (snapshots `graph case_00..case_11`, benches `graph_bench_longmemeval.jsonl`,
  signal ground `fact_presence_longmemeval.jsonl`) — **disjoint** from the 30
  evaluation cases (12–41). A case cannot be both train and eval; the harness
  iterates only the 0–11 artifacts, never the u3a/u3b benches or cases 12+, and
  records the disjointness assertion in the run manifest.
- Signal ground for a memory id is the frozen `graph_off` arm of
  `fact_presence_longmemeval.jsonl` (`delivered`, `item_facts.present`,
  `strong.present`) + `graph_bench_longmemeval.jsonl` required ids — objective
  properties of the *search*, never `answer_correct` (M0155).
- No edge, path or signal from any evaluation case exists in the ledger
  (asserted at load, recorded in the manifest).

### 12.3 Initial state, update count and order, signals, limits and shrinkage

- **Initial state**: ledger empty (`events.jsonl` empty, `utility.jsonl` empty,
  `sha1 "empty"`), `policy_version "p0"`.
- **Update rule and constants** (frozen, §7): `u' = clip((1−λ)·u + η·s, −1, 1)`
  with `λ=0.01`, `η=0.10`, bounds ±1, `k=5.0` shrinkage (`u_eff = u·n/(n+k)`),
  `hop_cost=0.15`, `wᵤ=0.5`.
- **Signal** (frozen composite §7.1, clipped to `[−1,1]`, attributed to every
  edge in its path, one `apply_update` per (case, item, path, edge)):
  `fact_presence +0.60`, `wasted_context −0.40`, `multi_evidence_complete
  +0.30`, `budget_respected +0.10`; `cross_document_leak −0.60` ⇒ record with
  `evidenced=false` (logged, never reinforced).
- **Update order** (fixed, deterministic): train cases `00→11` in filename
  order; per case, delivered memory items in `graph_off` items order; per item,
  candidate paths from frozen recall in base-score order (as in P1), retained
  to `max_paths_per_evidence=3`; per retained path, its edges in path order.
- **Number of updates** = the count the rule produces over the frozen inputs
  (not hand-picked); it is recorded in the ledger manifest and locked. Two
  re-populations from separate empty stores must yield a byte-identical
  `events.jsonl` (same count + sha1) — clause 12.8.
- **Limits**: no new caps beyond the frozen search limits (depth 2, `top_k` 8,
  `max_paths` 400, `max_paths_per_evidence` 3, budget char cap from §6.4);
  ledger size is bounded by the training pool and reported in the manifest.

### 12.4 Single frozen ledger version before evaluation

- Population writes a fresh versioned ledger; after population it is
  **frozen**: copied read-only to `eval/results/<run>/ledger_frozen/` with the
  sha1 of `events.jsonl` and `utility.jsonl` recorded in `run_manifest.json`, and
  the evaluation harness loads **only that copy** under the P1 mutation guard
  (any write outside `--out` aborts, exit 2).
- Exactly **one** frozen ledger version is evaluated. A second version = an
  unreported policy change; it invalidates the run.

### 12.5 Paired primary metric and exact tie/improve/regress rule

Per evaluation case (12–41) the mechanical outcome of each arm is:
**`correct`** ⇔ all required target ids were delivered as evidence in the
retained paths (`targets_missing == []`); **`incorrect`** otherwise (computed
exactly like run1's per-case table; no LLM).

Per-case pairing (baseline empty-ledger outcome, plastic outcome):

| Class | Rule | Net |
|---|---|---|
| **repaired** | baseline incorrect → plastic correct | `+1` |
| **regressed** | baseline correct → plastic incorrect | `−1` |
| **stayed-correct** | both correct | `0` |
| **stayed-incorrect** | both incorrect | `0` |

Anything not strictly repaired or regressed is a **tie**. Primary metric:
**`net = repaired − regressed`** over the 30 cases. Secondary (audit-only,
never gating): wasted-context delta, delivered-evidence stability (per-case
Jaccard of ids), ordering stability.

**Adendo P2 (pré-execução, aprovado pelo usuário).** Outcome por caso é medido
sobre o **payload com orçamento** (o contrato de entrega real), não sobre o
conjunto completo de itens recuperados: cada braço caminha seus itens ordenados
(base = score desc; plástico = energia asc, empatados por score desc) e vai
incluindo no payload até `graph_top_k` **8** itens ou **4000 chars** de label
(`evidence_payload_budget`), o que vier primeiro; `delivered_ids` = os
memory-ids do payload resultante. `correct` ⇔ `required_ids ⊆ delivered_ids`;
`incorrect` caso contrário. Base e plástico usam exatamente o mesmo gatilho de
orçamento — só a ordem muda — então "payloads e contexto idênticos" (§12.1)
fica garantido e a métrica pareada passa a ser sensível à reordenação (sem esse
adendo o conjunto entregue seria idêntico nos dois braços e `net` seria
invariavelmente 0). Constantes do orçamento: `graph_top_k=8`,
`evidence_payload_budget=4000` (config padrão, imutáveis).

### 12.6 Per-case audit and traceability

The run table classifies all 30 cases into the four buckets and prints per case:
base vs plastic top-3 paths (nodes → relations → edges), energy decomposition
(`D`, `wᵤ·U`, `H = R = 0`), target coverage, delivered/missing ids, budget.
Traceability chain (M0124): `case → query → paths → EdgeKeys → events.jsonl →
update records` (memory ids audit-only). Repaired and regressed cases carry an
additional path-level diff block for manual reading.

### 12.7 Negative control (must reproduce P1)

An empty-ledger evaluation over the same 30 cases, part of the P2 run itself,
must reproduce P1 run1 exactly: **changed = 0/30** with the two observer
iterations byte-identical (re-run sha1 must equal run1's `3d9df4dc…`). Any
divergence = snapshot or harness drift → abort before reading the plastic arm.

### 12.8 Variance separation and independent executions

- P2 population and evaluation are **fully mechanical — no LLM step** — so
  run-to-run variance is 0 by construction; yet the protocol executes the whole
  pipeline **twice from scratch** (two empty ledger stores, two run dirs), and
  both executions must produce an identical frozen ledger (sha1) and an
  identical 30-case classification. This satisfies the "≥2 independent runs"
  rule deterministically (policy effect separated from variance).
- If any later execution adds an LLM step, it **re-pre-registers** with ≥2
  independent runs at temperature 0 and a frozen judge; not covered here.

### 12.9 Promotion criterion (crossing the pre-registered floor)

Pair per case = 1/30 ≈ 0.0333. A net of `+2` = 0.0667 **lies below** the
0.07–0.08 floor; a net of `+3` = 0.10 **clears** it. Therefore:

```
promote P2  ⇔  (net = repaired − regressed) ≥ +3
               AND all invariants hold
               AND negative control reproduced 0/30
               AND every regressed case audited + explained by ledger replay
```

Promotion proceeds like doc-graph-v1: joint reading of the net metric **and**
reversibility (utility rebuild == frozen utility), then a tag. Net `< +3`
(+2 included) rejects the phase at the floor; secondary metrics are reported
but never gate. Empty-ledger "change" is never an effect (M0195).

## 13. P2b shared-graph — pre-registration (frozen before any P2b execution)

Frozen on 2026-09-14 per session decisions — this section is the binding
record; the code implements no behavior absent from it.

### 13.1 Substrate and instruments

- **One persistent shared graph** (`GraphStore`) generated deterministically by
  `eval/gen_graph_shared.py` (seed `20260914`), committed under
  `eval/plasticity_fixtures/u42_shared/` (`graph/`, `bench.jsonl`,
  `ground.jsonl`, `manifest.json` with `graph.sha1`).
- Regions: **trained** modules `{payments, auth, search, gateway, ledger}` with
  techs `{kafka, rabbitmq, postgres, mysql, redis, cassandra, clickhouse,
  flink}`; **unexposed** modules `{inventory, shipping, analytics}` with techs
  `{mongodb, dynamodb, elasticsearch, couchbase, oracle, solr}` (dedicated
  people `{dave, erin, frank}` and modules; no trained label used there).
- Bench: 104 mechanical questions (train 20, eval trained-region 60, eval
  unexposed 24). Train/eval questions are **textually disjoint**;
  `disjoint_train_eval: true` is asserted. No eval answer or eval label appears
  in any update; `required_ids` of eval rows are **shadow memory ids** that are
  never train targets (no eval-label leak into a learned signal).
- **Shadow targets**: for each trained-region fact, a second memory on the
  **same EdgeKey** `(module, decided_on, tech)` with lower deterministic
  confidence (0.22–0.38). Shadows are the repair-capable eval targets — same
  navigation, different question. This fixes the P2 lesson that disjoint
  different-fact queries inherit negative sibling-edge utility (repairs
  impossible by construction).

### 13.2 Instrument decisions (frozen, 2026-09-14)

- Search candidate pool: `recall_top_k = 32` (`GraphRecall(depth=2, top_k=32,
  max_paths=400)`). **Delivery budget unchanged §12.5**: top 8 items / 4000
  chars from the pool. Rationale: with pool = delivery = 8 the delivered set is
  always the whole pool and ordering never matters → net is structurally 0 on
  any substrate (P1/P2 blindness: `base_chars ≤ 795`, budget never bound).
- Evaluation pipelines exactly mirror `plasticity_observe.one_case` and
  `plasticity_shadow` (`_path_utility`, `_item_energy`, `shrink`,
  `energy(query_distance=1−score, weight_utility=0.5)`), but run one instance
  against the **single shared graph** instead of per-case snapshots.
- Signals and budget functions identical to §12.3/§12.4.

### 13.3 Protocol (order is part of the commitment)

1. **Populate**: replay deterministic recall per **train** qid over the shared
   graph; per delivered item (from the mechanical ground) record the frozen
   composite signal on every edge of its retained ≤3 candidate paths.
2. **Freeze**: copy the ledger read-only with a deterministic ts mask
   (audit-only; `created_at`/`ts` never enter EdgeKey, score or rank), record
   events/utility sha1 in the run manifest.
3. **Classify exposure** — mechanically, **before any outcome is computed**:
   an eval qid is **exposed** ⇔ its search-space EdgeKey set intersects the
   frozen ledger keys (≥1 learned edge); **unexposed** ⇔ empty. Written to
   `exposure.jsonl` before evaluation; classification is auditable without any
   outcome knowledge.
4. **Negative control**: same evaluator with an empty ledger must reproduce the
   base ranking byte-identically (`plastic ≡ base`, deterministic iterations);
   every **unexposed** case must remain unchanged (`net == 0` and evidence
   order equal) — any change aborts before the plastic arm is read.
5. **Paired evaluation**: base arm = score ranking; plastic arm = energy ranking
   with the frozen ledger; per-case outcome from the §12.5 budgeted payload
   (`correct ⇔ required ⊆ delivered`; `delivered` = top 8 items / 4000 chars of
   the 32-candidate pool).
6. **Replicate**: runA and runB from scratch must produce byte-identical frozen
   ledger sha1, identical exposure classification, identical eval iterations
   and identical per-case classification.

### 13.4 Metrics and promotion (frozen)

```
promote P2b  ⇔  exposed net = (repaired − regressed) ≥ +3  (floor from §12.9)
               AND unexposed changed = 0
               AND negative control deterministic + matches base
               AND replication equal (runA == runB byte-for-byte)
               AND every regressed case audited + explained by ledger replay
```

- **Primary metric**: net over **exposed** cases. **Total** net also reported.
- **Unexposed is a frozen negative control** — its delivery order must not
  change; it is not tuned or adapted after execution.
- Net `< +3` (including `≤ 0`) rejects the phase at the floor. A zero or
  negative result over the exposed cases closes the P3/P4 aspiration per the
  2026-09-14 decision (no further excavation without a new pre-registration).