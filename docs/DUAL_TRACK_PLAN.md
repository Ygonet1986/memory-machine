# Dual-track plan: synthetic lab and real shadow

Status: **recorded decision** (2026-09-22). Supersedes the narrow reading that
synthetic data would replace real validation.

## The two independent tracks

| Track | Purpose | What it can prove |
|---|---|---|
| **Synthetic lab** | invent and eliminate ideas fast (hundreds/thousands of controlled situations) | behavior under controlled scenarios |
| **Real shadow** | validate the frozen candidate in true usage | evidence of product performance |

Synthetic data is a **wind tunnel**: quick tests for corrections,
contradictions, topic shifts, old memories, changed preferences and large
volumes of irrelevant content. Only the most promising architecture moves to
a new real evaluation afterwards.

## Data flow (strict separation)

```text
real usage ──────> shadow-v2 logs ──────> P3v4 validation (current window)

synthetic generator ─> sandbox ─> candidate screening ─> best candidate
                                                        │
                         (after the current window closes)
                                                        v
                                      new real window, starting from zero
                                      (its own pre-registration)
```

## Rules

1. **The current window (`admission-shadow-v2`) continues untouched.** Its
   200 recalls, 15 sessions, 21 days and 40 judgments must all be real.
2. **Synthetic data never enters the checker counts, the logs, or the
   analysis** of the real window. No mixing, ever.
3. **No new candidate replaces P3v4 during this window.**
4. The synthetic lab is fully separate: its own fixtures under
   `eval/fixtures/`, its own pre-registration per experiment, research code
   under `eval/`; it never touches the product recall path or defaults.
5. A promising synthetic candidate is **not promoted immediately**; it is
   prepared for a future real window that starts from zero after the current
   one closes (own pre-registration, same freeze discipline).
6. The lab can run in parallel with the real window without contaminating
   it; this is the whole point of the two tracks.

## Lab candidates (from the ideas record)

To be screened in order, per `docs/EVIDENCE_PORTFOLIO_IDEAS.md`: typed
evidence portfolio with functional slots; versioned claims and supersession
graph; contradiction registry; retrieval planner; audit receipt. All under
the 4000-character budget, with availability **and** precision as joint
metrics, and P3v4 as the standing comparator.

## Why both tracks

Faster and scientifically stronger than either alone: the lab makes
invention cheap and selection strict; the real window provides the only
evidence that transfers to the product.
