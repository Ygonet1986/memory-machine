# graph-conversation-guard-v1 — pre-registration (bounded association rescue)

Status: **frozen before execution**. Date: 2026-09-25. Track: synthetic lab.

Background (v0.3.4): the conversation graph ships with `graph_recall_mode=
"augment"` because the promoted guard (`augment_guarded`: score floor 0.80,
cap 3) filters **association-only** evidence - the Lia → jardim → Nina case
where the linked turn shares no words with the question. The guard was kept
opt-in. This experiment tests a candidate **bounded rescue** for exactly that
class, without touching the promoted constants or any default.

## 1. Hypothesis

Re-admitting evidence whose every path is association-only (`related_to`),
above a lower declared floor and under a small extra cap, recovers the links
while adding **no** hub noise (hub expansion stays governed by the existing
hub-degree cap).

## 2. Fixture (frozen; hash in the manifest)

`eval/fixtures/graph_conversation_guard_v1/cases.json`, sha256
`05b9af5be8f7304ae30bc4291171e33c7389b2e53144da5bdeaa801076617ce3`.

- **A1-A3**: three association cases (distinct names; A3 adds a
  low-confidence distractor edge) where the linked memory has **no lexical
  overlap** with the question.
- **H1**: the hub-noise case (degree 2 under the fixture's declared cap).
- Declared constants: promoted guard `0.80 / 3`; candidate rescue `0.60 / 2`;
  traversal `depth = 3`; hub cap `2` for the guarded arms (the promoted
  default uses 20 - the mechanism is identical, the fixture lowers it to
  exercise the cap).

## 3. Arms (deterministic; no LLM)

- **U** plain augment: no score floor, no cap, no hub cap.
- **G** promoted guard: hub cap 2 + `guard_evidence(0.80, 3)`.
- **C** candidate: G plus `conversation_rescue(0.60, 2)` over the same
  evidence (only items whose paths are entirely `related_to`).

All arms run on the production-pruned index (`prune_to_active`).

## 4. Gates

- **C1** candidate recovers the linked memory in **3/3** association cases.
- **C2** candidate strictly beats the promoted guard on link recovery.
- **C3** hub noise: promoted **0**, candidate **0**, plain **> 0** (the
  fixture must exercise noise).
- **C4** determinism (two runs byte-equal).
- **C5** bounded rescue: candidate admitted items ≤ promoted + 2 per case.

`all_pass` = C1-C5. Failure is recorded as-is; no re-fit. Passing validates
the **mechanism in the lab** only; the rescue stays unwired/opt-in, and making
it the conversation default is a separate owner decision requiring a new §8
restart and release.

## Execution record

_(filled after the single run)_

## Execution record (2026-09-25) — single run

Deterministic, no LLM; one run; no re-fit. `all_pass` = **true**.

| reading | plain (U) | promoted (G) | candidate (C) |
|---|---:|---:|---:|
| linked memories recovered (3 cases) | 3/3 | **0/3** | **3/3** |
| hub noise admitted (1 case) | 1 | 0 | **0** |

Gates **C1-C5 all true**: the bounded rescue (association-only paths,
floor 0.60, cap 2) recovers every lexical-overlap-free link that the promoted
guard cuts, adds no hub noise, stays within promoted + 2 items per case, and
is deterministic. Scope: mechanism validated in the lab; the rescue remains
unwired/opt-in, and adopting it as the conversation default needs a new §8
restart plus a release (owner decision). Nothing promoted; the window, the
product defaults and the promoted guard constants are untouched.

## Adoption record (2026-09-25)

The owner adopted the validated rescue as the conversation default:
`graph_recall_mode = "augment_conversation"` (guarded traversal + rescue,
floor 0.60 / cap 2 as validated; no re-fit). `augment_guarded` keeps the
rescue off and `augment` keeps all guards off. Declared with an archived
restart of the admission-shadow-v2 window (4th restart of the day; 2
pre-restart records archived as
`admission_shadow.prerestart_20260925_rescue.jsonl`, never counted).
Nothing in the promoted guard constants, P3v4 or the experiment rules was
amended. Adoption is a product default inside the dual-track; real
validation of the combined behavior still requires measured use (the
restarted window and, later, a real pilot).
