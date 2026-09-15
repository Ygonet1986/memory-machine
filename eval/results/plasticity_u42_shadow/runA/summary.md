# plasticity P2 shadow — populated-ledger evaluation on U4.2

- run: `plasticity_u42_shadow:runA`
- git: `9594e926df97c7adcd40cbc217498ca5a4f68f22`
- train pool (ledger): cases 0–11 (disjoint from eval: True)
- eval set: cases 12–41 (30 cases)
- population: {"cases": 12, "items": 14, "paths": 42, "edges": 98, "leaks": 0, "skipped_items": ["4:M0016", "6:M0036", "7:M0040", "8:M0015", "11:M0013", "11:M0012"]}
- ledger_frozen: {"events": 98, "rows": 98, "events_sha1": "e1575e788b05f341c706b65c96793b69fb0af3d5", "utility_sha1": "ba4806c2dcf12991dd2001806eaaba0f0ea4060f", "policy_version": "p0"}
- negative control (empty ledger): deterministic=True matches_run1=True
- shadow eval determinism (shrun repeat): True

| case | slice | class | net | base correct | plastic correct | Δchars | max ΔE |
|---|---|---|---|---|---|---|---|
| 12 | u3a | stayed_correct | +0 | Y | Y | +0 | 0.0000 |
| 13 | u3a | stayed_correct | +0 | Y | Y | +0 | 0.0000 |
| 14 | u3a | stayed_incorrect | +0 | N | N | +0 | 0.0000 |
| 15 | u3a | stayed_incorrect | +0 | N | N | +0 | 0.0000 |
| 16 | u3a | stayed_correct | +0 | Y | Y | +0 | 0.0000 |
| 17 | u3a | stayed_incorrect | +0 | N | N | +0 | 0.0000 |
| 18 | u3a | stayed_incorrect | +0 | N | N | +0 | 0.0000 |
| 19 | u3a | stayed_correct | +0 | Y | Y | +0 | 0.0000 |
| 20 | u3a | stayed_incorrect | +0 | N | N | +0 | 0.0000 |
| 21 | u3a | stayed_incorrect | +0 | N | N | +0 | 0.0000 |
| 22 | u3a | stayed_correct | +0 | Y | Y | +0 | 0.0000 |
| 23 | u3a | stayed_correct | +0 | Y | Y | +0 | 0.0000 |
| 24 | u3a | stayed_incorrect | +0 | N | N | +0 | 0.0000 |
| 25 | u3a | stayed_incorrect | +0 | N | N | +0 | 0.0000 |
| 26 | u3a | stayed_incorrect | +0 | N | N | +0 | 0.0000 |
| 27 | u3b | stayed_incorrect | +0 | N | N | +0 | 0.0000 |
| 28 | u3b | stayed_correct | +0 | Y | Y | +0 | 0.0000 |
| 29 | u3b | stayed_incorrect | +0 | N | N | +0 | 0.0000 |
| 30 | u3b | stayed_incorrect | +0 | N | N | +0 | 0.0000 |
| 31 | u3b | stayed_incorrect | +0 | N | N | +0 | 0.0000 |
| 32 | u3b | stayed_correct | +0 | Y | Y | +0 | 0.0000 |
| 33 | u3b | stayed_incorrect | +0 | N | N | +0 | 0.0000 |
| 34 | u3b | stayed_incorrect | +0 | N | N | +0 | 0.0000 |
| 35 | u3b | stayed_incorrect | +0 | N | N | +0 | 0.0000 |
| 36 | u3b | stayed_correct | +0 | Y | Y | +0 | 0.0000 |
| 37 | u3b | stayed_incorrect | +0 | N | N | +0 | 0.0000 |
| 38 | u3b | stayed_incorrect | +0 | N | N | +0 | 0.0000 |
| 39 | u3b | stayed_correct | +0 | Y | Y | +0 | 0.0000 |
| 40 | u3b | stayed_correct | +0 | Y | Y | +0 | 0.0000 |
| 41 | u3b | stayed_incorrect | +0 | N | N | +0 | 0.0000 |

**classes: {"stayed_correct": 11, "stayed_incorrect": 19}**

**net = repaired − regressed = +0 (0/30 cases changed)**

Promotion (pre-registered §12.9): requires net ≥ +3 — and covers only
the order/budget change caused by the frozen ledger on an identical payload.
