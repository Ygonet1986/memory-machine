# money-holdout-v2

- W1 hits: 4/12 · W4 hits: 12/12 · external: {"W1": {"1000": false, "300": false}, "W4": {"1000": true, "300": false}}

| case | pos | W1 | W4 |
|---|---|---|---|
| G01 | early | ok | ok |
| G02 | middle | MISS | ok |
| G03 | late | MISS | ok |
| G04 | early | ok | ok |
| G05 | middle | MISS | ok |
| G06 | late | MISS | ok |
| G07 | early | ok | ok |
| G08 | middle | MISS | ok |
| G09 | late | MISS | ok |
| G10 | early | ok | ok |
| G11 | middle | MISS | ok |
| G12 | late | MISS | ok |

| case | W1 | W4 |
|---|---|---|
| G01 | correct/correct/correct | correct/correct/correct |
| G02 | incorrect/incorrect/incorrect | correct/correct/correct |
| G03 | incorrect/incorrect/incorrect | correct/correct/correct |

gates: {"Y1_w4_full": true, "Y2_beats_w1": true, "Y3_components": false, "Y4_budget": true, "Y4_determinism": true, "Y5_answers": true, "Y6_infra": true}
all_pass: False
