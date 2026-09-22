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
