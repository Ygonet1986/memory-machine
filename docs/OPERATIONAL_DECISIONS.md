# Operational decisions (2026-09-22)

Owner decisions, recorded verbatim in effect. These govern publication, CI and
spend; they do not change any product or experiment default.

## 1. Branch protection: deferred

No GitHub Pro purchase and no public exposure just to obtain rulesets. The
manual process stands: every change lands via PR with all six `ci.yml` checks
green before merge; `scientific.yml` remains informational. Revisit only if the
project gains collaborators or automated dependency updates.

## 2. `DEEPSEEK_API_KEY`: activate on demand only

The secret is not configured now. Activate it for a single, pre-registered
scientific run whose cost is justified, then disable it again. It must never be
exposed to external/fork pull requests; `scientific.yml` stays non-required and
scheduled/dispatch-only.

## 3. OSS publication: conditional go

Engineering readiness is accepted (L1 packaging, L10 CI, preflight). Public
opening requires, in order:

1. **Resolved (2026-09-22): `.opencode/memory` purged from history** with
   `git filter-repo` after a mirror backup; details and verification in
   `HISTORY_REWRITE_2026-09-22.md`.
2. **Executed after the rewrite**: preflight re-run over all rewritten blobs
   (0 critical, 14 reviewed canonical placeholders, PASS with
   `--accept-private-history`); every cited SHA remapped from the commit map;
   tags rewritten; CI green on the rewritten `main`; `v0.2.1` will mark the
   public-ready snapshot.
3. **Never publish first and clean later** — the purge happened before any
   public exposure, as required.

The public-open condition is now met at the repository level; the visibility
flip itself remains an explicit owner action.
