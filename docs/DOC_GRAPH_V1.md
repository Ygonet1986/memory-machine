# doc-graph-v1 — review + pre-registered rebuild-fidelity protocol

**Status: PRE-REGISTERED (frozen before execution)** · review target:
D5 @ `a7f4ae3` (+docs `4d93fd6`) · suite: **406 green** · precedent: U4.2
byte-identical replication and its oscillation-floor lesson.

This document registers, before any benchmark run, the exact question, input
contract, arms, metrics, normalization rules and failure criteria of the
`doc-graph-v1` gate. Nothing below is chosen after seeing results (discipline
of M0150 / U4.2).

---

## 1. Decision question

> Given the **same original TXT** and the **same configuration/extractor**, does
> the rebuilt documental graph preserve the **structure and provenance** of the
> original projection?

The question is narrow by design: it gates the **rebuild**, not the extractor.
An LLM extraction pass is stochastic; the gate must separate *program-controlled
identity* (must be deterministic) from *extractor-dependent output* (measured
stability). Requiring byte-identity of LLM output would be a false gate.

## 2. Review summary (invariant audit, D1–D5)

Fixes/design reviewed end-to-end at the hashes above. Every invariant below was
traced in code, not just inferred from tests.

| # | Invariant | Code surface | Verdict |
|---|---|---|---|
| R1 | Commit order tape → registry → graph; graph last, never propagates failures | `ingest_document.py` pipeline | hold |
| R2 | Rebuild never mutates the tape (read-only) | `build_graph` signature + `_build_into` | hold |
| R3 | `documents.jsonl` carried across atomic rebuild (registry is canonical) | `copy_documents_from` / backup-restore in non-atomic | hold |
| R4 | M0173 fixed: a plain rebuild no longer drops document rows — doc pass replayed after durable pass | `build_graph` → `rebuild_document_projection` | hold |
| R5 | Hash gate before mutation; missing/adulterated original aborts, previous graph kept | `validate_originals` + atomic `graph.building/` swap | hold |
| R6 | Evidence confined to real window members; empty → all members | `_resolve_window_evidence` | hold |
| R7 | Window ids `D####|wNN`, tags `name/version` vs `name/version/document`, cost = `len(why)` | window pass + `WINDOW_SCOPE_TAG` | hold |
| R8 | Meta settle keeps `meta.tag` chunk-level (`document_tag`, `document_structure_level` separate) | `_settle_meta` at both call sites | hold |
| R9 | graph-v3 default untouched: `document_structure_level=None` → byte-behavior | `build_graph` default branch | hold |
| R10 | Scope labels `extraction_scope ∈ {chunk, document}`; D3 rows stay readable | schema v3 `from_dict` | hold |

**Findings (non-blocking):**
- F-1 *(robustness garbage, not an invariant break)* the registry stores the
  preserved file as an **absolute path**. If the project root is moved, a
  rebuild/status on stale `documents.jsonl` will report `original missing` even
  though `<root>/documents/<name>` exists — it fails **closed**, never
  approximates. Recommendation for a future maintenance commit: resolve
  `doc.original` against `documents_root/<name>` when the absolute path is stale
  but the name exists.
- F-2 *(contractual, by design)* rebuild fidelity requires the same
  `structure_level` and `window_chars` as the original ingest — they are not
  stored in the registry. The protocol fixes them in the canonical state; a
  config-change between ingest and rebuild is out of question scope.

**Conclusion:** no invariant break found; the review passes. The gate now rests
solely on the empirical protocol below.

## 3. Canonical state (input contract)

One machine root, fixed by the harness and recreated identically for every arm:

- **Corpus:** the embedded seed files (`tech-notes.txt`, `novella.txt`,
  `decisions.txt`) with pinned byte content (UTF-8, no trailing junk), each
  1–2k characters.
- **Chunking:** `chunk_size=400`, `overlap=50` → unambiguous chunk spans,
  2–3 windows per document at `window_chars=12000`.
- **Scope:** `structure_level="both"` (chunk + document rows coexist).
- **Registry + originals:** one `documents.jsonl` row per file under
  `<root>/graph/documents.jsonl`; preserved bytes under `<root>/documents/`.
- **Tape:** exactly the `attachment` chunk records (no durable records) —
  isolates the document layer under test.
- **Extractor:** pinned `name`/`version` (recorded in `meta.json`); identical
  parameters (`temperature=0.0`) in every arm.

The harness writes the **canonical snapshot** (byte copies of `tape.jsonl`,
`documents.jsonl`, `documents/*`) into a read-only staging dir. Both rebuild
arms are seeded exclusively from those bytes — never from the original graph.

## 4. Arms

```
Original O   ingest of the canonical corpus          (graphO, built by the pipeline)
Rebuild A    independent rebuild from canonical bytes (graphA: fresh store, atomic build)
Rebuild B    independent rebuild from canonical bytes (graphB: fresh store, atomic build)
also:        A ↔ B
```

A and B are **two draw from the extractor**, exactly as U4.2 re-ran identical
contexts. Each rebuild starts from a store with the canned registry and no
extraction rows, so chunk + window passes execute fresh over the same tape. If
A and B differ from O and from each other at the same scale, that scale is
**extractor variance**, not rebuild defect.

## 5. Deterministic metrics (program-controlled identity, bar = 100%)

Volatile-excluded fields, fixed in advance: `created_at`, `updated_at`,
`built_at` on rows and in `meta.json`. `meta.counts` is compared only on the
deterministic arm (informational on the LLM arm).

| # | Metric | Bar |
|---|---|---|
| D1 | Tape bytes identical before/after every arm (`tape.jsonl`) | 0 bytes diff |
| D2 | Registry rows identical across O/A/B (id, source, name, hash, path, spans, extractor, status, original) | 100% |
| D3 | Originals all present and `validate_originals` clean in every arm; registry hash = hash of preserved bytes | 0 violations |
| D4 | Idempotency units: chunk `M####` ids + spans, window `D####|wNN` ids + spans identical across arms | 100% |
| D5 | Provenance: every relation/entity/mention in A/B has `source_document ∈` registry sources | 0 dangling |
| D6 | Evidence closure: doc-scope evidence `memory_id`s ⊆ window members, spans within the window; chunk-scope evidence within the record span | 0 leaks |
| D7 | Scope discipline: `extraction_scope ∈ {chunk, document}`; document rows carry doc provenance; no cross-contamination | 0 violations |
| D8 | Document bounds: every `source_span` inside `[0, len(preserved text))` and contiguous within the doc's span list | 0 violations |

D1–D8 are gated on **both** arms (deterministic and LLM), because they concern
program behavior, not model output.

## 6. Semantic metrics (extractor-dependent, registered)

Pre-registered normalization `norm`: NFC → lowercase → strip combining marks →
keep `[a-z0-9 ]` → collapse whitespace. Plural-strip (trailing `s`, len>3) is a
**separate variant** reported alongside.

| # | Metric | Definition |
|---|---|---|
| S1 | Entity stability | per-scope set of `(norm(name), norm(type), scope, source_document)`; pairwise Jaccard + precision/recall over the O/A, O/B, A/B matrix |
| S2 | Relation stability | set of `(norm(source), norm(verb), norm(target), scope, source_document)` (S2b: + naive plural-strip on the verb) |
| S3 | Evidence coverage | for **aligned** relations (same canonical key): mean recall of evidence `memory_id`s (exact match; a span-overlap variant reported second) |
| S4 | Structural drift | window set, chunk set, per-document entity-type histogram (per scope), mention/event counts; Jaccard + absolute deltas |
| S5 | Extraction health | `pending`/`failed` counts per arm (bar 0; a failure makes the arm invalid, not a stability signal) |

## 7. A/B variance rule (U4.2 precedent)

For every numeric semantic metric `m`, define the pairwise distance
`Δ(m)` = 1 − Jaccard (precision/recall always reported too).

> **Pre-registered rule:** the rebuild is faithful on `m` iff
> `Δ₍A,B₎(m) ≤ max(Δ₍O,A₎(m), Δ₍O,B₎(m))`.

`Δ(OH,A)` and `Δ(O,B)` bound the extractor's own draw-to-draw variance starting
from the same state; if `A ↔ B` exceeds that bound, the rebuild injected noise
beyond the extractor and is suspect. **No tolerance constant is introduced
post hoc.** Subthreshold equality on the deterministic arm (fake extractor) must
yield `Δ = 0` everywhere — this is the harness's built-in self-check.

## 8. Pre-registered failure criteria

The tag is refused unless **all** of the following hold; intermediate evidence
never promotes `doc-graph-v1`:

- **F0** D1 tape not byte-identical → FAIL.
- **F1** D2 registry drift across arms → FAIL.
- **F2** D3 any missing/adulterated original or divergent hash accepted → FAIL.
- **F3** D4/D5/D6/D7/D8 any provenance, scope or bounds violation → FAIL.
- **F4** S5 `pending`/`failed` > 0 in any arm → FAIL (incomplete extraction).
- **F5** Any semantic metric violates the §7 ordering → FAIL (suspected rebuild
  defect; investigate before any decision). No criterion is weakened after the
  fact; a failed gate means: small targeted fix → re-run → re-review, never
  re-fit of the rule.

On **PASS**: `Δ ≈ 0` behavior is confirmed on the deterministic arm, the LLM
arm's semantic table is registered verbatim, and the sequence advances to
tag `doc-graph-v1` → results → **Fase P (plasticity)**, now over Tape canônica +
preserved originals + ressonable spans + plural evidence + an auditable,
reconstructible graph.

## 9. Harness and output contract

`python3 eval/doc_graph_rebuild.py` (committed, deterministic by default;

`--llm` selects the real `GraphExtractor`). It writes:

- `build/` — canonical snapshot bytes (provenance of the run),
- `graphO|graphA|graphB/` — the three projections,
- `doc_graph_rebuild.json` — D1–D8 verdicts, S1–S5 table, Δ matrix, decision,
- `doc_graph_rebuild_summary.md` — the registered report (verbatim table).

The LLM arm requires a working API key and re-runs the extractor; it is the
**separate execution step** scheduled after this registration is committed.

## 10. Frozen scope (non-goals)

No changes to graph-v3, recall/admission defaults, `extraction_scope` semantics,
the D3/D4 contract or `docs/DOC_GRAPH.md`. The review may not reopen D5. This
protocol measures; only Fase P proposes plasticity changes afterwards.