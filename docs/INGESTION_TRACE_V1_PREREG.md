# ingestion-trace-v1 — pre-registration (temporal ingestion misses + metric fix)

Status: **frozen before execution**. Date: 2026-09-22. Track: synthetic lab.

Owner priority after `temporal-breadth-v1` (M0335): the four temporal
**ingestion misses** matter more than the delivery losses. For each case,
verify which basic facts exist at origin, which were preserved, and which
operation would be needed - separating an ingestion failure from a computed
answer over correctly ingested facts. In parallel, fix the phrase metric for
**abstention golds** (u3b-41 must not count as a delivery loss), and diagnose
the u3a-17 delivery residual. Deterministic, no LLM; windows stay OFF.

## 1. Cases

- Ingestion misses: u3a-14 (`3 weeks`), u3a-21 (`10 years`),
  u3b-30 (`4 years and 9 months`), u3b-40 (`12 days ago...`).
- Metric fix: u3b-41 (abstention gold).
- Delivery residual: u3a-17 (`over a year`).

## 2. Declared probes and classification

For each ingestion-miss case, probes are searched in the required records'
full texts (origin) and in the delivered arm contexts:

- **date components**: distinct date tokens (ISO, year, month name);
- **duration components**: distinct temporal phrases (from the phrase
  metric).

Declared classification:

- **`computation_needed`**: at least two distinct components (dates and/or
  durations) are present in ingestion - the answer is an interval/sum
  derivable from ingested facts, not an ingestion loss;
- **`ingestion_loss`**: fewer than two components present;
- plus flag **`question_date_unavailable`** when the question asks a
  relative quantity (`ago`) and carries no date of its own (the reference
  date cannot come from the records).

For u3a-17 (delivery residual), the report records the gold phrase, its
presence per arm (W0/W1/W3/W5), the segment position in the record and the
distance to the best segment - diagnostic values only, no rule change.

## 3. Metric fix (declared)

`phrase_delivery_v1.check` gains **`abstention_aware=False`** (default keeps
historic behaviour byte-identical for existing reports). When True and the
gold matches the abstention patterns, the result is
`{"basis": "abstention", "applicable": False, "ok": True}` - abstention
golds are no longer counted as delivery losses. New experiments pass True;
existing recorded results are unchanged.

## 4. Gates

- **I1** every ingestion-miss case is classified (not `unclear`).
- **I2** the abstention metric fix behaves as declared on u3b-41 and leaves
  the default path untouched (regression checked on a phrase case).
- **I3** determinism; **I4** the report includes origin excerpts per case.

`all_pass` = I1-I4. Nothing is promoted; windows OFF.

## 5. Execution protocol

Harness `eval/ingestion_trace_v1.py`, outputs
`eval/results/ingestion_trace_v1/{report.json,report.md}`,
`tests/test_ingestion_trace_v1.py`, proof regenerated, one run, execution
record appended, committed.

## Execution record (2026-09-22)

Deterministic; gates I1-I4 **all true**; `all_pass` true.

| case | components (dates/durations) | classification |
|---|---|---|
| u3a-14 (`3 weeks`) | 1 date token / 2 durations | **computation_needed** |
| u3a-21 (`10 years`) | 5 / 5 | **computation_needed** |
| u3b-30 (`4y9m`) | 1 / 6 | **computation_needed** |
| u3b-40 (`12 days ago`) | 5 / 0 | **computation_needed** |

Interpretation (per case, declared probes):

- **None of the four is an ingestion loss.** The component facts are
  ingested; the answers are **intervals or sums over them** (dates between
  events, total years, employment span, days since a date). They belong to
  composition/answer-side computation, not to write-time or delivery.
- **u3b-40 caveat**: `question_date_unavailable` did not set because the
  question contains the issue month (`March`), which the date-token probe
  matched; the relative `ago` still needs a reference date the fixture does
  not carry. Recorded as a probe limitation, not re-fitted.
- **u3a-14 caveat**: only a month token plus two short durations are found;
  the exact two event dates are prose ("last week of May"-style). The
  component count clears the declared threshold, but the operation (interval)
  depends on dates that may still be under-specified - flagged for the
  record.

Residual **u3a-17** (`over a year`): the phrase is absent from **every**
arm including W0 - segment 106/213 of the record; no window selects it. This
is a payload-level coverage loss common to all policies, not a W3/W5 defect.
Named next step: mid-text phrase coverage (all phrase-bearing segments
within budget), same pattern as the money/temporal rules.

**Metric fix (u3b-41)**: default path unchanged (basis `atom_fallback`);
`abstention_aware=True` returns `basis="abstention"`, `applicable=False`,
`ok=True` - abstention golds no longer count as delivery losses. The
phrase-case regression check (u3a-22 under W5) stays `ok`.

Nothing promoted; windows OFF.

## Addendum A (2026-09-22) — the two open caveats, inspected

Deterministic prose inspection (`eval/ingestion_caveats_v1.py`), no LLM.

- **u3a-14**: no prose dates exist in the required records; the two event
  dates are available as **record metadata**, and the payload headers carry
  them: M0032 `2023-02-26`, M0045 `2023-03-21` (interval **23 days ~= 3
  weeks**, the gold). The previously unidentified component is therefore the
  **header date of the second event** - delivered, computable. The
  `computation_needed` classification stands, with the operation named:
  interval between two delivered header dates.
- **u3b-40**: the fixture has **no question-date field and no date token in
  the question**; the only delivered date is the W1 header `2023-03-20`.
  The relative `ago` reference date is not available anywhere in the
  material, so the answer cannot be computed from the payload - an
  answer-side/harness limitation, not a model failure. `question_date_unavailable`
  is confirmed by inspection (the earlier automatic flag missed it because the
  issue month matched the token probe).

Both classifications now carry named, verifiable components. Nothing else in
the record changes.
