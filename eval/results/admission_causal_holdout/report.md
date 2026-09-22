# admission-causal holdout (single evaluation)

- cases: 40 · gold: 62 · slot used: 22

| policy | availability | precision | delivered | max items | undue (absent) |
|---|---:|---:|---:|---:|---:|
| B | 0.645 | 0.833 | 48 | 2 | 0.000 |
| S | 1.000 | 0.886 | 70 | 2 | 0.000 |

gates: {"H1_availability": true, "H2_precision": true, "H3_factual_control": true, "H4_absence": true, "H5_budget": true, "H6_determinism": true}
all_pass: True

## Per-scenario availability

| scenario | B | S |
|---|---:|---:|
| causal_absent | 1.00 | 1.00 |
| causal_buried | 0.50 | 1.00 |
| causal_chain | 0.50 | 1.00 |
| factual_control | 1.00 | 1.00 |
