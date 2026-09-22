# phrase-coverage-v1 — pre-registration (u3a-17 mid-text phrase coverage)

Status: **frozen before execution**. Date: 2026-09-22. Track: synthetic lab.

Owner direction after `ingestion-trace-v1` (M0337): freeze the current window
selection and add **only mid-text phrase coverage** under the same budget.
Primary gate: deliver `over a year` (u3a-17) without removing facts that
already arrived; the answer is measured separately. Windows stay OFF.

## 1. Policy W6 (single declared delta over W5)

W5 unchanged (source hash pinned) except: **every segment containing a
phrase** (any unit from the phrase metric: temporal, money, size) is included
in distance order to the best segment, uncapped, before the coverage fill,
bounded by the same allocation. This generalizes the temporal/money anchor
rules to any phrase-bearing segment.

## 2. Cases

Target: **u3a-17** (`over a year`, phrase `1year`, segment 106/213, absent
from W0/W1/W3/W5). Controls: the tracked cases u3a-12, u3a-19, u3a-22,
u3b-27 (no regression allowed), plus budgets against W0.

## 3. Gates

- **P1** target fixed: phrase `1year` present under W6 (absent under W5).
- **P2** no removals: on every control case, anything present under W5 stays
  present under W6 (phrase or atom basis); budget per case <= W0 length.
- **P3** answer gate (N=3, same answerer, blind judge, u3a-17, W5 vs W6,
  12 calls): score(W6) >= score(W5) - 0.05 - measured and reported
  separately from the delivery gate.
- **P4** determinism; **P5** infra failures <= 20%.

`all_pass` = P1-P5. Any failure: report, no re-fit, windows OFF.

## 4. Expected readings (declared)

P1 passes (segment 106 contains a phrase). Risk declared: including all
phrase segments may displace coverage-filled segments in some records; P2
guards the tracked cases. If P3 shows no answer movement, the fix is
delivery-level only - recorded.

## 5. Execution protocol

Harness `eval/phrase_coverage_v1.py` (`--skip-llm` for delivery only),
outputs `eval/results/phrase_coverage_v1/{report.json,report.md}`,
`tests/test_phrase_coverage_v1.py`, proof regenerated, execution record
appended, committed.

## Execution record (2026-09-22)

Delivery (deterministic) and answer gate (N=3 on u3a-17; contexts identical
between arms, see cause; 12 calls, 0 failures).

| case | arm | gold | present |
|---|---|---|---|
| u3a-17 | W5 | `1year` | **MISS** |
| u3a-17 | **W6** | `1year` | **MISS** |
| u3a-12 / u3a-22 / u3b-27 | W5/W6 | as before | unchanged |
| u3a-19 | W5 | `200$` | MISS |
| u3a-19 | **W6** | `200$` | **ok** (side observation) |

| arm | u3a-17 verdicts | score |
|---|---|---|
| W5 | incorrect x3 | 0.00 |
| W6 | incorrect x3 | 0.00 |

Gates: P1 **false** (target not fixed); P2 **true** (no removals on
controls); P3 true (no regression, but both arms at 0.00 on identical
contexts); P4/P5/P6 true; `all_pass` false.

**Root cause, named and not re-fitted**: u3a-17's item has
`room = frozen_body - summary - 1 = **-301**` - the record's summary is
longer than the delivered body, so every arm takes the `room < 120` guard and
**no window runs at all** (W5 and W6 contexts are byte-identical to W0).
The phrase lives in segment 106/213, beyond the head truncation. This is not
a selection-rule failure: delivering `over a year` requires a **contract-level
decision** - either allow trading summary characters for a phrase segment when
`summary >= allocation`, or accept the item as contract-limited. The locked
payload decision preserves the summary, so no rule change is made here.

Side observation (recorded, not promoted): W6's generic phrase coverage
delivers u3a-19's `$200` - the same class W4 targets; W4 remains independent
and exploratory.

Nothing promoted; windows OFF. Open decision: whether to pre-register a
summary-trade contract variant for the u3a-17 class, or close it as a
contract limitation.
