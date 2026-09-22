# Evidence retention policy

Recorded after the external audit (2026-09-22). Goal: every result cited in
the paper or in a closure record must stay reproducible and readable without
depending on expiring infrastructure.

## Rules

1. **Repository first.** Deterministic experiment outputs live in the
   repository (`eval/results/<line>/`), the conformance proof
   (`docs/CONFORMANCE_PROOF.txt`) is regenerated per commit, and closure
   records plus pre-registrations are committed documents.
2. **Releases carry evidence.** Every tagged release attaches the conformance
   proof and dataset hashes as assets (`v0.2.2` onwards). Release notes state
   the CI run and the scope of the change.
3. **Actions artifacts are convenience copies only.** GitHub artifact
   retention is capped at 90 days; wheels, per-matrix proofs and scientific
   raw runs uploaded by workflows must never be the only home of a result.
4. **Scientific runs.** `scientific.yml` is informational and secret-gated.
   When a pre-registered run produces numbers that a paper or closure record
   cites, the final report and the raw artifacts are committed under
   `eval/results/<line>/` and attached to a release in the same change.
5. **Local backups are never published.** The pre-rewrite mirror
   (`memory-machine-pre-rewrite.backup.git`) exists only on the author's
   machine and contains history that was deliberately purged.

## What this does not cover

Model-provider responses are not archived (licensing and reproducibility
limits); the harness inputs, prompts and commands are, so a rerun is always
possible when a provider is available.
