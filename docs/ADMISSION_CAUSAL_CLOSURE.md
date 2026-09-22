# Admission causal line (v1 -> v2 -> holdout) — closure record

Closed 2026-09-22 by owner decision after the holdout single evaluation
passed. The line closes with the mechanism validated **in the lab**, no
further optimizations, and the candidate kept immutable awaiting a future
real window.

## The established chain

1. **The rationale can be buried** by the lexical ranking (ranking miss).
2. **Causal relation retrieval finds it**: depth-1 expansion adds the buried
   record to the pool.
3. **Retrieval alone is not enough**: the frozen P3v4 admission rejects
   relation-linked evidence through the lexical floors (relative gain floor;
   mechanism locked by test in `tests/test_admission_causal_v1.py`).
4. **A narrow structural slot recovers it**: one `justified_by` slot, depth
   1, provenance mandatory, no threshold relief for other candidates -
   exploratory 1.000/0.857, **holdout single-shot 1.000/0.886 vs baseline
   0.645/0.833**. Both axes improved together, 22/22 buried cases recovered,
   factual control intact, no undue retrieval, budget respected.
5. The `why` cue fix (stopword tokenization) clarified **two separate
   mechanisms** - cue detection vs the relative floor - both isolated by
   tests.

## Named abstraction: operational retrieval provenance

> Every candidate carries not only content and score, but also the
> **structural reason it was retrieved**; admission may apply limited,
> auditable rules according to that origin.

Future provenance vocabulary (recorded, **not** granted slots):
`lexical_match`, `supersedes`, `justified_by`, `contradicts`,
`temporal_predecessor`, `cross_topic_link`.

**Scope limit (binding):** the result supports only the frozen narrow
mechanism - `justified_by`, depth 1, provenance mandatory, one item, hard
limits. It does not authorize slots for any other relation type.

## Candidate identity (immutable)

- **Policy S definition and constants**: `docs/ADMISSION_CAUSAL_V2_EXPLORATORY.md`
  (one `justified_by` slot, depth 1, top-3 lexical sources, raw-question cue
  regex, highest-BM25 target, provenance recorded as `relation_source`, one
  item, 4000-char budget, <= 3 items, no threshold relief; P3v4 otherwise
  unchanged).
- **Code**: `eval/admission_causal_v2.py` (policy), `eval/admission_causal_holdout.py`
  (holdout runner); fixtures `eval/fixtures/admission_causal_v1` (hash
  `cf597ae0...`) and `eval/fixtures/admission_causal_holdout` (hash
  `dd7692d5...`).
- **Recorded results**: `eval/results/admission_causal_v2/` (exploratory),
  `eval/results/admission_causal_holdout/` (single evaluation).
- **Git anchors**: prereg `1155818`, exploratory record `496882b`, holdout
  prereg `a03649a`, holdout record `0f5ac3e`, merge `9b6e175` (v0.2.3 line).
- Any modification of the policy, constants, fixtures or runners invalidates
  the validation.

## Status

- **Synthetic line closed; no further optimizations on this line.**
- The candidate awaits a **future real window starting from zero**, with its
  own pre-registration (dual-track plan); it is never auto-promoted.
- Production is unchanged; `admission-shadow-v2` keeps collecting in silence
  until `met: true`.
- Related closures: `docs/ADMISSION_SYNTHETIC_CLOSURE.md` (P1-P4 family,
  negative), `docs/ADMISSION_PORTFOLIO_V1_PREREG.md` (P4 family closed on
  its fixture).
