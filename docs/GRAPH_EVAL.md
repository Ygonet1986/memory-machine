# Graph recall measurement — M-phase results

**Scope.** Measure the frozen Graph Memory Machine v1 (`graph-v1` → `e7319a2`)
as a system: does the structural arm find evidence the traditional recall
misses, does that evidence improve answers, and at what cost? This document is
independent from the v1.0 paper: no frozen file (`eval/out`, `eval/archive`,
`docs/RESULTS.md`, `docs/PAPER.md`) was touched, no default changed.

## Method

- Harness `eval/graph_bench.py` (snapshots in `eval/graph_out/`, gitignored,
  checksummed): the base machine is ingested once per case with the graph
  **disabled**, the projection is built once (batched extraction + resolver),
  and each arm receives a **byte-identical tape + graph copy** (sha256 checked).
- Arms: `graph_off` and `graph_augment` answered and judged (same answerer and
  judge as the frozen harness, deepseek-v4-flash); `graph_only` is
  **retrieval-only**.
- Config used only by the harness: `graph_extract_types` includes `memory`
  (sessions are `type=memory`), resolver embeddings via local Ollama
  (`nomic-embed-text`), payload budget 4000, full ingestion, real dates.
- Aggregation `eval/graph_report.py` and figures `eval/graph_figures.py`
  consume only the snapshots.

## Synthetic fixture (32 cases) — ceiling control

| arm | strict | lenient | AUR | mean annotations |
|---|---|---|---|---|
| graph_off | 0.94 | 0.97 | 0.97 | 15.3 |
| graph_augment | 0.94 | 1.00 | 0.97 | 15.5 |
| graph_only (retrieval) | — | — | — | 2.9 |

- Evidence complete in **31/32** cases for both judged arms: no headroom.
- `graph_only_gold = 0` despite 18 graph-only memories: extra evidence, none
  needed. The fixture cannot demonstrate (or refute) a graph gain.

## LongMemEval-12 — the informative slice

Baseline headroom exists (agent evidence recall 0.79; complete in 9/12).

| arm | strict | lenient | AUR | mean annotations |
|---|---|---|---|---|
| graph_off | 0.67 | 0.75 | 0.89 | 2.25 |
| graph_augment | 0.75 | 0.75 | 0.73 | 7.75 |
| graph_only (retrieval) | — | — | — | 6.92 |

**The four primary numbers**

- `graph_only_gold = 3` (of 66 graph-only memories; graph precision 0.23).
- Paired delta augment − off: **2 better / 1 worse / 9 equal**.
- By stratum: the +2 sit in multi-session cases (1 temporal, 1
  knowledge-update); the −1 is a single-session-assistant case.
- Seeds were resolved in **12/12** cases; the lexical slice is 11× top-1 and
  1× top-5, **0× miss** — the "lexically disjoint" hypothesis cannot be tested
  in this slice.

**Case-level mechanisms (the honest reading)**

- **Real structural win — case 4** (temporal-reasoning, 2 sessions): the agent
  arm had M0016 only and answered wrong; the graph recovered the missing
  M0036 (`graph_only_gold`) through a multi-hop path and the answer became
  correct. Union recall 0.96 vs 0.79 in the aggregate comes essentially from
  this recovery.
- **Noise, not a graph win — case 7** (knowledge-update): the verdict improved
  partial → correct with the **identical payload** (`M0013, M0040`); the
  augment-only memory set is empty. Single-case judge variance.
- **Dilution regression — case 1** (single-session-assistant): off answered
  correctly from one memory; augment added 7 non-gold memories into the same
  4000-char budget and the answer became incorrect. The graph contributed no
  gold evidence; the expansion alone hurt. This is the protective-budget
  thesis ("more remembered context is not necessarily better memory")
  reappearing on the graph side.

**Paths.** 16 gold graph evidence items: 12 at semantic depth 1, 4 at depth 2;
**44% used an event hop** (`agent`/`object` through a `type=event` node) —
the event-as-one-semantic-hop rule is load-bearing in practice. Mean best
score 0.90.

**Review.** 0 hypotheses across the 12 cases: aliases resolved by exact
match/embedding, and the 0.60–0.90 band never triggered at this scale. The
review workflow was exercised in tests, not by this corpus.

**Cost.** Extraction: 77 batched LLM calls but **4,700 s (~78 min)** total —
dominated by the resolver's embedding shortlist (**8,284 embedding calls**,
27k texts on the first case alone), not by the LLM. Graph query is cheap:
2.2 ms/question. Review decisions: 0.

## Limitations

- n = 12 (LME slice), single judge model, one case-weight per stratum.
- The slice has no lexical-miss and no seed-less cases, so the pre-registered
  "structurally connected, lexically distant" hypothesis is **untested**, not
  refuted.
- Extraction truncates memories at 6,000 chars; LME sessions are ~10.4k.
- `graph_only` measures selection capacity, not answer quality.
- Case 7 shows that ±1 graded verdicts on n=12 are within model variance.

## Decision memo (M4)

1. **No default changes.** `graph_enabled` stays `false`; `augment` is opt-in.
2. **Signal that survives scrutiny:** the structural arm can recover missing
   gold evidence (union recall 0.96 vs 0.79; one clean answer fix via an
   event-hop path in a temporal multi-session question). This is a mechanism,
   not yet a rate.
3. **Signal that warns:** low graph precision (0.23) plus a shared budget
   turns extra non-gold memories into dilution (case 1). Any v2 should make
   augmentation *budget-aware* (e.g., cap graph-only additions, rank them
   below agent evidence, or add them only when agent recall is incomplete).
4. **Cost honesty:** the expensive stage is identity resolution (embeddings),
   not extraction or query. A resolver shortlist cap / embedding cache is the
   first optimization candidate.
5. **Next measurement (if pursued):** a slice enriched with lexical
   miss/top-5 and seed-less cases (e.g., filtered LME-50), plus a
   no-resolver-embeddings variant and a budget-aware augment arm. Those three
   would test the structural hypothesis instead of the current ceiling.

## V2 follow-up

Admission control and resolver-cost results: `docs/GRAPH_V2.md`.

## Reproduce

```bash
PYTHONPATH=src:.:eval python3 eval/graph_bench.py --dataset synthetic --limit 32 --api-key ...
PYTHONPATH=src:.:eval python3 eval/graph_bench.py --dataset longmemeval --limit 12 --tag --api-key ...
python3 eval/graph_report.py synthetic longmemeval
.venv/bin/python eval/graph_figures.py
```

Raw snapshots and per-case audit graphs: `eval/graph_out/`
(`graph_bench_*.jsonl`, `graphs/`, `CHECKSUMS_graph.txt`). Each metric walks
back `case → path → R#### → memory_id → tape text`.
