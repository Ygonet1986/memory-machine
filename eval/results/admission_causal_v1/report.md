# admission-causal-v1 (lab)

- cases: 40 · gold occurrences: 60

| policy | availability | precision | delivered | undue (absent) |
|---|---:|---:|---:|---:|
| B | 0.667 | 0.800 | 50 | 0.000 |
| K | 0.667 | 0.800 | 50 | 0.000 |
| K-abl | 0.667 | 0.800 | 50 | 0.000 |

gates: {"G1_availability": false, "G2_precision": true, "G3_causal_wins": false, "G4_factual_unharmed": true, "G5_negatives": true, "G6_gating_matters": true, "G7_determinism": true, "all_pass": false}

## Per-scenario availability

| scenario | B | K | K-abl |
|---|---:|---:|---:|
| causal_absent | 1.00 | 1.00 | 1.00 |
| causal_buried | 0.50 | 0.50 | 0.50 |
| causal_chain | 0.50 | 0.50 | 0.50 |
| factual_control | 1.00 | 1.00 | 1.00 |
