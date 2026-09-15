# plasticity P2b shared-graph — populated-ledger evaluation on one graph

- run: `plasticity_u42_shared:runA`
- git: `23673cce7c58e5db799c5f7f53cdc379ea683233`
- fixtures: `eval/plasticity_fixtures/u42_shared` (graph sha1 `2cc293cfd4280910aa851bc21b02664bbe0298d7`)
- eval qids: 5–104 (84 cases)
- config: {"depth": 2, "recall_top_k": 32, "max_paths": 400, "max_paths_per_evidence": 3, "budget_items": 8, "budget_chars": 4000, "weight_utility": 0.5}
- population: {"qids": 20, "items": 160, "paths": 384, "edges": 636, "leaks": 0, "skipped_items": []}
- ledger frozen: {"events": 636, "rows": 636, "events_sha1": "2d446cd14e07de5e167cc2d6d904e5a4a5cdce02", "utility_sha1": "f3c0a7487ee0fe99ceec97aaf4e8e5db6aae87c1", "policy_version": "p0"}
- exposure (classified BEFORE outcomes): exposed=60, unexposed=24
- negative control: deterministic=True matches_base=True unexposed_changed=0
- shadow determinism: True

## Exposed (primary metric)

| qid | class | net | base correct | plastic correct | Δchars | order changed |
|---|---|---|---|---|---|---|
| 5 | stayed_incorrect | +0 | N | N | -20 | Y |
| 6 | regressed | -1 | Y | N | -20 | Y |
| 7 | stayed_incorrect | +0 | N | N | -20 | Y |
| 8 | stayed_incorrect | +0 | N | N | -20 | Y |
| 9 | stayed_incorrect | +0 | N | N | -20 | Y |
| 10 | stayed_incorrect | +0 | N | N | -20 | Y |
| 11 | stayed_incorrect | +0 | N | N | -20 | Y |
| 12 | stayed_incorrect | +0 | N | N | -20 | Y |
| 13 | stayed_incorrect | +0 | N | N | -20 | Y |
| 14 | stayed_incorrect | +0 | N | N | -20 | Y |
| 15 | stayed_incorrect | +0 | N | N | -20 | Y |
| 16 | stayed_incorrect | +0 | N | N | -20 | Y |
| 21 | stayed_correct | +0 | Y | Y | -11 | Y |
| 22 | stayed_incorrect | +0 | N | N | -11 | Y |
| 23 | regressed | -1 | Y | N | -11 | Y |
| 24 | stayed_correct | +0 | Y | Y | -11 | Y |
| 25 | stayed_incorrect | +0 | N | N | -11 | Y |
| 26 | stayed_incorrect | +0 | N | N | -11 | Y |
| 27 | stayed_incorrect | +0 | N | N | -11 | Y |
| 28 | stayed_incorrect | +0 | N | N | -11 | Y |
| 29 | stayed_incorrect | +0 | N | N | -11 | Y |
| 30 | stayed_incorrect | +0 | N | N | -11 | Y |
| 31 | stayed_incorrect | +0 | N | N | -11 | Y |
| 32 | stayed_incorrect | +0 | N | N | -11 | Y |
| 37 | repaired | +1 | N | Y | +8 | Y |
| 38 | stayed_incorrect | +0 | N | N | +8 | Y |
| 39 | repaired | +1 | N | Y | +8 | Y |
| 40 | regressed | -1 | Y | N | +8 | Y |
| 41 | stayed_incorrect | +0 | N | N | +8 | Y |
| 42 | stayed_incorrect | +0 | N | N | +8 | Y |
| 43 | stayed_incorrect | +0 | N | N | +8 | Y |
| 44 | stayed_incorrect | +0 | N | N | +8 | Y |
| 45 | stayed_incorrect | +0 | N | N | +8 | Y |
| 46 | stayed_incorrect | +0 | N | N | +8 | Y |
| 47 | stayed_incorrect | +0 | N | N | +8 | Y |
| 48 | stayed_incorrect | +0 | N | N | +8 | Y |
| 53 | stayed_correct | +0 | Y | Y | -6 | Y |
| 54 | stayed_correct | +0 | Y | Y | -6 | Y |
| 55 | regressed | -1 | Y | N | -6 | Y |
| 56 | stayed_correct | +0 | Y | Y | -6 | Y |
| 57 | stayed_incorrect | +0 | N | N | -6 | Y |
| 58 | stayed_incorrect | +0 | N | N | -6 | Y |
| 59 | stayed_incorrect | +0 | N | N | -6 | Y |
| 60 | stayed_incorrect | +0 | N | N | -6 | Y |
| 61 | stayed_incorrect | +0 | N | N | -6 | Y |
| 62 | stayed_incorrect | +0 | N | N | -6 | Y |
| 63 | stayed_incorrect | +0 | N | N | -6 | Y |
| 64 | stayed_incorrect | +0 | N | N | -6 | Y |
| 69 | stayed_incorrect | +0 | N | N | +24 | Y |
| 70 | stayed_incorrect | +0 | N | N | +24 | Y |
| 71 | stayed_correct | +0 | Y | Y | +24 | Y |
| 72 | stayed_incorrect | +0 | N | N | +24 | Y |
| 73 | stayed_incorrect | +0 | N | N | +24 | Y |
| 74 | stayed_incorrect | +0 | N | N | +24 | Y |
| 75 | stayed_incorrect | +0 | N | N | +24 | Y |
| 76 | stayed_incorrect | +0 | N | N | +24 | Y |
| 77 | stayed_incorrect | +0 | N | N | +24 | Y |
| 78 | stayed_incorrect | +0 | N | N | +24 | Y |
| 79 | stayed_incorrect | +0 | N | N | +24 | Y |
| 80 | stayed_incorrect | +0 | N | N | +24 | Y |

**exposed: {"regressed": 4, "repaired": 2, "stayed_correct": 6, "stayed_incorrect": 48} — net = -2 (6)**

## Unexposed (negative control)

**unexposed: {"stayed_correct": 8, "stayed_incorrect": 16} — changed = 0** (must remain unchanged)

**total: {"regressed": 4, "repaired": 2, "stayed_correct": 14, "stayed_incorrect": 64} — net = -2**

Promotion (pre-registered §13): requires exposed net ≥ +3 (frozen from §12.9)
— with unexposed unchanged, controls green, replication equal.
