# Gate B2 vs B2+ — summary

- fixture sha1 `cec309defe1acecb82adbf57e08a6e8f76cfe533` · N=5 · model/judge `deepseek-v4-flash`
- classes: {'stayed_correct': 24, 'stayed_incorrect': 11, 'regressed': 1}
- net (paired strict): **-1** (-0.0278)
- measured identical-context floor: 0.1389 (effective max(0.07, measured) = 0.1389)
- qualification accuracy: B2 0.5625 vs B2+ 0.5500
- atoms: b2 0.825 vs b2plus 0.825
- provenance failures: 0 · deterministic: True · budget_ok: True

**verdict: provenance layer only (no demonstrated analytical gain) — T3 blocked**
