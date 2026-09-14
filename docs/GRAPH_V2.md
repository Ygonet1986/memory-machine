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

## Judged replay (same tapes and graphs, zero re-extraction)

Five arms on the LME-12 cases; `graph_only` is retrieval-only.

| arm | strict | evidence complete | graph-only gold found |
|---|---|---|---|
| graph_off | 0.75 | 9/12 | — |
| graph_augment (v1) | 0.75 | 11/12 | 2 |
| graph_augment_guarded (R5) | 0.75 | 11/12 | 2 |
| graph_augment_precise (R3) | 0.75 | 11/12 | 2 |

Aggregate tie, but the case level separates three mechanisms:

1. **The causal gain survives every guard.** Case 4 (temporal): off incorrect
   → v1, R5 and R3 **all correct**, with the recovered M0036 admitted as
   `graph_only_gold` in all three. The v2 gates do not kill the benefit they
   were meant to protect.
2. **Dilution regressions are stochastic, and the guards shrink the surface.**
   In the first measurement the flip was case 1; in this replay it is case 5.
   Case 5 went correct → incorrect in all three augment arms, with 8 (v1), 5
   (R5) and **2** (R3) payload items. With only **one** added memory (M0003, an
   unrelated anniversary session reached through a hub) the answerer switched
   from answering "12" to *refusing* ("I don't have an answer… explicitly
   rejects 12"). This is not budget dilution: it is behavioural interference
   from a single structurally-related, question-irrelevant neighbour.
3. **Found is not used.** Case 9: all augment arms admitted the gold M0032 as
   `graph_only_gold`, and all still answered incorrectly. Retrieval succeeded;
   the answerer did not use it (the AUR-style utilization gap).

Run-to-run variance matters at n=12: `graph_off` itself moved 0.667 → 0.75
between the two runs, and the flip cases differ. Aggregate accuracy is not the
right instrument at this size; the retrieval-side facts (union complete 11/12
vs agents 9/12; graph-only gold in cases 4 and 9 in both runs) and the
per-case mechanisms are.

## Resolver cost

Case 0, same preserved tape, real extraction with the v2 resolver (in-memory
vector cache + `max_candidates=10`):

| | v1 | v2 |
|---|---|---|
| embedding calls | 790 | 755 |
| embedding texts | 27,418 | **6,347 (−77%)** |
| build time | 464 s | **383 s (−18%)** |

The cache removes recomputation (semantics unchanged: same vectors, same
resolutions — covered by tests), but **per-request overhead dominates**, not
text volume. The next lever is batching the resolutions themselves (one embed
request per memory instead of per new entity).

## Decision

- `augment` untouched; `augment_guarded` (R5 defaults) and the precise recipe
  (flags) are implemented and tested (342 tests). `graph_enabled` stays off.
- Admission control demonstrably protects the payload (R3: −83% non-gold, +81%
  agent-gold allocation) and preserves the one causal win. It does **not** fix
  single-distractor interference (case 5) or utilization failures (case 9).
- Next lever, in order: (1) **question-conditioned gate** over admitted
  graph-only evidence (require question↔memory overlap, e.g. the path
  endpoints or the memory text must match question terms), since confidence
  and degree cannot distinguish "relevant to the graph" from "relevant to the
  question"; (2) batch resolver resolutions; (3) only then consider a larger
  enriched slice (lexical miss/top-5, seed-less) to re-test the structural
  hypothesis with the guard active.

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
