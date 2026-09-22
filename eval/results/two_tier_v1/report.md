# Two-tier retrieval v1

- fixture: /Users/igorcoutrimlacerda/memory-machine/eval/fixtures/lifecycle_v1
- thresholds: {"comparative_factor": 1.25, "coverage_idf": 0.5, "margin": 0.5, "min_token_len": 4, "rrf_k": 60, "top_k": 5}
- probes: 19 · required occurrences: 21 · calls added: 0

| arm | availability | precision@k | delivered | found | mean chars | p50 ms | p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|
| T2-A | 0.809 | 0.436 | 39 | 17 | 151 | 0.036 | 0.059 |
| T2-B | 0.952 | 0.476 | 42 | 20 | 160 | 0.097 | 0.149 |
| T2-C | 1.000 | 0.512 | 41 | 21 | 148 | 0.050 | 0.081 |
| T2-CRRF | 1.000 | 0.296 | 71 | 21 | 251 | 0.054 | 0.084 |
| T2-U | 1.000 | 0.525 | 40 | 21 | 145 | 0.057 | 0.087 |

gates: {"H2T-1_availability": true, "H2T-2_precision": false, "H2T-3_budget": true, "H2T-4_no_regression_vs_unfiltered": true, "H2T-5_determinism": true, "all_pass": false}
determinism: True

## Per probe

| probe | required | T2-A | T2-B | T2-C | T2-CRRF | T2-U |
|---|---|---|---|---|---|---|
| P01 | M0003 | M0003 | M0003 | M0003 | M0003 | M0003 |
| P02 | M0008 | M0008 | M0008 | M0008 | M0008 | M0008 |
| P03 | M0010 | M0010 | M0010 | M0010 | M0010 | M0010 |
| P04 | M0011 | M0011 | M0011 | M0011 | M0011 | M0011 |
| P05 | M0012 | - | M0012 | M0012 | M0012 | M0012 |
| P06 | M0013 | M0013 | M0013 | M0013 | M0013 | M0013 |
| P07 | M0014 | - | M0014 | M0014 | M0014 | M0014 |
| P08 | M0006 | M0006 | M0006 | M0006 | M0006 | M0006 |
| P09 | M0017 | M0017 | M0017 | M0017 | M0017 | M0017 |
| P10 | M0019 | M0019 | M0019 | M0019 | M0019 | M0019 |
| P11 | M0021 | M0021 | M0021 | M0021 | M0021 | M0021 |
| P12 | M0022 | M0022 | M0022 | M0022 | M0022 | M0022 |
| P13 | M0026 | - | M0026 | M0026 | M0026 | M0026 |
| P14 | M0027 | M0027 | M0027 | M0027 | M0027 | M0027 |
| P15 | M0006,M0030 | M0030,M0006 | M0030,M0006 | M0030,M0006 | M0030,M0006 | M0030,M0006 |
| P16 | M0031 | M0031 | M0031 | M0031 | M0031 | M0031 |
| P17 | M0013 | M0013 | M0013 | M0013 | M0013 | M0013 |
| P18 | M0003,M0017 | M0003,M0017 | M0003,M0017 | M0003,M0017 | M0003,M0017 | M0003,M0017 |
| P20 | M0029 | - | - | M0029 | M0029 | M0029 |
