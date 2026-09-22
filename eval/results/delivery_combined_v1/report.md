# delivery-combined-v1

## Evaluation A — delivery presence

| arm | mean | numeric | non-numeric |
|---|---:|---:|---:|
| W0 | 0.515 | 0.486 | 0.583 |
| W1 | 0.643 | 0.538 | 0.889 |
| W3 | 0.727 | 0.657 | 0.889 |

A gates: {"A1_mean": true, "A2_numeric": true, "A3_nonnumeric_identical": true, "A4_budget": true, "A5_determinism": true}

## Evaluation B — answer accuracy (same answerer, blind judge)

| arm | score | strict | numeric | counts |
|---|---:|---:|---:|---|
| W0 | 0.383 | 0.367 | 0.405 | {'correct': 11, 'partial': 1, 'incorrect': 18, 'infra_error': 0} |
| W1 | 0.583 | 0.533 | 0.500 | {'correct': 16, 'partial': 3, 'incorrect': 11, 'infra_error': 0} |
| W3 | 0.617 | 0.567 | 0.595 | {'correct': 17, 'partial': 3, 'incorrect': 10, 'infra_error': 0} |

B gates: {"B1_beats_W0": true, "B2_vs_W1": true, "B3_numeric_vs_W1": true, "B4_downgrades": false}
calls: {"failures": 0, "judge_prompt_version": "v1", "limit": 30, "llm_calls": 180, "pairs": 90}
inconclusive_infrastructure: False

