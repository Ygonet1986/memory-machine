# Graph Memory Machine v1 — status

**Status: COMPLETE** · reference tag **`graph-v1`** → `e7319a2` · baseline: **334 tests**
(frozen paper snapshot: `v1.0` → `7796211`, untouched).

## Final invariant

> No entity, relation or path of the graph is factual evidence without a
> provenance chain to a memory on the tape. The graph selects; the tape
> supplies the content.

## Core

| Phase | Commit | Delivered |
|---|---|---|
| F0 | `f7dfe90` | Clear docs button + capacity default 500 |
| F1 | `36426fc` | Append-only graph store (`graph/`), indices, rebuild, CLI `graph build/status/explain` |
| F2 | `747da99` | LLM `GraphExtractor` (semantic refs, never `E####`), resolver bands 0.90/0.60, write-time hooks, pending/failed policy |
| F3 | `02c978e` | Graph recall `off/augment/only`, semantic-hop traversal (event = 1 hop), explainable paths, global budget after union |
| F4 | `55e4cd2` | Batching (11.245 → 4.320 ms/mem; 411 → 55 tok/mem), `meta.json` versioning, atomic rebuild, hypothesis review, `pending/failed/retry` |
| F5 | `e7319a2` | Settings toggle + recall mode, read-only viewer with provenance, governed review, admin actions, packaging |

## Architecture (frozen)

```text
FITA (source of truth)
 ├─ views      how to organize
 └─ graph      how things relate
        ↓
     recall (off | augment | only)
        ↓
   evidence memory_ids
        ↓
      FITA (rehydration)
        ↓
   whiteboard → LLM
```

## Documentation

- `SPEC.md` §20 — normative graph projection specification.
- `README.md` — quickstart and commands.
- Manual v1.29, chapter 44 — architecture and operations.
- `PAPER.md` — the separate v1.0 paper; **not** updated by this line of work.

## Verify

```bash
python3 -m pytest tests/          # 334
python3 -m memory_machine -C <root> graph build --rebuild
open "/Applications/Memory Machine.app"   # Settings → Graph Memory
```

## Next

The measurement phase (`M0`–`M4`) evaluates v1 as a system: `off` vs
`augment`, `graph_only_gold`, path usefulness, extraction cost and review
frequency. Results land in `docs/GRAPH_EVAL.md`; no defaults change without
data. A v2 is a decision for after the measurements, not a presupposition.
