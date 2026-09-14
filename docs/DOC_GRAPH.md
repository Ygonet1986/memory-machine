# Operational document graph (D-phase)

**Status: ACTIVE (D3–D5)** · the document layer of the Graph Memory Machine.

## The invariant

Same as graph-v1, extended to files:

> No entity, relation or window of a document graph is factual evidence without
> a provenance chain — through chunk memories and windows — to the preserved
> original file. The tape and the registry are the proof; the document graph is
> a reconstructible view.

Concretely: a document graph row is evidence only if `graph explain` can walk
it to a span of text that actually exists in `<root>/documents/` (or falls back
to the tape memory). A rebuild that cannot reproduce that chain MUST fail, not
approximate.

## Pipeline

```text
.doc.txt
   │  chunk_spans (size/overlap)          [tape: MemoryRecord M####, type=attachment,
   │                                       source="name#hash12", source_span=(a,b)]
   ▼
documents.jsonl  D####  (registry: source, name, hash, spans, extractor,
   │                     status, original=<root>/documents/name.txt)
   ▼
chunk pass    per M####          tag name/version          scope=chunk     (D3)
window pass   per D####|wNN      tag name/version/document scope=document  (D4)
   ▼
entities / relations / mentions (provenance fields source_document + source_span)
```

Commit order is fixed: **tape → registry → graph**. The graph pass is last and
never propagates failures.

## Scope levels and windows

`document_structure_level` selects the pass set (`chunk` default, `document`,
`both`); `--no-document-graph` zeroes the projection in every level.

Windows group source-ordered chunk memories by content cost (`len(why)`, not the
formatted text) against `document_window_chars` (default 12000). Each window is
an idempotency unit with the stable id `D####|wNN` and a document-scope tag
`name/version/document`; evidence is confined to real window members.

## Rebuild (D5)

`graph build --rebuild` with the document layer active replays the tape plus the
registry plus the preserved originals, exactly reproducing chunk- and
document-scope rows (same tags, retry policy and idempotency units). The
decisive round-trip: **ingest → snapshot → delete the derived projection (keep
`documents.jsonl`) → rebuild → structurally and provenance-equivalent**.

Gate: `validate_originals` hashes every preserved file **before any mutation**.
One missing or altered original aborts the whole build explicitly
(`documents_validated: false`) and the previous projection stays in place —
rebuilds are atomic (`graph/build.building/` + swap). Never "reconstruct
approximately".

Same-version re-runs are idempotent: the window pass would clobber `meta.tag`,
so `_settle_meta` restores the chunk-level tag and records the window tag as
`meta.document_tag` + `meta.document_structure_level`.

## Operations

```bash
# ingest a .txt (tape -> registry -> graph)
python3 -m memory_machine -C <root> attach path/to/file.txt --level both

# rebuild the whole projection (durable + document) atomically
python3 -m memory_machine -C <root> graph build --rebuild

# consult the document subgraph
python3 -m memory_machine -C <root> graph document D0001
python3 -m memory_machine -C <root> graph document novella.txt                # by file name
python3 -m memory_machine -C <root> graph document 'novella.txt#ab12cd34ef56' # by source
python3 -m memory_machine -C <root> graph document D0001 --memory M0003       # one chunk
python3 -m memory_machine -C <root> graph document D0001 --span 100:400       # overlap rows

# full provenance of one relation, every evidence span
python3 -m memory_machine -C <root> graph explain R0042
```

`graph document` answer: record, hash-validated `original` status
(`present`/`hash_ok`/`expected_hash`, mismatch reported), chunk memories,
`windows` map (relations per `D####|wNN`), filtered subgraph rows.

`graph explain` output: `scope` (durable|chunk|document), the full `evidence`
list — every span, source (`original` | `tape` | `record`), exact text
re-hydrated from the preserved file, `window` id, document record with original
status, plus the classic source/target entities, memory, aliases, confidence.
Durable explain keeps its historical shape.

## Failure semantics

| Situation | Rebuild error | Projection kept |
|---|---|---|
| original file missing | `original missing` (expected hash listed) | previous graph |
| original altered (hash mismatch) | `hash mismatch (document was altered)` | previous graph |
| registry without a preserved file | `no original recorded` (view only) | — |
| transient API failure | `pending`, retried `graph_max_attempts` | same graph |

## Compatibility and scope

- `build_graph` defaults `document_structure_level=None` — plain `graph build`
  keeps the graph-v3 projection byte-for-byte.
- D3 rows without scope stay readable; `_settle_meta` keeps `meta.tag`
  chunk-level so `graph status` and incremental runs behave as before.
- Recall/admission, PAPER/RESULTS figures and historical defaults are untouched.
- Out of scope for D5: new recall mode, answering from the document subgraph,
  response-quality benchmark, plasticity/utility studies, promoting
  `document`/`both` to default.

## Tests

`tests/test_document_ingest.py` (D3), `tests/test_document_structure.py` (D4),
`tests/test_document_rebuild.py` (D5: round-trip reconstruction, hash-gated
failure + previous graph kept, per-level rebuild, idempotent re-run, view
filters/windows, all-evidence explain, graph-v3 default compatibility, CLI
smoke). Full suite: `PYTHONPATH=src python3 -m pytest tests/ -q`.