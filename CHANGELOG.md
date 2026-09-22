# Changelog

All notable changes to this project are documented here. The project follows
[Semantic Versioning](https://semver.org/) for the installable package; the
manual/whitepaper keeps its own document version.

## [0.2.0] - 2026-09-22

First packaged release (L1).

- Installable package (`pip install .`) with the `memory-cli` entry point;
  no `PYTHONPATH` required.
- Single source of version truth (`memory_machine.__version__`), unified with
  the package metadata (previously `0.1.0` in code vs "project 1.0" in docs).
- Core stays dependency-free; extras: `app` (PySide6), `dev` (pytest), `eval`.
- OpenCode integration moved into the repository under `integrations/opencode/`
  with install/uninstall scripts.
- Offline mock LLM (`MEMORY_MACHINE_MOCK=1`) for smoke tests and CI; never for
  evaluation.

## [0.2.1] - 2026-09-22

Public-ready snapshot. No functional change to recall.

- **Admission shadow instrumentation (opt-in).** `MEMORY_MACHINE_ADMISSION_SHADOW=1`
  logs one JSON line per recall with derived admission signals (candidate
  origin/score/rank, lexical overlap, IDF rare-term coverage, entity/date
  matches, character costs, counterfactual admission). No question text,
  summaries or notes; no behavior change. See `docs/ADMISSION_SHADOW_V1.md`.
- **History rewrite.** The author's early personal notes (`.opencode/memory`)
  were purged from all history with `git filter-repo`; all tags and cited
  commit SHAs were rewritten (`docs/HISTORY_REWRITE_2026-09-22.md`).
- **Preflight.** Canonical placeholder excerpts are now accepted by excerpt
  rather than by path; re-run over the rewritten history reports 0 critical
  findings.
