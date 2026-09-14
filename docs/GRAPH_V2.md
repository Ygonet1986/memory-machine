# Graph Memory Machine v2 — admission control results

**Scope.** Post-v1 measurement, following `docs/GRAPH_EVAL.md`. The goal is not
to retrieve more: it is to decide what deserves context. `augment` (v1) stays
byte-compatible; `augment_guarded` is a new mode. No global default changed
(`graph_enabled=false`), and `PAPER.md` / `RESULTS.md` / `eval/archive` were not
touched.

## V2-0 — replay calibration (offline, no LLM)

`eval/graph_guard_calib.py` replayed the V2-1 traversal against the 12
preserved LME graphs for `H` (hub degree cap) × `T` (score floor) × `N`
(graph-only item cap). Reference: the unguarded v1 graph recovered **3
graph-only gold** memories and admitted **63 non-gold** items (agent gold
allocation ratio 1.00; graph share of the payload 0.64).

| recipe | gold kept | non-gold admitted | agent gold alloc ratio | graph share | case-1 noise |
|---|---|---|---|---|---|
| v1 `augment` (unguarded) | 3/3 | 63 | 1.00 | 0.64 | 7 items |
| **R5 = literal rule**: no hub cap, T=0.80, N=5 | **3/3** | **44** | 1.19 | 0.57 | 5 items |
| **R3 = precision**: hub ≤ 20, T=0.80, N=3 | 2/3 (loses case-6 M0036) | **11** | **1.81** | **0.26** | **0 items** |

Per-case displacement (the `would_displace_agent_gold` column): in case 1 the
agent's gold item received **530 chars** unguarded, **711** under R5 and
**1,344** under R3; in case 4 it went 452 → 662 (R5) → 951 (R3). The rule
"preserve 100% of recovered gold, then minimize non-gold, then least
aggressive" selects **R5**; R3 is the precision alternative and loses exactly
one gold (case 6, which never changed an answer) — recorded as an explicit
trade-off, not an average.

Implementation: `graph_hub_degree`, `graph_augment_min_score`,
`graph_augment_max_items`, `graph_augment_weight`; guarded defaults = R5.

## Judged replay (corrected: shared agent annotations)

**Correction.** The first five-arm replay ran the LLM agents separately in each
arm, so agent variance was confounded with graph admission. A case-5 flip
reported earlier as "single-memory graph interference" was traced to the
agents of that arm finding an extra memory (`graph_ids` under `precise` were
exactly the agent gold; the added M0003 came from the arm's own agent recall).
The confounded snapshot is preserved as
`eval/graph_out/graph_bench_longmemeval_v2confounded.jsonl`; its case-5 reading
is retracted. `eval/graph_replay_shared.py` re-runs the judged replay with the
agents executed **once per case** and frozen; the variants differ only by the
deterministically computed graph admission, and the harness asserts that
building the union/payload makes no LLM call.

Corrected LME-12 results (shared agents):

| arm | strict | paired vs off |
|---|---|---|
| graph_off | 0.750 | — |
| graph_augment (v1) | 0.667 | 1 better / **2 worse** |
| graph_augment_guarded (R5) | 0.750 | 1 better / 1 worse |
| graph_augment_precise (R3) | **0.833** | **1 better / 0 worse** |

Per-case mechanics:

- **Case 4 (temporal)**: off incorrect → all three augment variants correct,
  graph-only gold M0036 admitted in all of them (the causal gain survives every
  guard).
- **Case 5 (single-session-user)**: off correct → v1 augment incorrect with 7
  graph additions; R5 and R3 both answer correctly with **0** graph-only
  additions (hub cap 20 zeroes this case's noise).
- **Case 0 (multi-session)**: off correct → v1 augment correct, **R5 guarded
  incorrect** (2 additions still admitted), **R3 correct** (0 additions).
- **Case 3**: off correct → v1 augment *partial* (6 additions); R5 and R3
  correct.
- **Case 9 (single-session-user)**: every variant admits the graph-only gold
  M0032 and every variant still answers incorrectly — the utilization gap is
  independent of admission control.

With the confound removed, the picture is causal: the v1 augment **loses cases
to dilution**, the R5 guard only partially protects (case 0), and the R3
recipe (hub ≤ 20, score ≥ 0.80, ≤ 3 items) preserves the causal win while
netting **+1 over the un-augmented system**. The `augment_guarded` defaults are
therefore promoted to the R3 recipe; `graph_hub_degree` remains the generic
traversal override and `augment` (v1) is untouched.

## Resolver cost

Case 0, same preserved tape, real extraction with the v2 resolver (in-memory
vector cache + `max_candidates=10`):

| | v1 | v2 cache | v2 cache + batch (P4) |
|---|---|---|---|
| embedding calls | 790 | 755 | **49 (−94%)** |
| embedding texts | 27,418 | 6,347 (−77%) | **1,388 (−95%)** |
| build time | 464 s | 383 s (−18%) | 405 s (noise) |

Batching resolutions (one embedding request per memory instead of per entity)
removes essentially all embedding recomputation with identical resolutions
(tested). The build time does **not** follow: with embeddings nearly free, the
remaining ~400 s are dominated by the extraction LLM calls themselves, not the
resolver. The earlier "embeddings dominate" attribution was wrong — the honest
decomposition is: batched extraction ≈ 300-380 s, resolver ≤ 20 s after P4.

## Decision

- `augment` untouched; `augment_guarded` defaults = R3 recipe (hub 20,
  score 0.80, ≤ 3 items), validated by the shared-agent replay above; 343
  tests. `graph_enabled` stays off.
- Admission control is now causally demonstrated: it removes two dilution
  regressions and preserves the recovered gold, netting +1 over `off`.
- The remaining limits are different in kind: **utilization** (case 9 admits
  the gold and still answers wrong) is an answerer-side question, not an
  admission one. The **question gate** calibration (`eval/graph_qgate_calib.py`,
  P2) shows every deterministic rule keeps 2/2 graph-only gold on this slice,
  with lexical coverage ≥ 0.30 blocking 45/46 non-gold — but this slice is
  11/12 lexically top-1, so the gate is implemented as an **opt-in flag**
  pending the enriched miss/top-5 slice (P5). The guard stays structural by
  default: it must not become another BM25.
- Next lever, in order: (1) enriched miss/top-5 slice to test the question
  gate outside the easy lexical regime; (2) resolver batching (already
  measured: 790 → 49 embed calls, 27,418 → 1,388 texts, same resolutions);
  (3) utilization experiments at the answerer boundary, separately.

## P5 — enriched lexical-miss slice (out-of-sample)

12 multi-session questions deliberately selected because their gold sessions
rank **miss/top-5** under BM25 (indices 71, 73, 78, 86, 88, 89, 110, 119, 126,
129, 131, 162 of the full 500). Graphs built once per case (batched extraction,
vector-cache resolver) and judged with the shared-agent design.

| arm | strict | paired vs off | graph-only gold admitted |
|---|---|---|---|
| graph_off | 0.583 | — | — |
| graph_augment (v1) | 0.583 | 0 / 0 | **9** |
| graph_augment_guarded (R5) | 0.500 | 0 / 1 | 7 |
| graph_augment_precise (R3) | 0.500 | 0 / 1 | 6 |
| graph_augment_gated (R3 + question gate) | **0.667** | 1 / 0 | **1** |

The numbers tell three different stories, and only one of them favors more
gating:

1. **On hard lexical cases the graph finds much more gold** — 9 graph-only gold
   across 12 cases versus 2 on the easy LME-12 slice (cases 78: 2, 89: 4, 126:
   3). This is the strongest retrieval-side evidence yet that structural search
   earns its keep exactly where lexical retrieval struggles.
2. **None of it converts into answers.** Cases 78 and 89 recovered gold and
   every variant still answered incorrectly (error classification: the
   answerer does not use the admitted evidence). The bottleneck on this slice
   is **utilization**, not admission or retrieval.
3. **Every gate trades gold away, and the lexical gate is the most expensive.**
   Admitted graph-only gold falls 9 → 7 (R5) → 6 (R3) → **1** (question gate).
   The gate's apparent +1 (case 131) has **zero graph additions in every
   variant** — its payload is agent-only, so the flip is judge variance, not a
   gate win.

**Decision after P5:** the question gate stays **opt-in, off by default** — on
out-of-sample lexical-miss questions it blocks 8 of 9 recovered gold while its
single "gain" is not evidence-driven. The R3 structural defaults stay (they
were clearly better on the easy slice and neutral here). The next frontier is
explicitly the **utilization boundary** (does the answerer see and use admitted
gold?), not more admission machinery.

## Reproduce

```bash
PYTHONPATH=src:.:eval python3 eval/graph_guard_calib.py --reuse-root <LME12-root>
PYTHONPATH=src:.:eval python3 eval/graph_bench.py --dataset longmemeval --limit 12 --tag \
    --reuse-root <LME12-root> \
    --arms graph_off,graph_augment,graph_augment_guarded,graph_augment_precise,graph_only
python3 eval/graph_report.py longmemeval
```

Snapshots: `eval/graph_out/` (`graph_bench_longmemeval.jsonl`, v1 preserved as
`graph_bench_longmemeval_v1.jsonl`, `guard_calib*.csv`, checksums).
