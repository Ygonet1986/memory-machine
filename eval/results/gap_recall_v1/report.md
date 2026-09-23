# gap-recall-v1

- complete: {"G0": 3, "G1": 15, "G2": 3, "G3": 15}
- recovered (gap cases): 12/12 ['C01', 'C02', 'C03', 'C04', 'C05', 'C06', 'C07', 'C08', 'C09', 'C10', 'C11', 'C12']
- budget: {"control_triggers": 0, "directed_extra_total": 12, "max_extra_per_case": 1, "mean_extra_per_case": 0.8}

| case | kind | G0 | G1 | G2 | G3 | extra |
|---|---|---|---|---|---|---|
| C01 | numeral | False | True | False | True | 1 |
| C02 | numeral | False | True | False | True | 1 |
| C03 | numeral | False | True | False | True | 1 |
| C04 | numeral | False | True | False | True | 1 |
| C05 | date | False | True | False | True | 1 |
| C06 | date | False | True | False | True | 1 |
| C07 | date | False | True | False | True | 1 |
| C08 | date | False | True | False | True | 1 |
| C09 | components | False | True | False | True | 1 |
| C10 | components | False | True | False | True | 1 |
| C11 | components | False | True | False | True | 1 |
| C12 | components | False | True | False | True | 1 |
| C13 | control | True | True | True | True | 0 |
| C14 | control | True | True | True | True | 0 |
| C15 | control | True | True | True | True | 0 |

gates: {"A1_answers": true, "A2_infra": true, "R1_no_loss": true, "R2_recovery": true, "R3_direction": true, "R4_budget": true, "R5_determinism": true, "R6_audit": true}
all_pass: True

| answer case | kind | G0 | G1 |
|---|---|---|---|
| C01 | numeral | incorrect/incorrect/incorrect | correct/correct/correct |
| C05 | date | incorrect/incorrect/incorrect | correct/correct/correct |
| C09 | components | incorrect/incorrect/partial | correct/correct/correct |
- scores: G0 0.1667 vs G1 3.0 (calls 36, failures 0)

exploratory (segment search on frozen fixtures, not gated):
{"money_holdout_v2": {"cases": 12, "directed_found": 4, "w1_found": 4}, "multi_component_holdout_v1": {"cases": 12, "directed_found": 0, "w1_found": 0}}
