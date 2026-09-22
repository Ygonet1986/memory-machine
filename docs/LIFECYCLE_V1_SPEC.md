# Memory Lifecycle v1 — specification (shadow mode)

Status: **draft for pre-registration** (docs/LIFECYCLE_V1_PREREG.md freezes the
experiment). Branch: `memory-lifecycle-v1`. Reference baseline: `v0.2.0`
(commit `181441d`, CI green 35712803264).

## 1. Purpose

Control *which records deserve to become consultable memory* without changing
the tape. Today "almost everything is memorized": every turn becomes a
`memory` record and is consultable. This specification defines a **shadow
admission projection** that classifies existing tape records into a lifecycle
class, writes its decisions to a rebuildable projection, and measures the
consequence — while the `0.2.0` tape, recall paths and defaults stay untouched.

The tape remains the single source of truth (invariant N1); the lifecycle is a
projection (N2) that **selects** what would be consultable; the tape supplies
the text (N3).

## 2. Non-goals

- No tape schema change, no rewrite, no deletion (N9 content immutability).
- No change of defaults; `lifecycle_mode` defaults to `off`.
- No automatic promotion of any record; no recall change in v1.
- No LLM in the rules arm; no retroactive promotion inside the same round.
- No use of evaluation gold by the classifier.

## 3. Classes

| Class | Meaning | Consultable in the shadow index |
|---|---|---|
| `semantic` | durable fact/decision/preference/restriction/procedure/correction | yes |
| `episodic` | occurrence bound to a session: attempt, result, failure, temporary state | yes |
| `event_only` | raw interaction; retained, **not** promoted to consultable memory | no |
| `reject` | duplicate/empty/noise: not promoted at all (still in the tape) | no |

The tape record keeps its own `type`; the lifecycle class is a separate,
revisable label.

**`reject` semantics (shadow vs production).** In shadow mode `reject` is a
counterfactual decision: the record stays in the tape (nothing is deleted) and
is only excluded from the *would-be* consultable set. If lifecycle is ever
promoted to the main path, the team must decide whether rejection happens
**before** the tape (which would change N1/N9 and requires a separate audit
log) or whether rejected records remain on the tape with a separate audit
trail. That decision is explicitly out of scope for v1 and is a prerequisite
for any production promotion.

**Deduplication scopes.** `duplicate_exact` and `duplicate_normalized` are the
only dedup rules in v1, and they apply **within a recent window** (same
session, previous N records) so that a valid repetition of a decision in a
later period is preserved. Semantic duplication is never rejected by a lexical
rule; it is classified as ambiguous and, in arm C, may be consolidated by the
LLM with a recorded reason code.

## 4. Policy v1 (deterministic rules)

The rules arm classifies each candidate record using only the record itself,
its neighbours and structured signals. Frozen rule families:

| Signal | Detected by | Class | Reason codes |
|---|---|---|---|
| Greeting/ack | lexical lists (`hi`, `ok`, `thanks`, `beleza`, …) and length < 24 chars | `event_only` | `greeting`, `ack` |
| Operational chatter | short message with no new content tokens vs the previous record | `event_only` | `operational`, `no_new_utility` |
| Duplicate — exact | byte-identical text within the same session's recent window | `reject` | `duplicate_exact` |
| Duplicate — normalised | case/whitespace/punctuation-normalised equality within the recent window | `reject` | `duplicate_normalized` |
| Duplicate — semantic | paraphrases, near-synonyms, same fact reworded | **not** a rule: classified by content; if unclear, `ambiguous` (arm C) | `possible_duplicate_semantic` |
| Typed durable records | tape `type` ∈ {decision, lesson, preference, bugfix, build} | `semantic` | `typed_record` + type-specific code |
| Attachments | tape `type` = attachment (document chunks) | `episodic` | `attachment_chunk` |
| Action/attempt | markers of an action taken or tried (`fixed`, `tried`, `ran`, `deployed`, `refactor`, …) | `episodic` | `action_taken` |
| Result/failure | result/measurement/failure vocabulary and error signatures | `episodic` | `experiment_result`, `failure_context` |
| Stability vocabulary | normative verbs (`always`, `never`, `must`, `we use`, `decided`, `prefer`) | `semantic` | `decision`, `preference`, `restriction` |
| Correction | explicit correction markers (`actually`, `correction`, `instead`, `supersede`) | `semantic` | `correction` |
| Ambiguous | weak/possible preference, future intent, unconfirmed inference, contradiction, context-dependent | `episodic` (provisional) with low confidence | `possible_preference`, `future_intent`, `unconfirmed_inference`, `contradiction`, `context_dependent` |

Confidence is a deterministic function of the rule evidence (number and weight
of matched signals), never a model score in this arm.

## 5. Arms

| Arm | Behaviour | LLM calls |
|---|---|---|
| **A — current** | every turn record is consultable (baseline) | 0 extra |
| **B — rules** | deterministic policy of §4 | 0 |
| **C — hybrid** | rules first; only ambiguous records go to one LLM call with a frozen prompt | ≤ budget (see prereg) |
| **D — diagnostic oracle** | gold class assigned by the fixture generator on a small subset; ceiling only, never a product arm | 0 |

D exists to bound what any classifier could achieve; it is excluded from
promotion criteria.

## 6. Shadow projection (rebuildable, no schema change)

```
<root>/lifecycle/
├── decisions.jsonl    one row per candidate record
├── promotions.jsonl   records that would enter the consultable set
├── metrics.jsonl      per-run aggregates (counts, rates, costs)
├── manifest.json      policy_version, tape sha256, counts, input hashes
└── reports/           generated reports (markdown/json)
```

Decision row (frozen schema):

```json
{
  "memory_id": "M0042",
  "action": "event_only",
  "target_class": null,
  "reason_codes": ["transient", "no_future_utility"],
  "confidence": 0.91,
  "policy_version": "lifecycle-v1",
  "decided_at": "2026-09-22T00:00:00+00:00",
  "input_hash": "sha256(text+neighbours+type)",
  "mode": "shadow"
}
```

`decided_at` is audit-only and never participates in ordering or hashing.
Rebuilding the projection from the same tape and policy version must be
identical in **normative content** — decisions, classes, reason codes, input
hashes and policy/config hashes — with timestamps excluded from the comparison
(or injected by a deterministic clock in tests) and hybrid outputs reused from
the frozen persisted LLM records.

## 7. Retroactive retrieval protocol (specified; implemented after the experiment)

1. try the active set (consultable memories);
2. detect insufficient coverage (existing question gate / coverage signals);
3. search the event log for non-promoted candidates;
4. rehydrate the evidence from the tape/original (existing `derived_from`/
   `rehydrate` machinery);
5. record `retroactive_hit` in `metrics.jsonl`;
6. optionally promote the found record — recorded, **never applied** in the
   same round.

False negatives are, by construction, recoverable: `event_only` records stay
in the tape.

## 8. Relationship to existing invariants

| Invariant | How lifecycle complies |
|---|---|
| N1 tape is truth | no record is changed or deleted |
| N2 projections rebuildable | `lifecycle/` is derived from the tape + policy |
| N3 every claim traceable | decisions reference `memory_id`; rehydration uses the tape |
| N7 secrets | candidate text already passed the tape scanner; no new text is written |
| N9 content immutability | shadow only |
| N10 experimental off | `lifecycle_mode=off` default; off ≡ byte-identical to 0.2.0 |

## 9. Rollout rule

Lifecycle may only move from shadow to the main recall path after the
pre-registered gates of `docs/LIFECYCLE_V1_PREREG.md` are met and the
off-switch reproduces `0.2.0` byte-for-byte. Until then it is a measurement
instrument.
