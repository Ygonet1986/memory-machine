# admission-synthetic-v2

- cases: 100 · gold occurrences: 100

| policy | availability | precision | delivered | mean chars | abstention (S7) |
|---|---:|---:|---:|---:|---:|
| P0 | 0.500 | 0.500 | 100 | 80 | 0.000 |
| P1 | 0.900 | 0.310 | 290 | 204 | 0.000 |
| P2 | 0.600 | 0.429 | 140 | 107 | 0.000 |
| P3v1 | 0.700 | 0.500 | 140 | 108 | 1.000 |
| P3v2 | 1.000 | 0.455 | 220 | 169 | 1.000 |

gates: {"G1_availability": true, "G2_precision": false, "G3_dual_frontier": true, "G4_abstention": true, "G5_scenario_floor": true, "G6_determinism": true, "G7_beats_v1": false, "all_pass": false}

## Per-scenario availability

| scenario | P1 | P2 | P3v1 | P3v2 |
|---|---:|---:|---:|---:|
| corrected | 0.00 | 0.00 | 0.00 | 1.00 |
| distractor_volume | 1.00 | 1.00 | 1.00 | 1.00 |
| easy_single | 1.00 | 1.00 | 1.00 | 1.00 |
| long_specific | 1.00 | 1.00 | 1.00 | 1.00 |
| multi_memory | 1.00 | 0.50 | 0.50 | 1.00 |
| near_duplicate | 1.00 | 1.00 | 0.00 | 1.00 |
| no_answer | — | — | — | — |
| old_vs_recent | 1.00 | 0.00 | 1.00 | 1.00 |
| shared_subject | 1.00 | 1.00 | 1.00 | 1.00 |
| short_ambiguous | 1.00 | 0.00 | 1.00 | 1.00 |
