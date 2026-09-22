# admission-synthetic-v4

- cases: 100 · gold occurrences: 100 · removed superseded (P3v4): 30

| policy | availability | precision | delivered | max/case | abstention (S7) |
|---|---:|---:|---:|---:|---:|
| P0 | 0.500 | 0.500 | 100 | 1 | 0.000 |
| P1 | 0.900 | 0.310 | 290 | 5 | 0.000 |
| P2 | 0.600 | 0.429 | 140 | 4 | 0.000 |
| P3v1 | 0.700 | 0.500 | 140 | 5 | 1.000 |
| P3v2 | 1.000 | 0.455 | 220 | 5 | 1.000 |
| P3v3 | 0.900 | 0.643 | 140 | 2 | 1.000 |
| P3v4 | 1.000 | 0.714 | 140 | 2 | 1.000 |

gates: {"G1_availability": true, "G2_precision": true, "G3_dual_frontier": true, "G4_abstention": true, "G5_scenario_floor": true, "G6_determinism": true, "G7_beats_v3": true, "G8_cap": true, "all_pass": true}

## Per-scenario (P3v4)

| scenario | availability | precision |
|---|---:|---:|
| corrected | 1.00 | 0.50 |
| distractor_volume | 1.00 | 1.00 |
| easy_single | 1.00 | 1.00 |
| long_specific | 1.00 | 0.50 |
| multi_memory | 1.00 | 1.00 |
| near_duplicate | 1.00 | 1.00 |
| no_answer | — | — |
| old_vs_recent | 1.00 | 1.00 |
| shared_subject | 1.00 | 0.50 |
| short_ambiguous | 1.00 | 0.50 |
