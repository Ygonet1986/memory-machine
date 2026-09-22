# admission-causal-v2 (exploratory)

- cases: 40 · gold: 60 · slot used: 20

| policy | availability | precision | delivered | max items | undue (absent) |
|---|---:|---:|---:|---:|---:|
| B | 0.667 | 0.800 | 50 | 2 | 0.000 |
| S | 1.000 | 0.857 | 70 | 2 | 0.000 |

requirements: {"R1_factual_clean": true, "R2_absent_clean": true, "R3_budget": true, "R4_determinism": true, "all_pass": true}

## Per-scenario availability

| scenario | B | S |
|---|---:|---:|
| causal_absent | 1.00 | 1.00 |
| causal_buried | 0.50 | 1.00 |
| causal_chain | 0.50 | 1.00 |
| factual_control | 1.00 | 1.00 |
