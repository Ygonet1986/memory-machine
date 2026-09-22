# admission-shadow-v1 — pause record (2026-09-22)

## Status

**Paused before reaching the stopping rule and before any inspection of
outcome metrics.** Not completed, not failed. The scientific record reads:

> `admission-shadow-v1` was paused before reaching the stopping rule and
> before any inspection of outcome metrics. Its data were preserved but not
> analyzed. Development proceeded in `admission-synthetic-v1`, a controlled
> evaluation with relevance known by construction.

## What happened

- The collection was armed (env var in `~/.zshrc`) and verified end-to-end
  with a mock smoke in a temporary root.
- **Zero real log records** existed at pause time: nothing to preserve beyond
  the confirmed fact of zero data. The checker still applies if any stray log
  is ever found: it must remain unanalyzed unless the phase is formally
  resumed.
- The collection was disarmed: the `~/.zshrc` export was replaced by a pause
  marker; the plugin, repo and product were not modified.
- The stopping rule (`docs/ADMISSION_SHADOW_STOPPING_RULE.md`) stays frozen
  and unamended. If the phase is ever resumed, the collection window restarts
  from zero (there is no partial sample to continue).

## Why

The owner chose controlled evaluation with exact gold (`admission-synthetic-v1`)
to test the admission mechanism faster; real-world validation may return later
as an independent phase. The synthetic phase is an explicitly declared
substitute for the paused one, not a continuation.

## Discipline preserved

- No outcome metric of the paused phase was computed or inspected.
- The shadow instrumentation remains in the product, off by default.
- The synthetic phase has its own pre-registration, frozen before execution:
  `docs/ADMISSION_SYNTHETIC_V1_PREREG.md`.
