# phrase-delivery-v1 — pre-registration (item 3 follow-up, correction 1)

Status: **frozen before execution**. Date: 2026-09-22. Track: synthetic lab.

First of the two named corrections from `diagnostic-trace-v1` (M0328): make
the delivered **phrase** measurable, so the u3a-22 loss (gold `two weeks`,
W3 incorrect 3/3 while W0/W1 are correct 3/3) becomes visible at the
delivery stage. Payloads and answerer stay frozen; no new LLM calls: the
answer gate reuses the recorded N=3 trace verdicts on byte-identical
contexts (hashes compared).

## 1. Phrase metric (declared)

`phrases(text)` over normalized text (lowercase, thousands separators
removed):

- digit + unit: `(\d+(?:[.,]\d+)?)\s*(days?|weeks?|months?|years?|hours?|minutes?|gb|mb|kb|tb|%|percent|dollars?|usd)`;
- number word + unit: one..twelve (and a/an) + the same units;
- currency: `\$\s*(\d+(?:[.,]\d+)?)` -> unit `$`.

A gold phrase is **present** in a span when a span phrase has the same
canonical value and unit. Golds without any phrase fall back to the existing
atom check (`item_fact_atoms` + `atom_present`), so the metric is total: it
never becomes vacuous.

## 2. Validity gates (metric verification, not policy promotion)

- **P1 detects the known loss**: u3a-22: phrase(`two weeks`) present in W0
  and W1, **absent in W3**, agreeing with the recorded answers (W0/W1
  correct 3/3; W3 incorrect 3/3).
- **P2 no false alarms on controls**: u3a-12 (`16GB`): phrase present in all
  three arms; u3b-27 (no phrase gold): fallback check present in all three
  arms.
- **P3 also localizes u3a-19**: `$200` absent from all three arms (the known
  mid-text truncation), consistent with `diagnostic-trace-v1`.
- **P4 context hashes equal** to the ones recorded in
  `eval/results/diagnostic_trace_v1/trace.jsonl` (same frozen payloads).
- **P5 determinism**.

## 3. Stop rules

Metric-only experiment: nothing is promoted, no policy changes. If P1 fails
(the metric does not see the loss), the metric is wrong and the next step is
to fix the metric, not the policy. `all_pass` requires P1-P5.

## 4. Execution protocol

Harness `eval/phrase_delivery_v1.py`, outputs
`eval/results/phrase_delivery_v1/{report.json,report.md}`,
`tests/test_phrase_delivery_v1.py`, proof regenerated, execution record
appended, committed.

## Execution record (2026-09-22)

Deterministic run; gates P1-P5 **all true**; `all_pass` true.

| case | arm | basis | gold phrase | present | recorded answers (N=3) |
|---|---|---|---|---|---|
| u3a-12 | W0/W1/W3 | phrase | `16gb` | ok | correct x3 |
| u3a-19 | W0/W1/W3 | phrase | `200$` | **MISS** | incorrect (unstable) |
| u3a-22 | W0/W1 | phrase | `2week` | ok | correct x3 |
| u3a-22 | **W3** | phrase | `2week` | **MISS** | **incorrect x3** |
| u3b-27 | W0/W1/W3 | atom_fallback | (none) | ok | mixed (noise) |

Findings:

- **The phrase metric makes the u3a-22 loss measurable at the delivery
  stage**, in exact agreement with the recorded repeated answers: the
  `two weeks` phrase is delivered by W0/W1 and missing from W3. The previous
  atom metric was vacuous for this gold.
- The same metric **also localizes u3a-19** (`$200` missing in every arm) and
  produces **no false alarms** on the controls (`16GB` present everywhere;
  the phrase-less gold falls back to the atom check).
- Context hashes match `diagnostic-trace-v1` exactly: the answer gate is the
  recorded N=3 evidence on byte-identical payloads, with no new LLM calls.

No policy changed; nothing promoted. This unblocks correction 2 (central
numeral inclusion for the u3a-19 class) with a delivery metric that can
verify it, and a phrase check for the u3a-22 class.
