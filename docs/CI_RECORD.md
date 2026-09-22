# First CI run record (L10 proof)

Date: 2026-09-22 · Repository: `github.com/Ygonet1986/memory-machine` (private)

## First green matrix

- **Run:** [35712803264](https://github.com/Ygonet1986/memory-machine/actions/runs/35712803264) — conclusion **success**
- **Commit:** `26f273f` ("fix: deterministic topic order under coarse clocks")
- **Jobs (all green):** ubuntu-latest · py3.11; ubuntu-latest · py3.14;
  macos-latest · py3.11; macos-latest · py3.14; windows-latest · py3.11;
  windows-latest · py3.14.
- **Preceding failure (kept for the record):** run `35712534329` failed only on
  windows-latest · py3.11 (`test_backend` ×3) because Windows' coarse clock
  stamped two topics with identical `created_at` and the stable sort left the
  order filesystem-dependent. Fixed in `app/topics.py` with an id tie-breaker
  and covered by `tests/test_topics_order.py` (fails without the fix).
- **Tag:** annotated `v0.2.0` points at the green commit.

## What the CI proves

- installs the package and runs the full suite on 3 OS × 2 Python versions;
- no expected test disappeared (`verify_proof_manifest.py --strict`) and the
  manifest is exact;
- the installed wheel passes the cross-platform smoke (`smoke_installed.py`);
- deterministic offline harness checks (evidence cards, E5 dry-run, gate
  dry-run) run without secrets;
- wheel + conformance proof are uploaded as artifacts.

## Pending (plan decision required)

**Branch protection** (require the six CI checks on `main`) is unavailable on a
private repository of a personal Free account: both classic branch protection
and repository rulesets return HTTP 403 "Upgrade to GitHub Pro or make this
repository public". Options: enable GitHub Pro, or make the repository public
(which requires the keep/purge decision for the history-only
`.opencode/memory` notes recorded in `docs/PUBLICATION_PREFLIGHT.md`), or defer
protection while the repository stays private.

`scientific.yml` is intentionally **not** a required check; it needs a
`DEEPSEEK_API_KEY` repository secret to run (not set — no spend was authorized).
