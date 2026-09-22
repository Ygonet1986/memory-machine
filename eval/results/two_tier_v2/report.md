# Two-tier retrieval v2 — bounded candidacy

- fixture: /Users/igorcoutrimlacerda/memory-machine/eval/fixtures/lifecycle_v1
- thresholds: {"margin_primary": 0.9, "margin_variant": 0.7, "top_k": 5}
- probes: 19 · required occurrences: 21 · calls added: 0

| arm | availability | precision@k | delivered | found | mean chars | p50 ms | p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|
| T2v2-P | 0.905 | 0.826 | 23 | 19 | 86 | 0.051 | 0.080 |
| T2v2-B2 | 0.952 | 0.556 | 36 | 20 | 122 | 0.051 | 0.080 |
| T2v2-M70 | 0.905 | 0.679 | 28 | 19 | 104 | 0.051 | 0.080 |
| T2v2-U90 | 0.905 | 0.760 | 25 | 19 | 92 | 0.057 | 0.089 |
| T2v2-A90 | 0.714 | 0.652 | 23 | 15 | 87 | 0.036 | 0.059 |

gates: {"H6-1_availability": false, "H6-2_precision": true, "H6-3_budget": true, "H6-4_no_regression_vs_unfiltered": true, "H6-5_determinism": true, "all_pass": false}
determinism: True

## Sensitivity (combined index; descriptive, not gating)

| margin | availability | precision@k |
|---|---:|---:|
| 0.50 | 1.000 | 0.512 |
| 0.70 | 0.905 | 0.679 |
| 0.90 | 0.905 | 0.826 |
| 1.00 | 0.857 | 0.947 |

| budget | availability | precision@k |
|---|---:|---:|
| top-1 | 0.857 | 0.947 |
| top-2 | 0.952 | 0.556 |
| top-3 | 1.000 | 0.420 |
