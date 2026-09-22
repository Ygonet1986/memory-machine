# Graph usage


The tape stays the single source of truth; the graph is a rebuildable
projection over it (like views), never a factual source by itself:

```text
Memory:  "Kalak crossed the rock."        (M0001)
             │
Graph:  Kalak --cross--> rock ── M0001        (every edge keeps its memory)
```

```bash
python3 -m memory_machine -C <root> graph build --rebuild   # project the tape
python3 -m memory_machine -C <root> graph status            # versions + counts
python3 -m memory_machine -C <root> graph query "Kalak"     # entities→paths→memories
python3 -m memory_machine -C <root> graph path Kalak rochedo
python3 -m memory_machine -C <root> graph explain R0001     # edge → memories → text
python3 -m memory_machine -C <root> graph document D0001    # document subgraph + windows
python3 -m memory_machine -C <root> graph document novella.txt --memory M0003 --span 100:400
python3 -m memory_machine -C <root> graph review            # identity hypotheses
python3 -m memory_machine -C <root> graph pending / failed / retry
```

Write-time extraction is opt-in (`graph_enabled=true`), batched
(`graph_batch_size=8`; 20 real memories: 11.2s → 4.3s per memory, 411 → 55
prompt tokens per memory from batch 1 → 16, zero failures). Recall adds the
graph as a second, deterministic selection arm: `graph_recall_mode=off`
(default) / `augment` / `only` — in every mode the evidence is rehydrated from
the tape. Rebuilds are atomic (`graph.building/` + swap) and human review
decisions survive them. See SPEC §20.

`.txt` attachments project into the **document graph** (SPEC §20.12): each file
is chunked onto the tape, registered in `graph/documents.jsonl` and its
original preserved under `<root>/documents/`. Rebuilding replays the documented
chunk/window scopes from the tape hash-gated against the preserved originals —
a missing or altered original aborts the build explicitly, never approximate.
`graph document` queries the subgraph (by `D####`, `name#hash` or file name,
optionally filtered by `--memory` and `--span`) and `graph explain` shows every
evidence span re-hydrated from the original file. See `docs/DOC_GRAPH.md`.

