# admission-shadow-v2 — product shadow pre-registration (frozen before collection)

Status: **frozen before collection**. Date: 2026-09-22.

A new real-tape window evaluating the frozen synthetic candidate **P3v4**
against the product's actual delivery and the score-margin comparators. The
paused `admission-shadow-v1` remains historically paused
(`docs/ADMISSION_SHADOW_PAUSE.md`); this window starts from zero and reuses
nothing from the previous sample.

## 1. Frozen candidate (tied to the commit)

P3v4 is the pass of `admission-synthetic-v4` (execution commit `44c0124`;
harness `eval/admission_synthetic_v4.py`). Its exact rule: v3 scoring
(`gain = 0.30*base + 0.20*rare + 0.15*entity + 0.15*temporal + 0.10*type_fit
+ 0.10*correction`, smoothed-IDF `rare`, path/key entity patterns,
correction markers, relative floor `0.60 x best_gain`, `rare >= 0.30`,
redundancy Jaccard > 0.60, budget 4000 chars, cap 2) plus **supersession
removal** and the **correction priority slot** (highest-gain eligible
correction first, exempt from the redundancy penalty).

The product implementation lives in `src/memory_machine/admission_p3v4.py`.
**Equivalence is mandatory and tested**: on the frozen synthetic fixture the
product module must reproduce the v4 harness decisions case by case
(`tests/test_admission_p3v4.py`). No constant, signal or order may change
during the window.

Candidate universe (declared boundary): BM25 top-5 positive scores over the
session tape records (`summary + " " + why`), product retriever; IDF computed
over all active session records. Agent-found candidates and the actual
payload are logged separately as the product's real behavior; they are not
part of the P3v4 counterfactual. Cross-session hits remain logged for the
two-tier record but are outside the P3v4 universe (single lexical scale).

## 2. Instrumentation schema v2 (frozen before collection)

`admission_shadow` records gain: `schema` version 2; the lexical candidate
block with per-candidate `score`, `rank`, `type`, `lexical_overlap`,
`rare_term_coverage`, `entity_matches`, `date_matches`, `correction`,
`temporal`, `type_fit`, `gain`, `removed_superseded`, `slot`,
`would_deliver_p3v4`, `chars_if_admitted`; the P3v4 summary (`delivered` ids,
`delivered_chars`, `empty`); the actual recall summary (`payload` ids,
`payload_chars`, delivered chars); comparators P1/P2 counterfactuals on the
same lexical candidates; `retrieval_ms` for the shadow computation; and the
existing event-log block. Derived data only: no question text, summaries,
notes or payload text (IDs, hashes and metrics). File mode 0600, off by
default (`MEMORY_MACHINE_ADMISSION_SHADOW=1`).

## 3. Unit of analysis and stopping rule (frozen, coverage-only)

Unit: one recall event (one user message → one recall), scored only when
`cached == false`; within-session duplicates by (session, question hash)
collapsed (first by timestamp); the same question across sessions counts.

Stop when **all** hold (checked only by `scripts/shadow_stop_check_v2.py`,
which reports coverage criteria and never outcome metrics):

| criterion | threshold |
|---|---|
| unique scored recalls | >= 200 |
| sessions with >= 1 valid record | >= 15 |
| window length (first to last record) | >= 21 days |
| scored recalls with event-log candidates | >= 30 |
| scored recalls with lexical candidates >= 2 | >= 100 |
| scored recalls with zero candidates in both universes | >= 10 |
| judged-subsample recalls (see 4) | >= 40 |
| malformed-record ratio | <= 1% |

Record treatment: valid = schema v2 parses, session id, question hash,
boolean cached, candidate lists present, parseable ts. Malformed counted,
never dropped silently. Corrections: the correction signal is part of P3v4;
the log records it per candidate and marks removed superseded records.
Absence of candidates: recorded as `empty` and scored through the abstention
metric. Duplicates: as above; instrumentation write failures remain a
disclosed limitation (one stderr warning, invisible losses possible).

## 4. Analysis after the stop (judged subsample)

The judged subsample is selected deterministically and content-independently:
`sha256(question_hash) % 5 == 0` (declared now, before collection). After
the stop, the frozen logs are snapshotted (sha256 per file) and a blind,
frozen judge (house protocol: primary judge, blind to arm, agreement audited
on a double-scored subset) labels, for each subsample recall:

1. **ranking miss** - was there a tape memory that answered the question and
   did not appear in the lexical candidates?
2. **admission discard** - did the answering memory appear in the candidates
   and was not delivered by P3v4?
3. **delivered but unused** - was the answering memory delivered and the
   answer failed to use it?

Diagnostics are reported as shares of the subsample; they are diagnostic,
not gated - except that a ranking-miss share above 50% invalidates the
promotion case (the admission layer would be measured on a substrate where
it cannot matter).

## 5. Metrics (primary, joint)

On the judged subsample: **availability** (recalls whose P3v4 delivery
contains the judged answering memory / judged recalls with a required
memory) and **precision** (judged-relevant delivered memories / delivered
memories). Full-sample: delivered counts, `payload_chars` and P3v4
`delivered_chars` (cost; 4000-char budget never exceeded by construction),
`retrieval_ms` p50/p95 (informational), abstention rate on candidate-empty
recalls, per-policy counters.

## 6. Comparators

Same judged subsample, same lexical candidates: **P1** (margin 0.50),
**P2** (margin 0.90), and the **actual delivery** (what the product really
put in the payload). P3v4 vs each on availability and precision.

## 7. Promotion gates (all required for a promotion proposal)

- G1 availability(P3v4) >= 0.90.
- G2 precision(P3v4) >= 0.70.
- G3 P3v4 strictly beats P1 and P2 on both availability and precision.
- G4 cost: mean delivered chars (P3v4) <= mean chars of the actual delivery
  and <= 4000 by construction.
- G5 ranking-miss share <= 50% (otherwise the experiment is invalidated).
- G6 stopping-rule criteria met and snapshot hashes recorded.

Passing all six authorizes a **promotion proposal** (a separate PR changing
a product default, still off until an explicit owner decision). It does not
promote anything by itself.

## 8. Window freeze

During the window: no change to P3v4 (module or constants), comparators,
schema, thresholds, stopping rule, retrievers, prompts or defaults. Bugs
that corrupt data (crashes, malformed writes) are fixed only as data-integrity
fixes and documented; any change to a measured mechanism restarts the window
from zero. No outcome aggregate may be computed or inspected before the stop
and snapshot; only `shadow_stop_check_v2.py` may run.

## 9. Threats and limits

Real sessions are uncontrolled: candidate quality, judge coverage and
co-occurrence patterns differ from the synthetic fixture; the P3v4
counterfactual is evaluated on a lexical substrate that excludes agent-found
candidates (declared boundary). The judged subsample is the smallest
supporting sample; diagnostics carry judge noise. Synthetic v4 results are
context, not evidence. No default changes during this phase.

## Window restart (2026-09-23) — declared under §8

Reason: **turn slots activated** (`MEMORY_MACHINE_TURN_SLOTS=1`, owner
decision, PRs #51/#52): the product write path now records question+reply
records on the tape, so the environment the window measures changed. §8
requires a restart from zero; no rule, threshold, candidate, comparator,
schema, prompt or default is amended (P3v4 stays frozen at `44c0124`).

Procedure executed:

- Pre-restart logs archived in place as
  `admission_shadow.prerestart_20260923.jsonl` (two session logs: 47 + 12
  records). The checker reads only `admission_shadow.jsonl` (`LOG_NAME`), so
  archived files are never counted.
- Counting restarts from the first schema-v2 record written after
  activation. New start: declared 2026-09-23; the first post-restart record
  marks it exactly.
- The partial collection is kept as historical artifact; **no outcome
  inspection was performed** on it. Activation requires an opencode restart
  (the plugin reads the flag at startup); until then the checker reports
  `met:false` with zero records.
- The tape gains `question`/`reply` slots from activation onward; this is
  part of the restarted window's declared starting state.

## Window restart (2026-09-25) — declared under §8 (agent conversation window)

Reason: the memory agents' conversation window became **active by default**
(`agent_history_messages = 10`, v0.3.1): agent user prompts now include the
last ten turn slots, so the measured recall environment changed. Same
procedure as the 2026-09-23 restart.

- Pre-restart logs archived in place as
  `admission_shadow.prerestart_20260925.jsonl` (29 records from the session),
  never counted by the checker; earlier archives remain historical.
- Counting restarts from the first schema-v2 record after activation; the
  new starting state includes the conversation window and the (still
  pending) turn-slot activation on the opencode side. The effective content
  of the window appears once turn slots are being written (opencode
  restart).
- No rule, threshold, candidate, comparator, schema, prompt template or
  default of the *admission experiment* is amended; P3v4 stays frozen at
  `44c0124`.

## Window restart (2026-09-25, second) — declared under §8 (conversation graph)

Reason: the persistent graph became **active by default** (v0.3.4:
`graph_enabled = true`, `graph_conversation_enabled = true`,
`graph_recall_mode = "augment"`), adding graph annotations/evidence to the
measured recall path and extraction calls on the turn-slot write path.

- Pre-restart logs archived in place as
  `admission_shadow.prerestart_20260925_graph.jsonl` (8 records), never
  counted; counting restarts from the first schema-v2 record after the
  change.
- No rule, threshold, candidate, comparator or schema of the *admission
  experiment* is amended; P3v4 stays frozen at `44c0124`.
- The P0–P5 promoted guard (`augment_guarded`) was **not** adopted as the
  conversation default: its score floor filters association-only evidence
  (fails the conversation graph's own association case). A conversation-aware
  guard would require its own pre-registered evaluation.

## Window restart (2026-09-25, third) — declared under §8 (graph hygiene)

Reason: the graph recall path now prunes its index to the tape's active
records before traversal (v0.3.5) and merges graph annotations in dimension
mode — both change measured recall behavior.

- Pre-restart logs archived in place as
  `admission_shadow.prerestart_20260925_hygiene.jsonl` (1 record), never
  counted; counting restarts from the first schema-v2 record after the fix.
- No rule, threshold, candidate, comparator or schema of the *admission
  experiment* is amended; P3v4 stays frozen at `44c0124`.
