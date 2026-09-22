# temporal-breadth-v1

- temporal cases: 13 · phrase cases: 6 · verdict: **recurring_class**
- counts: {"delivery_loss_w1": 3, "delivery_loss_w1_non_dev": 3, "fixed_by_w5": 1, "fixed_by_w5_non_dev": 1, "w3_regressions": 1, "w5_recovers_w3": 1, "w5_regressions": 0}

| case | dev | basis | ingestion | W1 | W3 | W5 | flags |
|---|---|---|---|---|---|---|---|
| u3a:14 |  | phrase | MISS | MISS | MISS | MISS | - |
| u3a:17 |  | phrase | ok | MISS | MISS | MISS | delivery_loss_w1 |
| u3a:21 |  | phrase | MISS | MISS | MISS | MISS | - |
| u3a:22 | DEV | phrase | ok | ok | MISS | ok | w3_regression,w5_recovers_w3 |
| u3b:27 |  | atom_fallback | ok | ok | ok | ok | - |
| u3b:28 |  | atom_fallback | ok | ok | ok | ok | - |
| u3b:30 |  | phrase | MISS | MISS | MISS | MISS | - |
| u3b:31 |  | atom_fallback | ok | MISS | ok | ok | delivery_loss_w1,fixed_by_w5 |
| u3b:33 |  | atom_fallback | ok | ok | ok | ok | - |
| u3b:34 |  | atom_fallback | ok | ok | ok | ok | - |
| u3b:35 |  | atom_fallback | MISS | MISS | MISS | MISS | - |
| u3b:40 |  | phrase | MISS | MISS | MISS | MISS | - |
| u3b:41 |  | atom_fallback | ok | MISS | MISS | MISS | delivery_loss_w1 |

gates: {"V1_consistent": true, "V2_determinism": true, "V3_w5_no_regression": true, "V4_budget": true}
