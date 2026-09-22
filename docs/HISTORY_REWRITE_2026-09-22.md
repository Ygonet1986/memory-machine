# History rewrite — purging `.opencode/memory` (2026-09-22)

## Reason

The OSS go is conditional on resolving the author's personal notes
(`.opencode/memory/manifest.json`, `.opencode/memory/whiteboard.json`) in
history. Reviewed content: early project notes, no secret patterns, but
personal data. Owner rule: purge from history before any public opening.

## Method

- Tool: `git filter-repo` 2.47.0.
- Command: `git filter-repo --path .opencode/memory --invert-paths`.
- Safety: full mirror backup taken first (see below).
- Result: 144 commits preserved; the two commits that carried the notes
  (`2138cb8`, `09b4397`; each rewritten) no longer contain them. All six tags
  were rewritten in place (`graph-v1..v3`, `doc-graph-v1`, `v0.2.0`, `v1.0`).

## Verification

- `git log --all -- .opencode/memory` is empty.
- `git rev-list --objects --all | grep '.opencode/memory'` is empty.
- Preflight re-run over all rewritten blobs: **0 critical findings**; the 14
  remaining hits are canonical test placeholders (`sk-...`, `Bearer ...`, PEM
  header samples) in `tests/`, the preflight report and the tool itself —
  reviewed and accepted (`--accept-private-history`). The tool now classifies
  those by excerpt instead of by path.
- CI matrix green on the rewritten `main` (`b4b034c` at rewrite time).

## Reference remap

Every commit SHA cited in `docs/`, `README.md` and `CHANGELOG.md` was rewritten
from the filter-repo commit map (79 tokens across 17 files). The pre-rewrite
SHAs are invalid everywhere; the map is preserved in the backup mirror.

## Backup

`/Users/igorcoutrimlacerda/memory-machine-pre-rewrite.backup.git` (local
mirror, 9.1 MB, contains the removed notes). It must never be published; the
owner can delete it once satisfied. The local clone also still holds the
pre-rewrite objects only through this backup, not through the working `main`.

## Public-ready tag

`v0.2.1` marks this snapshot (history rewrite + admission shadow
instrumentation v1). `v0.2.0` remains as the rewritten historical release.
