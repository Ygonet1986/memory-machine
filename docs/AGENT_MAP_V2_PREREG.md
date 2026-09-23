# agent-map-v2 — pre-registration (evidence-seeking stopping rule)

Status: **frozen before execution**. Date: 2026-09-23. Track: synthetic lab.

New hypothesis required after `agent-map-v1` (M0368): the token-coverage
stop (tau=0.5) failed the decisive no-loss gate (coverage 0.7469). This
experiment tests an **evidence-seeking** stopping rule: a **score margin**
between candidate partitions plus a **bounded tape rescue**, with no
threshold re-fit of the failed tau (that rule is kept only as a reference
arm).

## 1. Dry-check rationale (design-time, disclosed)

Deterministic checks on the frozen 27-case fixture (no results recorded):
margin-only 0.5 x best (cap 3) reaches coverage **0.8519** with **39**
consulted partitions; adding the bounded rescue (partitions of the tape's
top-3 records) restores **1.0000** at **54** (i.e., every partition with
K=2). The margin itself failed the no-loss gate alone; the rescue is what
restores it - declared primary accordingly.

## 2. Arms (map = verifiable pointer index, unchanged from v1)

- **B0 all** (baseline).
- **B1 map top-1** (reference; 0.6728/27 in v1).
- **B2 primary: margin + bounded rescue** - map top-1, plus every partition
  hosting a record with score >= 0.5 x the global best, plus the partitions
  hosting the tape's top-3 records; cap at 3 partitions (when the cap binds,
  keep the highest map scores; ties by partition order).
- **B3 variant: margin only** - map top-1 plus partitions hosting records
  >= 0.5 x best, cap 3 (**no rescue**).
- **B4 reference: tau=0.5 coverage stop** (the failed v1 rule, re-run for
  continuity; 0.7469/29).

## 3. Gates (B2)

- **M1** no case lost: per-case coverage(B2) == coverage(B0).
- **M2** economy: total consulted(B2) < total consulted(B0). Declared
  expectation: with K=2 this **fails** (the rescue spans both partitions);
  it is the scope-limited gate, not a re-fit target.
- **M4** determinism. **M5** map pointers present.

`all_pass` = M1, M2, M4, M5. Variant/reference coverages are reported, not
gated. No promotion; windows OFF; the shadow window is untouched; the
K=2-vs-4-groups distinction is restated in the record.

## 4. Execution protocol

Harness `eval/agent_map_v2.py` (reuses `agent_map_v1` helpers and the frozen
fixture); outputs `eval/results/agent_map_v2/`; `tests/test_agent_map_v2.py`;
proof regenerated; execution record appended; committed.

## Execution record (2026-09-23)

Deterministic, 27 cases.

| arm | routing coverage | consulted partitions |
|---|---:|---:|
| B0 all | 1.0000 | 54 |
| B1 map top-1 | 0.6728 | 27 |
| **B2 margin 0.5 + rescue (primary)** | **1.0000** | 54 |
| B3 margin only | 0.8519 | 39 |
| B4 tau=0.5 coverage (v1 rule) | 0.7469 | 29 |

Gates: **M1 true** (the evidence-seeking rule restores the no-loss gate the
token-coverage stop failed); **M2 false** (with K=2 the rescue spans both
partitions, so consultations equal the all-agents arm); M4 true; M5 true;
`all_pass` false.

Findings:

- **Evidence-seeking works; economy remains unmeasurable at K=2**: the
  margin+rescue rule reaches coverage 1.0000 - fixing the failure of
  `agent-map-v1` - but consults all partitions on a two-partition fixture.
  This is the declared scope limit, not a threshold to re-fit.
- **Margin-only trades better than token coverage**: 0.8519/39 vs
  0.7469/29 (v1) - a real improvement in the trade-off, still insufficient
  alone.
- **The decisive economy question stays with track S** on the four real
  groups at `met: true` (companion addendum; S1 mirrors M1, S2 mirrors M2).
- Nothing promoted; windows OFF; shadow untouched; the K=2-vs-4-groups
  distinction is explicit in the report.
