# Lifecycle v2 — coverage-trigger variants (frozen pre-registration)

- probes: 19 · needing fallback: 4 · thresholds: {"coverage": 0.5, "min_token_len": 4, "top_k": 5}

| variant | trigger quality | fallback rate | recovery | precision@k | combined recall |
|---|---:|---:|---:|---:|---:|
| T1 | 0.250 | 0.053 | 0.250 | 1.000 | 0.857 |
| T2 | 0.750 | 0.263 | 0.750 | 0.750 | 0.952 |
| T3 | 0.750 | 0.263 | 0.750 | 0.750 | 0.952 |

gates: {"H2-1_trigger_quality": true, "H2-2_recovery": false, "H2-3_precision": false, "H2-4_combined_recall": true, "H2-5_selective": true, "all_pass": false}

## Per probe (T3)

| probe | coverage | T1 | T3 fired | needed | found |
|---|---:|---|---|---|---|
| P01 | 0.57 | False | False | — | — |
| P02 | 0.60 | False | False | — | — |
| P03 | 0.50 | False | False | — | — |
| P04 | 0.40 | False | True | — | — |
| P05 | 0.25 | False | True | ['M0012'] | ['M0012'] |
| P06 | 1.00 | False | False | — | — |
| P07 | 0.20 | False | True | ['M0014'] | ['M0014'] |
| P08 | 0.57 | False | False | — | — |
| P09 | 0.60 | False | False | — | — |
| P10 | 0.67 | False | False | — | — |
| P11 | 0.50 | False | False | — | — |
| P12 | 0.75 | False | False | — | — |
| P13 | 0.00 | True | True | ['M0026'] | ['M0026'] |
| P14 | 0.75 | False | False | — | — |
| P15 | 0.67 | False | False | — | — |
| P16 | 0.50 | False | False | — | — |
| P17 | 0.67 | False | False | — | — |
| P18 | 0.29 | False | True | — | — |
| P20 | 0.60 | False | False | ['M0029'] | — |
