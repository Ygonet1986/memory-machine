# admission-portfolio-v1 (lab)

- cases: 80 · gold occurrences: 110

| policy | availability | precision | delivered | max/case | abstention |
|---|---:|---:|---:|---:|---:|
| P1 | 0.818 | 0.562 | 160 | 5 | 0.000 |
| P2 | 0.746 | 0.578 | 142 | 5 | 0.000 |
| P3v4 | 0.909 | 0.833 | 120 | 2 | 0.000 |
| P4-abl | 0.909 | 0.714 | 140 | 3 | 0.000 |
| P4 | 0.909 | 0.714 | 140 | 3 | 0.000 |

gates: {"G1_availability": true, "G2_precision": true, "G3_beats_p3v4": false, "G4_targeted_wins": false, "G5_slots_are_the_cause": false, "G6_cap_and_budget": true, "G7_determinism": true, "all_pass": false}

## Per-scenario availability

| scenario | P3v4 | P4-abl | P4 |
|---|---:|---:|---:|
| contradiction | 1.00 | 1.00 | 1.00 |
| current_state | 1.00 | 1.00 | 1.00 |
| distractor_volume | 1.00 | 1.00 | 1.00 |
| multi_memory | 1.00 | 1.00 | 1.00 |
| no_answer | — | — | — |
| origin | 1.00 | 1.00 | 1.00 |
| related_context | 0.50 | 0.50 | 0.50 |
| supersession | 1.00 | 1.00 | 1.00 |
