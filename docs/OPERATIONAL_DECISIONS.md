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

1. **Resolve `.opencode/memory` in history.** Content reviewed: the author's
   own early project notes (`manifest.json`, `whiteboard.json`, removed from
   HEAD in `09b4397`; no secret patterns). They are personal data, so under the
   author's rule they must be **purged from history before any public
   opening**. The purge is not executed yet; the repository stays private until
   the public-open go.
2. **After any history rewrite**: re-run `scripts/preflight_publication.py`
   across every new blob, re-create the annotated tag, update every recorded
   SHA reference (CI records, docs), and verify CI on the rewritten `main`.
3. **Never publish first and clean later** — clones and caches make reversal
   incomplete.

Until steps 1-2 complete, publication remains conditional; nothing about the
private repository's visibility changes as a side effect of this record.
