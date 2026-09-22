# Publication preflight (first push)

Date: 2026-09-22 · Tool: `scripts/preflight_publication.py` (history-wide scan,
641 text blobs across all commits, plus every commit message).

## Decision

**First push to a private repository.**

Rationale: the history contains two early-commit paths with the author's own
personal notes (`.opencode/memory/manifest.json`, `.opencode/memory/whiteboard.json`,
removed from HEAD in `09b4397`). They hold no secret patterns and concern this
very project, but they are personal data in history. Making the repository
public later requires a decision: keep them (they are the author's own notes on
this project) or purge them from history (which would rewrite every SHA and
invalidate the annotated tags and the frozen v1.0 snapshot — not acceptable
without an explicit decision). A private first push preserves the clean
`0.2.0` reference while the decision is deferred.

## Scan results (all reviewed)

| Class | Finding | Disposition |
|---|---|---|
| Secret patterns | 12 hits, all canonical placeholders inside `tests/` (`sk-abcdef…`, `Bearer abcdef…`, `-----BEGIN RSA PRIVATE KEY-----`) | accepted: test fixtures |
| History-only personal data | `.opencode/memory/{manifest,whiteboard}.json` (author's own early notes, removed from HEAD) | accepted for private push; public requires a keep/purge decision |
| Restricted datasets | none versioned (`eval/data/` is ignored; `eval/DATASETS.sha256` publishes hashes only) | clear |
| Forbidden names (`.env`, keys, credentials) | none in history | clear |
| Large blobs (>5 MB) | none | clear |
| `.gitignore` | covers `.env`, `.venv/`, `eval/data/`, `dist/`, `build/`, `__pycache__/` | clear |
| License/authorship | MIT, "Igor Coutrim Lacerda" | clear |
| PR workflows | `ci.yml` references no secrets (fork-safe); `scientific.yml` uses the provider secret and is non-required | clear |

## Sequence after this record

1. Private remote `origin`, first push of `main` + historical tags.
2. Watch the CI matrix (3 OS × py3.11/3.14); fix environmental differences.
3. Branch protection: require `ci.yml`; keep `scientific.yml` informational.
4. Record the first green run as the L10 proof, then annotate the `0.2.0` tag.
5. Open `memory-lifecycle-v1` from the green reference.
