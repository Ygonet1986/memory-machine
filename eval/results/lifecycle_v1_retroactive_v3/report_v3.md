# Lifecycle v3 — IDF coverage + candidacy margin

- thresholds: {"coverage_idf": 0.5, "margin": 0.5, "min_token_len": 4, "top_k": 5}

| variant | trigger quality | fallback rate | recovery | precision@k | combined recall |
|---|---:|---:|---:|---:|---:|
| V3-A | 0.750 | 0.210 | 0.750 | 1.000 | 0.952 |
| V3-B | 0.750 | 0.210 | 0.750 | 1.000 | 0.952 |
| V3-C | 0.750 | 0.263 | 0.750 | 0.750 | 0.952 |
| (v2 T3) | 0.750 | 0.263 | 0.750 | 0.750 | 0.952 |

gates: {"H3-1_trigger_quality": true, "H3-2_recovery": false, "H3-3_precision": true, "H3-4_combined_recall": true, "H3-5_selective": true, "H3-6_no_regression": true, "all_pass": false}

## Per probe (primary V3-B)

| probe | cov_idf | cov_plain | T fired | needed | delivered | found |
|---|---:|---:|---|---|---|---|
| P01 | 0.73 | 0.57 | False | — | — | — |
| P02 | 0.82 | 0.60 | False | — | — | — |
| P03 | 0.74 | 0.50 | False | — | — | — |
| P04 | 0.65 | 0.40 | False | — | — | — |
| P05 | 0.30 | 0.25 | True | ['M0012'] | ['M0012'] | ['M0012'] |
| P06 | 1.00 | 1.00 | False | — | — | — |
| P07 | 0.30 | 0.20 | True | ['M0014'] | ['M0014'] | ['M0014'] |
| P08 | 0.78 | 0.57 | False | — | — | — |
| P09 | 0.79 | 0.60 | False | — | — | — |
| P10 | 0.84 | 0.67 | False | — | — | — |
| P11 | 0.76 | 0.50 | False | — | — | — |
| P12 | 0.91 | 0.75 | False | — | — | — |
| P13 | 0.00 | 0.00 | True | ['M0026'] | ['M0026'] | ['M0026'] |
| P14 | 0.91 | 0.75 | False | — | — | — |
| P15 | 0.85 | 0.67 | False | — | — | — |
| P16 | 0.76 | 0.50 | False | — | — | — |
| P17 | 0.73 | 0.67 | False | — | — | — |
| P18 | 0.39 | 0.29 | True | — | — | — |
| P20 | 0.56 | 0.60 | False | ['M0029'] | — | — |
