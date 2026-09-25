# Where Long-Term Agent Memory Loses Information

## A boundary-decomposed experimental study

**Draft for arXiv (v1.0, September 2026)**

> Snapshot note (2026-09-24): the contents below are the frozen
> v1.0 record. Current architecture, the Companion track and the
> active admission window live in docs/ARCHITECTURE.md.

---

## Abstract

Long-term memory for LLM agents is usually evaluated end to end: one accuracy
number over a long conversation. That number cannot tell whether a failure
happened when the history was written, when it was organized, when it was
retrieved, when it was placed in the context, or when the model used it. We
present an experimental study that decomposes the memory pipeline into five
boundaries — **ingestion, organization, retrieval, delivery, answer** — and
measures each one separately with per-boundary metrics: Gold Fact Retention
(GFR), view/agent evidence recall, fact coverage, context characters, Answer
Utilization Rate (AUR) and judge-reported strict/lenient accuracy. Using a
purpose-built but minimal system (Memory Machine) and two frozen benchmarks
(a 32-task synthetic fixture and a 50-question sample of LongMemEval), we run
paired ablations on the same questions, answerer and judge. The decomposition
localizes several failures that an end-to-end score hides: (1) truncating
sessions at ingestion nearly halves Gold Fact Retention (0.83 → 0.42) and caps
end-to-end accuracy, while evidence recall stays constant — the loss is at
write time, before retrieval; (2) perspective agents that emit only relevance *notes* lose
the factual payload, and delivering the *content* raises strict accuracy
0.72 → 0.88 and AUR 0.74 → 0.90 at equal retrieval and cost; (3) a budgeted
evidence payload matches full-context accuracy at 57–70% fewer context
characters; (4) a gold-evidence condition with all sessions and no cap
*underperforms* the budgeted payload (0.52 vs 0.56 strict; multi-session
0.08 → 0.00), evidence that more remembered context is not necessarily better
memory; (5) prompt-only interventions — memory-aware framing and an explicit
temporal-computation procedure — fail, while restoring real session timestamps
raises temporal reasoning from 0.29 to 0.64 and lifts every temporal question
with complete evidence from 4/9 to 9/9. A flat session-level dense baseline
with the same ingestion, answerer and judge reaches only 0.24 evidence and 0.16
strict while delivering almost as many context characters as the full-context
arm: retrieval quality and context size are different axes. We also document a
harness bug in the first runs of the corrected experiments, kept as `*_BUGGY`
artifacts, whose fix reversed two conclusions; we report only post-fix
numbers. All harnesses,
frozen snapshots, checksums and figures are released so the study can be
re-run and audited.

---

## 1. Introduction

Memory systems for LLM agents are built as pipelines: raw history is
**ingested**, organized or summarized into **structurally** stored memories,
**retrieved** as evidence, **delivered** into a limited context window, and
finally **used** by a language model to answer. Every stage can lose
information, and the stages interact. A single end-to-end accuracy number
averages over all of them.

This paper asks a narrower and more causal question: **where, in the pipeline,
does evidence get lost, and which losses actually reach the answer?** To answer
it we built a small, inspectable memory system (Memory Machine; §3) whose
stages can be toggled independently, instrumented every boundary with a metric,
and ran paired ablations on two frozen benchmarks (§4). The result is a set of
attributable failure modes rather than a leaderboard claim.

### 1.1 Contributions

1. **A boundary-decomposed causal evaluation.** We define five boundaries with
   per-boundary metrics and paired arms that differ in exactly one boundary;
   the same answerer, judge, questions and seeds are used throughout. This
   localizes failures that end-to-end numbers average away.
2. **Write-time loss dominates, and it is invisible to retrieval metrics.** On
   LongMemEval-50, storing truncated sessions drops Gold Fact Retention from
   0.83 to 0.42 while evidence recall stays flat at 0.75: the system retrieves
   the right memories, but the facts are already gone. Restoring full
   ingestion recovers GFR to 0.83 and end-to-end strict accuracy 0.33 → 0.50 on
   the fixed 12-question sample.
3. **The pointer-vs-content finding.** A perspective agent can have
   near-perfect evidence recall (0.97 complete evidence at 4.1 calls) and still
   lose the answer, because it writes relevance notes instead of the memory's
   content.
   Delivering the content raises strict 0.72 → 0.88 and AUR 0.74 → 0.90 at
   equal evidence (0.97) and equal cost (4.0–4.1 calls).
4. **A budgeted payload with a protective effect.** A ~4,000-character payload
   matches full-context accuracy (−70% characters) and slightly exceeds it; a
   gold-evidence condition with all expected sessions and **no cap** (~14.2k
   characters) scores *worse* (0.52 vs 0.56 strict) and collapses on
   multi-session questions (0.08 → 0.00). More remembered context is not
   necessarily better memory.
5. **Negative results that constrain the design space.** Prompt-only
   interventions fail: memory-aware answer framing (H4) lowers accuracy
   (0.56 → 0.50), and a task-specific temporal-computation procedure (H6a)
   changes nothing on temporal questions once timestamps are correct. The
   measured fixes were architectural — payload delivery and real timestamps —
   not instructions.
6. **A provenance fix with a clean effect.** Restoring the real session
   timestamps and the question date raises temporal-reasoning accuracy
   0.29 → 0.64 and, conditional on complete evidence, 4/9 → 9/9, with controls
   (evidence recall, GFR) held.
7. **Reproducibility without hero numbers.** All harnesses, snapshots,
   checksums and figures are released. We document a harness bug whose fix
   reversed two conclusions and keep the buggy snapshots as `*_BUGGY`
   artifacts. LongMemEval-50 absolute accuracy is low for every arm (0.50–0.64
   strict); our claims are relative and conditional.

### 1.2 What this paper does not claim

We do not claim a new memory architecture, and we do not claim to beat RAG in
general. Retrieval quality is regime-dependent in our own external study
(evidence recall: LongMemEval dense 0.94 vs BM25 0.85; LoCoMo agents 0.90 >
BM25 0.78 > dense 0.56), and the router that selects memory structures remains
opt-in, off by default. The contribution is the *decomposition* and the
attributable findings, not a universal win.

---

## 2. Related work

**Long-term agent memory.** MemGPT (2310.08560) treats the LLM as an operating
system that pages memory in and out of context. Generative Agents (2304.03442)
introduce a memory stream with recency, importance and relevance scoring plus
reflection. Mem0 (2504.19413) extracts consolidated facts and reports strong
token/latency savings against RAG and full-context baselines — the comparison
we instantiate with a budgeted payload and a dense baseline. Recent systems
push on organization and provenance: Agent Zero Memory (2608.29606) is
provenance-aware, MemoryLACE (2609.03201) does lifecycle-aware consolidation,
CreaMem (2609.08550) organizes by scene, and MemForest (2609.08273) partitions
history into an event tree.

**Graph and structured memory.** HippoRAG (2405.14831) retrieves via a
knowledge graph and personalized PageRank; Zep (2501.13956) makes time a
first-class dimension in a temporal knowledge graph; a bitemporal memory store
(2607.26520) and continuous phase rotation (2604.11544) explore temporal
representations. Our two-clock framing (session timestamp for what was said,
question date as "now") is adjacent to the bitemporal work but used as an
ablation variable, not as a store design.

**Retrieval and evaluation.** LongMemEval (2410.10813) separates extraction,
multi-session reasoning, temporal reasoning, knowledge updates and abstention;
we use its 50-question sample. LongMemEval-V2 (2605.12493) targets
environment-experience memory. RAG Deserves an Index (2608.20845) argues for
ingest-time compilation; Stage-Wise Utility-Risk (2608.30177) evaluates
retain/transform/expose stages for poisoning risk; What Eviction Destroys
(2609.08279) uses gold-evidence reinstatement to separate irreversible
eviction from recoverable retrieval failure; CABLE (2608.17911) studies
evidence reachability through a bounded memory interface.

**Positioning.** After these works, multi-structure memory, write-time
organization, provenance and gold-evidence counterfactuals are not novel in
themselves. What this paper adds is the *joint* boundary decomposition with
per-boundary metrics on the same frozen questions, the pointer-vs-content
failure mode, the protective-budget result, the negative prompt-intervention
results, and an executable open architecture with preserved buggy artifacts.

---

## 3. The Memory Machine, in brief

The system exists to make each boundary independently configurable; it is not
itself the contribution. The core is pure Python standard library.

- **Tape.** An append-only canonical store of typed memory records
  (`fact | event | decision | summary | note | ...`) with provenance,
  timestamps and supersedence links. Nothing is destructively edited.
- **Views.** Write-time projections over the tape: time, type, source, topic
  and subject. A view is a *pointer set plus a rollup*, not a copy; producers
  register rollups on append.
- **Perspective agents.** One agent per view answers "which memories matter
  for this question", optionally with an LLM, optionally writing only a note
  (the failure mode of §5.3) or emitting the content.
- **Dimension routing.** A router plans a retrieval over dimensions
  (time/type/source/topic/subject) with intersection and progressive
  relaxation; it is opt-in and off by default.
- **Attention state.** A small persistent state (selected ids + scores) that
  biases the next turn. Conversation experiments show it stabilizes anaphora
  (calls 15 → 3) at the cost of old-topic residual (0.56) unless the gate
  includes the conversation context.
- **Evidence payload.** A water-filling builder that assembles memory *content*
  under a character budget, with provenance headers (`[id | date] summary`,
  content, supersedence notes). The payload is ephemeral: it is rebuilt each
  turn and never merged into the tape.
- **Answerer and judge.** A single answerer model with a fixed system prompt;
  a frozen three-way judge (`correct | partial | incorrect`) blind to the arm;
  a stratified audit re-judges ~25% of answers with the same model.

Boundary metrics used throughout:

| Boundary | Metric | Definition |
|---|---|---|
| Ingestion | Gold Fact Retention (GFR) | fraction of gold facts present in the tape after ingestion |
| Organization | view recall / precision | whether expected views exist for the question's dimensions |
| Retrieval | evidence recall; agent recall | gold sessions retrieved; views activated |
| Delivery | fact coverage; context chars | gold facts present in the delivered context; size |
| Answer | strict / lenient / AUR | judge=correct; correct or partial; correct among questions with complete evidence (Answer Utilization Rate) |

---

## 4. Methodology

**Benchmarks.** (i) A synthetic fixture of 32 tasks across categories
(factual recall, preference, temporal, multi-session, update,
contradiction/resolution, abstention), each with gold sessions and a reference
answer (seed 7). It is intentionally small and fully controlled, for paired
ablations and routing benchmarks. (ii) LongMemEval-50: a frozen 50-question
sample with official categories (single-session-user, single-session-assistant,
multi-session, temporal-reasoning, knowledge-update), full ingestion unless a
variant says otherwise, and the same gold answers. (iii) For evidence recall
only, external runs on LongMemEval-100 and LoCoMo-150 described in the manual.

**Arms.** Synthetic: `no_memory`, `bm25`, `agents_group` (partition agents),
`agents_view` (pointer notes), `agents_view_ctx` (full content), 
`agents_view_payload` (budgeted content), `oracle` (gold evidence as context).
LongMemEval: `agents_view_ctx` (full), `agents_view_payload` (budgeted;
2,500/4,000/6,000), `oracle`/`oracle_dates` (gold-evidence full-context),
payload `+dates`, payload `+dates+temporal`, and a dense RAG baseline.

**Judge and audit.** The judge is frozen v1, blind to arm, three-way. A
stratified ~25% audit re-judges with the same model; per-arm agreement is
0.75–1.00. All accuracies are judge-reported.

**Frozen regime and hygiene.** Same questions, seed, answerer, judge, ingestion
and budget across arms; a `run_manifest` is written per run; secret-like
benchmark sessions are skipped by the ingestion scanner (never bypassed);
`eval/data` and `eval/out` are gitignored; snapshots are checksummed.

**Harness bug and correction (reported for transparency).** The first runs of
the two "dates" payload arms were missing from the payload-delivery branch of
the harness and therefore measured whiteboard-only answers (fact coverage
0.16, no payload in the context). The fix added a `PAYLOAD_ARMS` set. The
original snapshots were preserved as `*_BUGGY.jsonl`; the corrected re-runs
reverse the H5′/H6a conclusions reported in an earlier draft of this project.
All numbers in this paper are post-fix. Audit agreement for the corrected arms
is 1.00 (12/12) and 1.00 (12/12).

---

## 5. Results by information boundary

### 5.1 Ingestion: truncation destroys facts before retrieval

LongMemEval sessions have a median length of ~10.4k characters. When the
external harness stored only the first 2,000 characters per session, end-to-end
strict accuracy on the fixed 12-question sample was 0.33 and Gold Fact
Retention 0.42. Raising the cap raises both monotonically:

| ingest cap | GFR | strict | evidence recall | fact coverage |
|---|---|---|---|---|
| 2,000 | 0.42 | 0.33 | 0.75 | 0.83 |
| 4,000 | 0.50 | 0.33 | 0.75 | 0.87 |
| 8,000 | 0.58 | 0.42 | — | 0.86 |
| full | 0.83 | 0.50 | 0.75 | 0.87 |

The evidence-recall column is constant: retrieval is not the stage that
improved. The facts were missing from the tape, and no downstream component
could recover them. This is the clearest boundary attribution in the study:
**write-time loss is silent to retrieval metrics**.

### 5.2 Organization and retrieval: agents over views

On the 32-task synthetic fixture, a cascade of BM25 view selection plus
dimension routing recovers complete evidence for 0.91 of tasks at ~10 calls;
adding a pruning pass over view agents reaches 0.97 complete evidence at 4.9
calls; the lexical view-agent configuration reaches 0.97 at 3.0 calls; the
stateless LLM+pruned view-agent configuration reaches 1.00 complete evidence
at 5.0 calls in the H1 runs (persistent variant: 0.97 at 4.9 calls; oracle:
1.00 at 7.4 calls). Partition agents (`agents_group`) also reach 1.00
complete evidence but need 15.2 calls. Dimension routing itself is reliable
(dimension recall 1.0, precision 0.82, recovery 0.94–0.97), which is why the
aggregation hypothesis (H5) — that combining multi-session evidence is the
bottleneck — was refuted: multi-session was the *easiest* category in the e2e
study (0.77) and temporal reasoning the worst (0.29).

**Attention.** Replaying 8 focused tasks 5 times each, deterministic
lexical+prior attention is perfectly stable (modal 1.00, Jaccard 1.00),
whereas LLM-driven attention without state is only modal 0.75 / Jaccard 0.80.
In a 4-turn conversation, attention reduces anaphora retrieval from 15 and 16
calls to 3–7, but a topic shift leaves 0.56 residual old-topic attention
unless the gate includes conversation context. Attention is a latency/context
tool, not an accuracy fix.

### 5.3 Delivery: pointers are not content

The sharpest paired result in the study. Three arms have (near-)identical
retrieval, cost and question set; they differ only in what is delivered to the
answerer:

| arm | evidence | strict | lenient | AUR | fact coverage | chars | calls |
|---|---|---|---|---|---|---|---|
| `agents_view` (notes only) | 0.97 | 0.72 | 0.94 | 0.74 | 0.73 | 0 | 4.1 |
| `agents_view_ctx` (full content) | 0.97 | 0.88 | 0.97 | 0.90 | 0.99 | 1,632 | 4.0 |
| `agents_view_payload` (budgeted) | 0.97 | 0.97 | 1.00 | 1.00 | 0.99 | 2,007 | 4.1 |
| `oracle` (gold evidence) | 1.00 | 0.94 | 0.97 | 0.94 | 1.00 | 242 | 1.0 |

The agent with pointer notes found the right memories but delivered "this
matters" instead of the facts; fact coverage 0.73 vs 0.99. Delivering content
in the same retrieval regime moves strict 0.72 → 0.88 and AUR 0.74 → 0.90.
Adding the budgeted format adds the remaining gain (0.88 → 0.97) by ordering
and trimming what the context shows. This is the **pointer-vs-content**
failure mode: an agent can have near-perfect evidence recall and still lose
the answer.

### 5.4 Budget: a payload that protects

On LongMemEval-50, packing the retrieved content under a character budget
matches — and at 6,000 characters slightly exceeds — full-context accuracy,
while using 57–70% fewer characters:

| arm | evidence | strict | lenient | AUR | chars | calls |
|---|---|---|---|---|---|---|
| full context | 0.74 | 0.58 | 0.66 | 0.78 | 12,947 | 4.4 |
| payload 6,000 | 0.74 | 0.60 | 0.64 | 0.78 | 5,539 | 4.4 |
| payload 4,000 | 0.74 | 0.56 | 0.62 | 0.76 | 3,836 | 4.4 |
| payload 2,500 | 0.74 | 0.52 | 0.66 | 0.68 | 2,430 | 4.4 |

The compression curve has a knee around 4,000 characters; at 2,500 the
conditional utilization (AUR) drops first. The budget is not merely a cost
knob. A gold-evidence condition that includes **all** expected sessions with
**no cap** (≈14.2k characters) scores below the 4,000-character payload
(0.52 vs 0.56 strict; AUR 0.52 vs 0.76) and collapses on multi-session
questions (from 0.08 to 0.00 in the dated condition). More remembered context
is not necessarily better memory: past a point, extra irrelevant-but-true
context actively dilutes the answerer.

### 5.5 Answer: prompts do not fix what architecture breaks

Two prompt-only interventions were tested and refuted:

- **H4, memory-aware framing.** Telling the answerer that its context is a
  curated memory and to prefer it lowers strict 0.56 → 0.50 (AUR 0.76 → 0.68)
  and does not help the gold-evidence condition either (0.52 both). An error
  taxonomy over the failing questions shows insufficient-evidence errors
  dominating (16–22 of ~25 errors), not mis-framing.
- **H6a, temporal-computation procedure.** A gated procedure (list timestamps,
  resolve relatives against the session clock, use the question date as "now",
  compute, verify) adds nothing on temporal questions once timestamps are
  correct (0.64 → 0.64; conditional 1.00 → 1.00). Its small aggregate gain
  (0.64 → 0.70 strict) comes from small-n non-temporal cases.

### 5.6 The temporal case: provenance beats instructions

The temporal-reasoning category was the worst at 0.29 because the loader
discarded `haystack_dates` and `question_date`; every external memory fell
into `time/2026-09` and payload headers showed ingestion time. Restoring the
real session timestamps and the question date (same ingestion, payload,
budget, answerer and judge) changes:

| arm | evidence | strict | AUR | temporal (n=14) | temporal \| evidence complete (n=9) |
|---|---|---|---|---|---|---|
| payload 4,000 | 0.74 | 0.56 | 0.76 | 0.29 (4/14) | 0.44 (4/9) |
| + real dates | 0.72 | 0.64 | 0.89 | 0.64 (9/14) | **1.00 (9/9)** |
| + dates + temporal prompt | 0.72 | 0.70 | 0.97 | 0.64 (9/14) | **1.00 (9/9)** |

All four audited target errors (relative-date resolution, wrong anchor,
interval computation, date-window selection) were fixed by the timestamps
alone. Every temporal question with complete evidence is now answered
correctly; all five remaining errors are retrieval misses. The bottleneck
moved from the answerer to retrieval — a boundary attribution that would be
invisible in the aggregate number alone.

### 5.7 Flat dense baseline: context size is not evidence

The same harness, full ingestion (GFR 0.86 confirms the tape has the facts),
real dates, answerer, judge and question set; only retrieval and delivery
differ: one dense vector per session (`nomic-embed-text`, 2048-token model
context; top-5 by cosine), full text of the ranked sessions under the same
context builder as the BM25 arm.

| arm | evidence | strict | lenient | AUR | GFR | fact coverage | chars | calls |
|---|---|---|---|---|---|---|---|---|
| dense top-5 (session vectors) | 0.24 | 0.16 | 0.24 | 0.58 | 0.86 | 0.46 | 11,036 | 1.0 |
| view agents + payload 4,000 | 0.74 | 0.56 | 0.62 | 0.76 | 0.84 | 0.83 | 3,836 | 4.4 |

GFR is intact, so ingestion is not the problem; the session-granularity dense
ranking simply fails to recover the complete gold set (0.24 evidence), and 41
of the 50 errors are classified `insufficient_evidence`. The dense arm's mean
context (11,036 characters) is close to the full-context arm's (12,947) with a
fraction of the evidence — **context size and evidence are different axes**.
Two caveats: (i) this baseline embeds each session as a single vector truncated
to 2048 tokens, which is a lower bound for dense RAG; chunk-level dense
retrieval is stronger (our external evidence-recall study reaches 0.94 on
LongMemEval-100 with chunked retrieval, manual Part IV), though at a different
granularity and not part of this e2e comparison; (ii) the arm was run once on
the frozen 50-question sample.

### 5.8 The memory lifecycle: admissions and retroactive recovery (shadow only)

A separate shadow study asked whether a classification layer over the tape can
shrink the consultable set without losing recoverable facts, and whether a
coverage-triggered re-search of the event log can recover the rest. On the
frozen fixture (32 records, 20 probes, 17 required): admissions reduce the
consultable set by 46.9% while promotion precision rises from 0.531 to 0.765;
the event-log BM25 retriever finds every recoverable false discard at rank 1
(4/4); four pre-registered trigger designs (zero-overlap, plain coverage, IDF
coverage, event-vs-active score ratio) raise trigger quality 0.25 → 0.75 with
final precision@k 1.000 and combined availability 0.952 (floor 0.93), but the
last case is a genuine near-tie (A*=2.734 vs E*=3.395, ratio 1.242 against the
frozen 1.25 factor) and the line closed by its pre-declared stop rule. Nothing
was promoted; the tape, classifier and retrieval path were untouched. Full
record: `LIFECYCLE_CLOSURE.md`; pre-registrations with execution records:
`LIFECYCLE_V1_PREREG.md` … `LIFECYCLE_V4_PREREG.md`.

### 5.9 Unconditional retrieval: availability is free, precision is the price

The lifecycle trigger missed one reconstructable case because deciding *when*
to search is fragile. Removing the trigger entirely - always searching the
promoted set plus a cheap lexical index of the non-rejected log, one ranking
scale, one budget - recovers all four former false discards at rank 1
(availability 1.000 vs 0.952) on the frozen fixture, but full top-5 delivery
precision falls to 0.512. Bounding candidacy with a high-confidence margin
(rank-1 plus score >= 0.90 x best) lifts precision to 0.826 above the 0.80
floor while dropping availability to 0.905. The sensitivity curve shows the
frontier is structural for score-margin and budget families: no point meets
both gates (availability >= 0.952 with precision 0.556 at top-2; precision
0.826 with availability 0.905 at margin 0.90). The causes are specific: one
required occurrence sits at rank 2 with a score ratio in (0.50, 0.70), another
at rank 3 unreachable by any margin, and the noise shares their score band.
Descriptive precision@1 is 0.947 - the evidence is strong in the first slot
and the cost lives in the second. Shadow-only; full record:
`TWO_TIER_CLOSURE.md`.

---

## 6. Discussion

Three patterns generalize beyond this system.

1. **Measure the boundaries you can name.** Every headline failure in this
   study was attributed to a stage: ingestion truncation (GFR vs constant
   evidence recall), pointer-vs-content (equal evidence, unequal fact
   coverage), dilution (equal evidence, more characters, lower AUR), and
   provenance (equal system, real timestamps). The dense baseline makes the
   same point from the other side: it delivers almost as many characters as
   the full-context arm while carrying a fraction of the evidence, and scores
   0.16 strict. A single accuracy number cannot distinguish these; per-boundary
   metrics can.
2. **The measured fixes were architectural, not instructional.** Deliver
   content, restore timestamps, budget the context. Prompts that reframe or
   instruct the answerer did not move it. This is a scoping result for agent
   memory work: spend effort on what is delivered and how it is stored.
3. **Conditional accuracy is the honest metric.** AUR (correct among questions
   with complete evidence) separates retrieval failures from answerer
   failures, and it changes the conclusion of an experiment. H5′/H6a reversed
   after a harness fix; AUR made the reversal legible (0.44 → 1.00 vs a flat
   aggregate).

### 6.1 Threats to validity

Small n (32 synthetic; 50 LongMemEval; some categories n=3) means single-case
differences are noise; we say so wherever it applies. One answerer and one
judge model are used (judge audited, agreement 0.75–1.00). The bug story is
itself evidence that harness-level failures can silently manufacture
conclusions; we kept the buggy artifacts rather than deleting them.

---

## 7. Limitations

- **No LoCoMo end-to-end study.** LoCoMo appears only in evidence-recall runs
  from the manual; a full e2e comparison is future work.
- **Absolute accuracy is low** on LongMemEval-50 (0.50–0.70 strict); the
  claims are relative and conditional.
- **Single-model evaluation.** Answerer and judge are from one model family;
  the judge audit mitigates but does not remove this.
- **Dense baseline granularity.** The e2e dense baseline embeds one vector per
  session (truncated to the embedding model's 2048-token context), which is a
  lower bound for dense RAG; chunk-level dense retrieval is not part of the
  e2e comparison.
- **Synthetic fixture size.** Routing and attention results are from a
  32-task fixture and an 8-task stability replay.
- **External ingestion caps.** The external harness historically truncated
  sessions (§5.1); the main e2e study uses full ingestion, but older
  evidence-recall runs are affected and are reported with caps visible.
- **Router opt-in.** The dimension router is off by default and its benefit is
  regime-dependent.

---

## 8. Reproducibility

- Core: `src/memory_machine/` (stdlib only). Harnesses: `eval/` 
  (`view_router_bench.py`, `stability_bench.py`, `conversation_bench.py`,
  `continuity_bench.py`, `external_bench.py`, `e2e_bench.py`).
- Frozen artifacts: `eval/archive/` (routing JSONs, scripts, logs,
  `CHECKSUMS.txt`); snapshots `eval/out/*.jsonl` with checksums; buggy
  first-run snapshots preserved as `*_BUGGY.jsonl`.
- `eval/report.py` regenerates `docs/RESULTS.md` and six CSV tables from the
  frozen artifacts; `eval/figures.py` regenerates the figures (PDF/SVG) and
  their source CSVs in `docs/figures/`.
- Tests: 226 unit tests pass. Secret-like benchmark sessions are skipped by
  the ingestion scanner, never bypassed.

---

## 9. Conclusion

We decomposed long-term agent memory into five informational boundaries and
measured each one with paired ablations. The study localizes failures that
end-to-end accuracy hides: truncated ingestion silently deletes gold facts
while retrieval looks healthy; perspective agents can find every memory and
still lose the answer by delivering pointers instead of content; a budgeted
payload matches full context at a fraction of the characters, and *unbounded*
gold context performs worse than the budgeted payload; prompt-only fixes fail
while timestamp provenance lifts conditional temporal accuracy to 9/9. Along
the way, a harness bug reversed two conclusions — a reminder that the
measurement pipeline is itself part of the system under study. All artifacts
are released so that the decomposition, not just the system, can be attacked
and reused.

---

## Appendix A. Full result tables

See `docs/RESULTS.md` (generated) and `docs/figures/*.csv`.
