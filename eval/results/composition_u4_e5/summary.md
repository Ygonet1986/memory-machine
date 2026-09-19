# E5 answerer/composition — summary

- fixture sha1 `24b390955b228bbfad5150bc7412ca67c6ae4cc5` · N=5 · model/judge `deepseek-v4-flash`
- scaffold vs control: classes {'stayed_incorrect': 18, 'stayed_correct': 9, 'repaired': 3} · net **+3**
- atom_complete vs control: classes {'repaired': 4, 'stayed_incorrect': 17, 'stayed_correct': 9} · net +4
- measured floor 0.2 (effective 0.2)
- atoms: control 0.711 vs atom_complete 0.776
- provenance 0 · deterministic True · budget True

**verdict: both levers fail -> consolidation (provenance layer), no new mechanism**
