# E2 — controlled M0042 repair (cards v1 vs cards + no-score fallback)

- fixture sha1 `24b390955b228bbfad5150bc7412ca67c6ae4cc5` · E1 ledger frozen at `a0edc08`
- model `deepseek-v4-flash` · judge `deepseek-v4-flash` · N=5

## Atom coverage (required memories; deterministic)

| arm | item facts present | rate | all-present cases |
|---|---|---|---|
| cards_v1 | 176/249 | 0.707 | 15/30 |
| cards_repair | 176/249 | 0.707 | 15/30 |

## Strict accuracy (modal of 5)

- classes: {'stayed_incorrect': 18, 'stayed_correct': 9, 'repaired': 2, 'regressed': 1}
- net cards_repair vs cards_v1: **+1**
- case 26 replicates: v1=['partial', 'partial', 'partial', 'partial', 'partial'] repair=['correct', 'incorrect', 'correct', 'incorrect', 'partial']

## Gate (frozen)

1. case 26 strict modal improves: True
2. global net strict > 0: True (+1)
3. no material drop in item rate/all-present: True
4. majority of the five runs: False (2/5 vs 0/5)

**verdict: localized repair only (or none): not a general mechanism**
