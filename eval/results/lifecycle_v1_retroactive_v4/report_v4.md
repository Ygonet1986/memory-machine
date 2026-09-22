# Lifecycle v4 — comparative coverage signal

- thresholds: {"comparative_factor": 1.25, "coverage_idf": 0.5, "margin": 0.5, "min_token_len": 4, "top_k": 5}
- comparative diagnostics: {"comparative_fires": 3, "extra_irrelevant": 0, "extra_recovered": 0, "extra_triggers_vs_v3": 0}

| variant | trigger quality | fallback rate | recovery | precision@k | combined recall |
|---|---:|---:|---:|---:|---:|
| V4-A | 0.750 | 0.210 | 0.750 | 1.000 | 0.952 |
| V4-B | 0.750 | 0.210 | 0.750 | 1.000 | 0.952 |
| V4-C | 0.750 | 0.158 | 0.750 | 1.000 | 0.952 |
| (v3 B) | 0.750 | 0.210 | 0.750 | 1.000 | 0.952 |

gates: {"H4-1_trigger_quality": true, "H4-2_recovery": false, "H4-3_precision": true, "H4-4_combined_recall": true, "H4-5_selective": true, "H4-6_no_regression": true, "all_pass": false}

## Per probe (primary V4-B)

| probe | cov_idf | A* | E* | comparative | T fired | needed | delivered | found |
|---|---:|---:|---:|---|---|---|---|---|
| P01 | 0.73 | 2.07 | 0.00 | False | False | — | — | — |
| P02 | 0.82 | 9.38 | 0.00 | False | False | — | — | — |
| P03 | 0.74 | 5.73 | 1.70 | False | False | — | — | — |
| P04 | 0.65 | 2.86 | 1.70 | False | False | — | — | — |
| P05 | 0.30 | 1.64 | 2.79 | True | True | ['M0012'] | ['M0012'] | ['M0012'] |
| P06 | 1.00 | 8.20 | 1.70 | False | False | — | — | — |
| P07 | 0.30 | 1.38 | 2.36 | True | True | ['M0014'] | ['M0014'] | ['M0014'] |
| P08 | 0.78 | 4.32 | 1.39 | False | False | — | — | — |
| P09 | 0.79 | 4.01 | 0.00 | False | False | — | — | — |
| P10 | 0.84 | 5.42 | 0.00 | False | False | — | — | — |
| P11 | 0.76 | 6.98 | 3.49 | False | False | — | — | — |
| P12 | 0.91 | 5.51 | 1.95 | False | False | — | — | — |
| P13 | 0.00 | 0.00 | 5.78 | True | True | ['M0026'] | ['M0026'] | ['M0026'] |
| P14 | 0.91 | 8.99 | 0.00 | False | False | — | — | — |
| P15 | 0.85 | 6.31 | 0.00 | False | False | — | — | — |
| P16 | 0.76 | 3.76 | 2.08 | False | False | — | — | — |
| P17 | 0.73 | 6.25 | 1.70 | False | False | — | — | — |
| P18 | 0.39 | 3.08 | 0.00 | False | True | — | — | — |
| P20 | 0.56 | 2.73 | 3.40 | False | False | ['M0029'] | — | — |
