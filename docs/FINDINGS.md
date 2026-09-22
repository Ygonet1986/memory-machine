# Experimental findings (README annex)

Measurement-laden notes moved out of the README so the front page stays a
short promise + quickstart + links. The paper and the generated tables are
authoritative: `docs/PAPER.md`, `docs/RESULTS.md`, `docs/RELATED_WORK.md`.

## Program status (experimental program v1)

The experimental program tested one layer at a time. Confirmed: perspective
agents over views (H1), factual-content delivery (H2), budgeted evidence with
relative parity at -70% context (H3). Refuted: the memory-aware prompt (H4),
multi-session aggregation as the bottleneck (H5), and the temporal-computation
prompt once the timestamps were correct (H6a). Confirmed: real timestamps plus
payload delivery fix evidence-complete temporal reasoning (H5').
Two findings stand out: the external ingestion cap was losing ~80% of each
session at write time, and an oracle with unlimited context scores *below* the
4000-char payload — the budget is a protective filter, not just a cost play.
The paper-phase flat dense baseline (one vector per session, top-5) confirms
the boundary story from the other side: 0.24 evidence and 0.16 strict while
delivering ~11k context characters — context size is not evidence. See
`docs/PAPER.md` (draft), `docs/RESULTS.md` (generated tables) and
`docs/RELATED_WORK.md`.

## Measured notes

- **Memory router** (opt-in, off by default) — selects the top-K partitions
  (via group digests) instead of consulting every agent, cutting fan-out from
  O(N) to O(K). Modes: `llm` (one routing call, semantic), `embedding` (cosine
  over digests; needs an embeddings provider like Ollama), or `lexical` (BM25;
  cheapest but unsafe for lexically-distant memories). It is opt-in because
  measurements show it trades recall for cost: on external benchmarks the full
  sweep scored 0.83-0.93 evidence recall vs 0.63-0.70 for the router.
- **Evaluation** (`eval/`) — `agent_bench.py` (synthetic, lexically distant),
  `external_bench.py` (LongMemEval / LoCoMo, with BM25, dense vector, full
  agents and routed agents; `--arms` and `--embedding-models` select arms and
  dense models) and `view_router_bench.py` (controlled topology: full vs
  similarity vs view-BM25 vs view-LLM vs view-oracle vs cascades, with view
  recall/precision, evidence and agent recall, reduction, expansion, fallback
  reasons, calls/tokens/latency). Measured: on LongMemEval dense retrieval
  beats BM25 and ties the agents (no agentic advantage); on LoCoMo the agents
  lead (0.90 vs BM25 0.78 and dense 0.56). The agentic advantage is
  benchmark-dependent: it emerges where relevance is contextual, not directly
  similar.
- **Provenance** — rollups record `derived_from`; `rehydrate <id>` recovers the
  original (archived) memories so compression is never a dead end.
- **Views (projections)** — a memory belongs to one canonical tape but can
  appear in several views (`time/…`, `type/…`, `source/…`, `topic/…`,
  `subject/…`) without physical duplication; the view index is a rebuildable
  projection. List with `views`, filter recall with `--views`.
- **Ingestion ablation** (`eval/e2e_bench.py --gfr --ingest-why N`) — the
  external harness truncated sessions to 2k chars at write time; raising the
  cap lifts Gold Fact Retention from 0.42 to 0.83 and strict accuracy from 0.33
  to 0.50 (evidence recall constant at 0.75 — the loss was upstream of
  retrieval).
- **H5' (confirmed)** — with the payload delivered, restoring the real session
  timestamps and the question date (`--ingest-dates`) lifts temporal-reasoning
  0.29 -> 0.64 and temporal | evidence complete 0.44 -> 1.00 (9/9); overall
  strict 0.56 -> 0.64 and AUR 0.76 -> 0.89. An oracle with all expected
  sessions and no context cap collapses on multi-session, showing that more
  evidence can hurt.
- **H6a (refuted on temporal)** — a gated temporal-computation procedure added
  nothing on temporal questions once the timestamps were correct (0.64 -> 0.64);
  the small overall gain (0.64 -> 0.70) comes from non-temporal small-n cases.
- **Harness bug (documented)** — the first H5'/H6a "dates" runs were missing
  from the payload-delivery branch, so they measured whiteboard-only answers;
  after the fix the results reversed. Old snapshots kept as `*_BUGGY.jsonl`.
- **H4 (refuted)** — a memory-aware answer prompt (explicitly telling the
  answerer the context is recalled history) did not help: payload 4000 dropped
  0.56 -> 0.50 strict and the oracle stayed at 0.52. The dominant remaining
  failure is evidence insufficiency (16-22 of ~25 errors), not temporal
  misreading (1-5).
- **Compression curve (H3)** — on LongMemEval 50q with full ingestion, payload
  6000 matches the full context (0.60 vs 0.58 strict) with a 57% context
  reduction, and payload 4000 stays within noise at 70% reduction; 2500 loses
  accuracy, so the compression knee is around 4000.
- **Evidence payload** (`evidence_payload: budgeted`) — the agents say *why* a
  memory matters; the payload delivers *what it says* under a character budget
  (relevance-ordered, `why` truncated first, rollups rehydrated from their
  archived sources). It is recall-local (never persisted in the whiteboard).
  Measured: 0.97 strict vs 0.88 for full injection on the controlled fixture.
- **End-to-end answer accuracy** (`eval/e2e_bench.py`) — measures whether the
  memory actually improves the final answer, not just retrieval: view agents +
  full memory content score 0.88 strict (AUR 0.90) vs 0.72 (AUR 0.74) with
  annotation notes only, at the same cost — the bottleneck is context loss, not
  retrieval.
- **Attention state** (opt-in) — `Whiteboard.attention` is a recency-weighted
  prior over views (decay + saturating boost) that keeps the conversation's
  active regions across turns: `prior` blends it into lexical routing,
  `context` shows it to the LLM plan, `state` reuses it for anaphoric
  follow-ups. Measured: anaphora resolved at 5.7 calls vs 10.7 (full sweep),
  and the old topic decays 0.94 -> 0.56 after a topic shift.
- **CLI/app modes** — `recall --agent-mode view --whiteboard-mode dimension
  --dimension-mode auto` switches a single recall to perspective agents and
  per-dimension boards; the app's settings expose the same as a "Memory mode"
  selector. External sessions can be auto-tagged into views with
  `eval/tag_sessions.py` + `external_bench.py --tag` (Fase 2).
- **View router** (opt-in) — uses the write-time organization as a structural
  retrieval prior: `router_mode: views` selects views (BM25 over view digests,
  or an LLM call with the whiteboard) and consults only their records;
  `router_mode: cascade` adds a recall-safe fallback (expand co-occurring
  views → similarity router → full sweep) and records why it fell back. An
  explicit `recall --views` overrides routing. With `view_dimension_mode:
  auto` the router plans dimensions first (semantic/temporal/structural) and
  intersects their record sets with progressive relaxation; `coverage_mode`
  adds a recall-local coverage signal (agents/structural/both/judge) that the
  cascade uses to expand. Controlled benchmarks (32 tasks): dimension-aware
  view-BM25 raises view recall 0.67 -> 0.81 and reduction 0.63 -> 0.70 at 9.6
  calls; the ground-truth-views oracle reaches 1.00 at 7.7 calls / 0.84
  reduction, so the router and the coverage signal — not the topology — are the
  bottleneck (manual 40.4/40.5).
