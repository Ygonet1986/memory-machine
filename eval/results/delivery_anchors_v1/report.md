# delivery-anchors-v1 (lab)

- cases: 30 · repairs W1/W2: 6/5

| arm | all-present | mean presence | numeric | non-numeric |
|---|---:|---:|---:|---:|
| W0 | 14/30 | 0.515 | 0.486 | 0.583 |
| W1 | 17/30 | 0.643 | 0.538 | 0.889 |
| W2 | 17/30 | 0.635 | 0.657 | 0.583 |

gates: {"D1_no_regression": true, "D2_numeric_mean": true, "D3_case0_anchor": false, "D4_numeric_repairs": true, "D5_nonnumeric_unchanged": true, "D6_budget": true, "D7_determinism": true}
all_pass: False

## case u3a-12 (16GB anchor)
{"W0": {"all_present": true, "chars": 4000, "missing": [], "presence": 1.0}, "W1": {"all_present": true, "chars": 3921, "missing": [], "presence": 1.0}, "W2": {"all_present": true, "chars": 3998, "missing": [], "presence": 1.0}}
