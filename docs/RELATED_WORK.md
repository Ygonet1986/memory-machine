# Related work and novelty positioning (v1.0)

Prepared for the Memory Machine v1.0 paper. Citations verified against the
arXiv API; IDs and dates are included so the final bibliography can resolve
them. The last section states what remains novel after the closest works.

## 1. Long-term agent memory

- **MemGPT: Towards LLMs as Operating Systems** (2310.08560, 2023-10) — paged
  memory: the LLM manages its own context via function calls to archival
  storage. The reference point for "LLM as memory manager".
- **Generative Agents** (2304.03442, 2023-04) — memory stream with recency,
  importance and relevance scoring plus reflection. Antecedent for persistent
  experience plus higher-level summaries.
- **Mem0: Building Production-Ready AI Agents with Scalable Long-Term Memory**
  (2504.19413, 2025-04) — extracts consolidated facts and compares against RAG
  and full-context baselines, reporting strong token/latency savings with
  competitive accuracy. Directly motivates our dense-RAG and full-context
  comparison.
- **Agent Zero Memory: Provenance-Aware Long-Term Memory for LLM Agents**
  (2608.29606, 2026-08) — distils conversations/files/sources into multiple
  structures and emphasizes provenance. Closest work to our provenance and
  rehydration stance.
- **MemoryLACE: Memory Lifecycle-Aware Consolidation and Evidence Retrieval**
  (2609.03201, 2026-09) — distinguishes repeated evidence, historical states,
  updates and contradictions during consolidation and retrieval. Closest work
  to our temporal/knowledge-update analysis.
- **CreaMem: A Scene-Aware Memory Architecture for Personalized Agents**
  (2609.08550, 2026-09) — organizes memories by life *scenes* to prevent
  cross-scene interference and reduce the search space. Closest work to our
  write-time organization rationale.
- **MemForest: Efficient Agent Memory Management via EventTree Partitioning
  and Progressive Merging** (2609.08273, 2026-09) — partitions history into an
  event tree and compresses progressively. Related to our partitions/rollups.

## 2. Graph and structured memory

- **HippoRAG: Neurobiologically Inspired Long-Term Memory for Large Language
  Models** (2405.14831, 2024-05) — retrieval as associative memory over a
  knowledge graph plus personalized PageRank.
- **Zep: A Temporal Knowledge Graph Architecture for Agent Memory**
  (2501.13956, 2025-01) — temporal knowledge graph memory; time as a
  first-class dimension.
- **A Graph-Native Bitemporal Memory Store for Conversational AI Agents**
  (2607.26520, 2026-07) — bitemporal graph store; close to our two-clock
  (session timestamp vs question date) framing.
- **Time is Not a Label: Continuous Phase Rotation for Temporal Knowledge
  Graphs and Agentic Memory** (2604.11544, 2026-04) — continuous temporal
  representations for agent memory.

## 3. Retrieval and evaluation

- **RAG / dense retrieval** (BM25 and embedding baselines) — the family our
  similarity arms and the dense e2e baseline instantiate.
- **LongMemEval: Benchmarking Chat Assistants on Long-Term Interactive
  Memory** (2410.10813, 2024-10) — separates extraction, multi-session
  reasoning, temporal reasoning, knowledge updates and abstention. Our
  external study uses its 50-question sample and question types.
- **LongMemEval-V2: Evaluating Long-Term Agent Memory Toward Experienced
  Colleagues** (2605.12493, 2026-05) — environment-experience memory for web
  agents.
- **LoCoMo / LOCOMO-CONV** — long conversational memory; used for evidence
  recall in the manual (not for the v1.0 e2e study; see Limitations).
- **RAG Deserves an Index: Why Ingest-Time Compilation Beats Query-Time
  Interpretation** (2608.20845, 2026-08) — argues for organizing/compiling at
  ingest time instead of interpreting at query time. Directly adjacent to our
  write-time views claim.
- **Understanding Stage-Wise Utility-Risk Trade-offs in LLM Agent Memory**
  (2608.30177, 2026-08) — stage-wise (retain/transform/expose) evaluation,
  albeit for poisoning risk rather than information loss.
- **What Eviction Destroys: A Restore-Counterfactual Audit of Forgetting in
  Agent Memory** (2609.08279, 2026-09) — reinstates gold evidence in the
  read-time context to separate irreversible eviction loss from recoverable
  retrieval failures. The closest methodological work to our gold-evidence
  condition and boundary attribution.
- **CABLE: Extending the Reach of Memory Retrieval via Complementary
  Antecedent-Based Linking and Expansion** (2608.17911, 2026-08) — studies
  *evidence reachability* through a bounded memory interface and adds
  antecedent-based linking/expansion. Closest work to our retrieval-stage
  diagnosis and to the aggregation idea we tested and refuted.

## 4. What remains novel (after the closest works)

The literature already explores: ingest-time organization
(RAG-Deserves-an-Index), evidence reachability (CABLE), gold-evidence
counterfactuals (What-Eviction-Destroys), stage-wise analysis
(Stage-Wise-Utility-Risk), provenance-aware memory (Agent Zero), lifecycle
consolidation (MemoryLACE), scene organization (CreaMem) and temporal graphs
(Zep, bitemporal store).

Therefore the v1.0 paper does **not** claim to invent multi-structure memory or
write-time organization. Its defensible contributions are:

1. **A boundary-decomposed, causal evaluation of information loss** across
   ingestion → organization → retrieval → delivery → answer, with per-boundary
   metrics (Gold Fact Retention, evidence/agent recall, fact coverage, Answer
   Utilization Rate) and paired ablations on the same questions, answerer and
   judge. The decomposition localizes *where* a failure happened instead of
   reporting a single end-to-end number.
2. **The pointer-vs-content finding (H2)**: agents that only write relevance
   notes ("this memory matters") lose the factual payload; delivering the
   memory's content raises strict accuracy 0.72 → 0.88 and AUR 0.74 → 0.90 at
   equal retrieval and cost. This is a concrete, attributable failure mode.
3. **The protective-budget result**: a gold-evidence condition with *all*
   expected sessions and no context cap underperforms a ~4,000-character
   budgeted payload (oracle 0.52 vs payload 0.56 strict; multi-session 0.08 →
   0.00). "More remembered context is not necessarily better memory" is
   demonstrated experimentally, not only invoked as a cost argument.
4. **Negative results as evidence**: prompt-only interventions (memory-aware
   framing, H4; temporal computation, H6a) fail, and multi-session aggregation
   (H5) was not the dominant bottleneck. These eliminate explanations and
   constrain the design space, which the related work above does not report.
5. **An executable open architecture** implementing the pipeline end to end
   (canonical tape, projections, perspective agents, attention, budgeted
   payload with rehydration), with reproducible harnesses and frozen artifacts.

### Claim discipline

- No "beats RAG in general" claim: retrieval advantage is regime-dependent
  (evidence recall numbers from the manual: LongMemEval dense 0.94 vs BM25
  0.85; LoCoMo agents 0.90 vs BM25 0.78 vs dense 0.56).
- The router remains opt-in; its default state is off.
- Absolute answer accuracy on LongMemEval-50 is low for every arm (0.50-0.60);
  the paper's claims are relative (parity at lower context; conditional AUR),
  and this ceiling is reported as a limitation.
