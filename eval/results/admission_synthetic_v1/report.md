# admission-synthetic-v1

- cases: 100 · gold occurrences: 100

| policy | availability | precision | delivered | mean chars | abstention (S7) |
|---|---:|---:|---:|---:|---:|
| P0 | 0.500 | 0.500 | 100 | 80 | 0.000 |
| P1 | 0.900 | 0.310 | 290 | 204 | 0.000 |
| P2 | 0.600 | 0.429 | 140 | 107 | 0.000 |
| P3 | 0.700 | 0.500 | 140 | 108 | 1.000 |

gates: {"G1_availability": false, "G2_precision": false, "G3_dual_frontier": true, "G4_abstention": true, "G5_scenario_floor": false, "G6_determinism": true, "all_pass": false}

## Per-scenario availability (P3)

| scenario | P0 | P1 | P2 | P3 |
|---|---:|---:|---:|---:|
| corrected | 0.00 | 0.00 | 0.00 | 0.00 |
| distractor_volume | 1.00 | 1.00 | 1.00 | 1.00 |
| easy_single | 1.00 | 1.00 | 1.00 | 1.00 |
| long_specific | 1.00 | 1.00 | 1.00 | 1.00 |
| multi_memory | 0.50 | 1.00 | 0.50 | 0.50 |
| near_duplicate | 0.00 | 1.00 | 1.00 | 0.00 |
| no_answer | — | — | — | — |
| old_vs_recent | 0.00 | 1.00 | 0.00 | 1.00 |
| shared_subject | 1.00 | 1.00 | 1.00 | 1.00 |
| short_ambiguous | 0.00 | 1.00 | 0.00 | 1.00 |

## P3 decisions on hard scenarios

| case | scenario | delivered | gold |
|---|---|---|---|
| S3-01 | corrected | S3-01-R01 | S3-01-R03 |
| S3-02 | corrected | S3-02-R01 | S3-02-R03 |
| S3-03 | corrected | S3-03-R01 | S3-03-R03 |
| S3-04 | corrected | S3-04-R01 | S3-04-R03 |
| S3-05 | corrected | S3-05-R01 | S3-05-R03 |
| S3-06 | corrected | S3-06-R01 | S3-06-R03 |
| S3-07 | corrected | S3-07-R01 | S3-07-R03 |
| S3-08 | corrected | S3-08-R01 | S3-08-R03 |
| S3-09 | corrected | S3-09-R01 | S3-09-R03 |
| S3-10 | corrected | S3-10-R01 | S3-10-R03 |
| S5-01 | short_ambiguous | S5-01-R03,S5-01-R06,S5-01-R01,S5-01-R02,S5-01-R04 | S5-01-R03 |
| S5-02 | short_ambiguous | S5-02-R03,S5-02-R06,S5-02-R01,S5-02-R02,S5-02-R04 | S5-02-R03 |
| S5-03 | short_ambiguous | S5-03-R03,S5-03-R06,S5-03-R01,S5-03-R02,S5-03-R04 | S5-03-R03 |
| S5-04 | short_ambiguous | S5-04-R03,S5-04-R06,S5-04-R01,S5-04-R02,S5-04-R04 | S5-04-R03 |
| S5-05 | short_ambiguous | S5-05-R03,S5-05-R06,S5-05-R01,S5-05-R02,S5-05-R04 | S5-05-R03 |
| S5-06 | short_ambiguous | S5-06-R03,S5-06-R06,S5-06-R01,S5-06-R02,S5-06-R04 | S5-06-R03 |
| S5-07 | short_ambiguous | S5-07-R03,S5-07-R06,S5-07-R01,S5-07-R02,S5-07-R04 | S5-07-R03 |
| S5-08 | short_ambiguous | S5-08-R03,S5-08-R06,S5-08-R01,S5-08-R02,S5-08-R04 | S5-08-R03 |
| S5-09 | short_ambiguous | S5-09-R03,S5-09-R06,S5-09-R01,S5-09-R02,S5-09-R04 | S5-09-R03 |
| S5-10 | short_ambiguous | S5-10-R03,S5-10-R06,S5-10-R01,S5-10-R02,S5-10-R04 | S5-10-R03 |
| S7-01 | no_answer | — | — |
| S7-02 | no_answer | — | — |
| S7-03 | no_answer | — | — |
| S7-04 | no_answer | — | — |
| S7-05 | no_answer | — | — |
| S7-06 | no_answer | — | — |
| S7-07 | no_answer | — | — |
| S7-08 | no_answer | — | — |
| S7-09 | no_answer | — | — |
| S7-10 | no_answer | — | — |
| S8-01 | old_vs_recent | S8-01-R02,S8-01-R01 | S8-01-R02 |
| S8-02 | old_vs_recent | S8-02-R02,S8-02-R01 | S8-02-R02 |
| S8-03 | old_vs_recent | S8-03-R02,S8-03-R01 | S8-03-R02 |
| S8-04 | old_vs_recent | S8-04-R02,S8-04-R01 | S8-04-R02 |
| S8-05 | old_vs_recent | S8-05-R02,S8-05-R01 | S8-05-R02 |
| S8-06 | old_vs_recent | S8-06-R02,S8-06-R01 | S8-06-R02 |
| S8-07 | old_vs_recent | S8-07-R02,S8-07-R01 | S8-07-R02 |
| S8-08 | old_vs_recent | S8-08-R02,S8-08-R01 | S8-08-R02 |
| S8-09 | old_vs_recent | S8-09-R02,S8-09-R01 | S8-09-R02 |
| S8-10 | old_vs_recent | S8-10-R02,S8-10-R01 | S8-10-R02 |
| S9-01 | multi_memory | S9-01-R02 | S9-01-R01,S9-01-R02 |
| S9-02 | multi_memory | S9-02-R02 | S9-02-R01,S9-02-R02 |
| S9-03 | multi_memory | S9-03-R02 | S9-03-R01,S9-03-R02 |
| S9-04 | multi_memory | S9-04-R02 | S9-04-R01,S9-04-R02 |
| S9-05 | multi_memory | S9-05-R02 | S9-05-R01,S9-05-R02 |
| S9-06 | multi_memory | S9-06-R02 | S9-06-R01,S9-06-R02 |
| S9-07 | multi_memory | S9-07-R02 | S9-07-R01,S9-07-R02 |
| S9-08 | multi_memory | S9-08-R02 | S9-08-R01,S9-08-R02 |
| S9-09 | multi_memory | S9-09-R02 | S9-09-R01,S9-09-R02 |
| S9-10 | multi_memory | S9-10-R02 | S9-10-R01,S9-10-R02 |
