# plasticity P1 observe — shadow ranking comparison (what would change)

- cases: 30 (U4.2: u3a 12–26 + u3b 27–41)
- snapshot: `eval/graph_out/graphs/longmemeval`
- ledger: `{'policy_version': 'p0', 'rows': 0, 'sha1': 'empty'}`
- config: `{'depth': 2, 'top_k': 8, 'max_paths': 400, 'weight_utility': 0.5, 'hop_cost_observe': 0.0}`
- determinism (2 identical iterations): `True`

| case | slice | seeds | paths | order equal | targets equal | missing equal | max ΔE | budget Δchars |
|---|---|---|---|---|---|---|---|---|
| 12 | u3a | 3 | 26 | Y | Y | Y | 0.0000 | +0 |
| 13 | u3a | 2 | 179 | Y | Y | Y | 0.0000 | +0 |
| 14 | u3a | 3 | 400 | Y | Y | Y | 0.0000 | +0 |
| 15 | u3a | 1 | 157 | Y | Y | Y | 0.0000 | +0 |
| 16 | u3a | 1 | 4 | Y | Y | Y | 0.0000 | +0 |
| 17 | u3a | 0 | 0 | Y | Y | Y | 0.0000 | +0 |
| 18 | u3a | 1 | 9 | Y | Y | Y | 0.0000 | +0 |
| 19 | u3a | 3 | 405 | Y | Y | Y | 0.0000 | +0 |
| 20 | u3a | 0 | 0 | Y | Y | Y | 0.0000 | +0 |
| 21 | u3a | 1 | 208 | Y | Y | Y | 0.0000 | +0 |
| 22 | u3a | 1 | 155 | Y | Y | Y | 0.0000 | +0 |
| 23 | u3a | 3 | 400 | Y | Y | Y | 0.0000 | +0 |
| 24 | u3a | 1 | 202 | Y | Y | Y | 0.0000 | +0 |
| 25 | u3a | 1 | 401 | Y | Y | Y | 0.0000 | +0 |
| 26 | u3a | 3 | 400 | Y | Y | Y | 0.0000 | +0 |
| 27 | u3b | 2 | 144 | Y | Y | Y | 0.0000 | +0 |
| 28 | u3b | 2 | 242 | Y | Y | Y | 0.0000 | +0 |
| 29 | u3b | 2 | 267 | Y | Y | Y | 0.0000 | +0 |
| 30 | u3b | 2 | 337 | Y | Y | Y | 0.0000 | +0 |
| 31 | u3b | 4 | 400 | Y | Y | Y | 0.0000 | +0 |
| 32 | u3b | 2 | 199 | Y | Y | Y | 0.0000 | +0 |
| 33 | u3b | 0 | 0 | Y | Y | Y | 0.0000 | +0 |
| 34 | u3b | 0 | 0 | Y | Y | Y | 0.0000 | +0 |
| 35 | u3b | 2 | 177 | Y | Y | Y | 0.0000 | +0 |
| 36 | u3b | 2 | 223 | Y | Y | Y | 0.0000 | +0 |
| 37 | u3b | 0 | 0 | Y | Y | Y | 0.0000 | +0 |
| 38 | u3b | 4 | 400 | Y | Y | Y | 0.0000 | +0 |
| 39 | u3b | 1 | 115 | Y | Y | Y | 0.0000 | +0 |
| 40 | u3b | 3 | 262 | Y | Y | Y | 0.0000 | +0 |
| 41 | u3b | 0 | 0 | Y | Y | Y | 0.0000 | +0 |

**Cases whose delivered targets or path order would change: 0/30**

Deliverable: an auditable 'what would change' table with nothing changed.
