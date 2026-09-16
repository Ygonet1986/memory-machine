# composition-v1 — Fase E pre-registration (E0)

Frozen 2026-09-15, before any E1/E2 execution and before any LLM call of this
phase. This section is the binding record; the code implements no card rule
absent from it. Any change to the frozen rules after the E0 commit is a new
pre-registration.

## 1. Decision question

Given the same retrieved memories and the same context budget, does presenting
short **exact excerpts organized as an evidence table** improve the use of
multi-memory evidence (composition) — without exceeding the baseline budget and
without relying on plasticity?

Motivating measurements (held): the graph finds gold the lexical path misses
(P5: 9 graph-only gold) but they do not convert to correct answers; more context
distracts (I4); a single question-matched window loses complementary anchors
(U4.3: multi-window 0.43 / anchor_keep 0.41 vs 0.49); ranking plasticity ended
at net −2 (P2b, closed).

## 2. Substrate (committed fixture)

`eval/fixtures/composition_u4/` — built once from the volatile U3 roots
(`/tmp/mm-graph-shared-*`) and the frozen snapshots
(`eval/graph_out/u_diag_longmemeval_{u3a,u3b}.jsonl`) by
`eval/gen_composition_fixture.py`; committed before any execution.

- 30 cases: blocks `u3a` (cases 12–26) + `u3b` (27–41), the U4.2 substrate and
  its 0.07–0.08 noise floor.
- `cases.jsonl`: per case `{block, case, cat, question, gold (reference,
  measurement only), required_ids, payload_ids, payload_chars, context_sha1,
  context (frozen control arm `graph_augment_precise`), verdict_precise}`.
- `records.jsonl`: the 122 tape records needed by E1/E2 (`why` fallback
  `summary`, verbatim, plus `why_sha1`), keyed by `(case, id)` — each case is an
  independent machine, so ids do **not** collide across cases.
- Manifest sha1 `24b390955b228bbfad5150bc7412ca67c6ae4cc5`; per-file sha256 in
  `manifest.json`. `gen_composition_fixture.py --verify` re-checks fixture
  contexts against the snapshots and every record's `why` against the source
  tapes (30 cases, 122 checks, 0 failures on 2026-09-15).

## 3. Instrument (`eval/evidence_cards.py`) — frozen rules v1

### 3.1 EvidenceAtom / EvidenceCard

```
EvidenceAtom(memory_id, field, start, end, text, fact_kinds, score)
decode(card)  = (memory_id, field, start, end)          # reversible
validate(card, source_text) ⇔ source_text[start:end] == text
```

In E0/E1/E2 one card carries exactly one atom (the atom is the card);
multi-atom cards appear only in E3.

### 3.2 Frozen rules

- **Canonical source**: `why` when non-empty, else `summary`; offsets index the
  verbatim field.
- **Segmentation**: `payload._segments` (sentence/newline split + trim),
  recovered as exact substrings with monotonic offsets.
- **Scoring**: `score = |question_tokens ∩ segment_tokens| + 0.5 × has_fact`
  with `retrieval.tokenize` (lowercase, len>2, stopwords removed) and
  `has_fact = number|date|interval`. Segments with `score ≤ 0` are dropped.
- **Ordering**: memories in caller-provided order (E1: `required_ids`; E2:
  `payload_ids`); segments by `(-score, start)`.
- **Packing**: round-robin passes over memories, at most 3 segments per memory,
  first-fit by remaining budget; a card that does not fit is skipped — atoms
  are **never truncated**.
- **Render**: `[M#### | field a:b] <verbatim text>`, joined by newlines.
- **Budget**: `CARD_BUDGET = 4000`, identical to the frozen baseline §12.5.

### 3.3 Fact classifiers (deterministic, used by scoring and reporting)

`number` `\b\d+(?:[.,]\d+)?\s*%?` · `date` years (19|20)\d{2} and month names ·
`interval` `\b\d+\s*(day|week|month|year)s?\b` · `negation`
not|no|never|without|n't · `comparison`
more|less|fewer|higher|lower|increase(d)|decrease(d)|difference|between|before|after|than ·
`update` now|currently|updated|changed|used to|no longer|latest.

### 3.4 Provenance validation

Every atom must be an exact substring of the source field with reversible
offsets (guard 2). `--report` validates every emitted card; normalization or
paraphrase invalidates provenance and fails the check (exit 1).

## 4. Execution guards (binding)

1. **Frozen rules**: the card construction rules above are frozen before E1;
   the fixture may be explored freely, rule changes require a new
   pre-registration.
2. **Exact atoms**: every atom is an exact substring of the memory with
   reversible offsets `(memory_id, field, start, end)`; normalization or
   paraphrase invalidates provenance.
3. **Selection purity**: in the real arm (E2) the instrument may read only the
   question and the candidate memories' verbatim text — never reference
   answers, gold atoms/spans or verdicts. E1 (ceiling) passes the gold memories
   by design and is labeled as such.
4. **Identity in E2**: both arms share the same questions, the same candidate
   memories in the same order, the same experimental parameters, model and
   judge; only the **context assembly** differs (frozen precise payload vs
   evidence cards), both within the same 4000-char budget.

No default in `src/` changes in this phase; the instrument is harness-local.

## 5. E1 — ceiling test (kill criterion)

Arms over the 30 cases, same batch, same model/judge:

```
full        the complete text of the required memories (no budget; the I4-style
            "more context" arm; chars reported)
precise     the frozen control context (fixture, byte-identical rebuild)
cards       evidence cards built from the required memories (budget 4000)
```

Order: deterministic metrics first (`fact_presence`-style atom retention,
all-present), then LLM verdicts (`answer_with` + `judge`, N=3; flip cases N=5).
**Kill criterion**: close the phase without E2 when the cards arm is `≤` the
precise arm on the deterministic atom metrics **and** `≤` on the paired answer
comparison (both axes, no re-fitting); a win on either axis alone does not
close it.

## 6. E2 — real selection, frozen recall

Candidates are exactly the frozen `payload_ids` of the control arm, order
preserved. Control = `context` from the fixture (re-run in the same batch);
experimental = cards from the same candidate memories' full texts, budget 4000.
Guard 4 (identity) applies verbatim. Negative control: a card run over an empty
candidate list must produce an empty context, byte-identical between
iterations.

## 7. Metrics and promotion gate (frozen)

- **Primary**: paired strict accuracy net `repaired − regressed ≥ +3` on the 30
  cases (floor 0.07–0.08, U4.2; a single flip is not evidence).
- **Secondary**: atom retention, all-present, AUR (accuracy under complete
  evidence), context efficiency (useful facts per 1000 chars).
- **Guards**: provenance validity 100%; budget ≤ 4000; deterministic
  (byte-identical iterations); E2 selection purity. Nothing is adapted after
  execution; the floor is not re-fit.

## 8. E3/E4 (conditional scope)

- E3 (only after a positive E2): document-graph relations (multi-evidence
  spans) as the card organizer; extractor instability (doc-graph-v1 F5 FAIL)
  requires a frozen extraction artifact or the deterministic synthetic corpus;
  pre-registered separately.
- E4 (only after a positive effect): unused LongMemEval sample
  (`longmemeval_oracle.json`), LoCoMo end-to-end, ≥2 answerer models, repeats
  for oscillation.

## 9. E0 execution record (no LLM)

`eval/results/composition_u4_e0/e0_report.json` (sha1
`c2285d38d5350fe176561d081bee00c65b291622`), report run byte-identical twice:

| mode | cards | chars/case (max) | memories w/o cards | cases w/o cards | provenance | deterministic |
|---|---:|---:|---:|---:|---|---|
| gold (`required_ids`) | 186 | 862 (2812) | 0 | 0 | 100% | yes |
| payloads (`payload_ids`) | 331 | 1439 (3966) | 1 (case 26 M0042) | 0 | 100% | yes |

Fact-kind histogram (gold): number 70, date 25, comparison 22, update 13,
interval 11, negation 7. Fixture regeneration is byte-identical; `--verify`
cross-checks fixture→snapshot→tape with 0 failures.

## 10. E1 execution record (registered verbatim, no criterion re-fit)

Run `eval/results/composition_u4_e1` (harness commit `371037b`; fixture sha1
`24b390955b228bbfad5150bc7412ca67c6ae4cc5`; single batch, model
`deepseek-v4-flash`, judge `deepseek-v4-flash`, N=3, flips N=5 on the 18 cases
whose precise↔cards modal diverged). Raw answers and judge reasons preserved in
`answers.jsonl` (sha1 `4dca1c6e…`), contexts in `contexts.jsonl`, per-case atom
audit in `atoms.jsonl`, paired ledger in `paired_ledger.jsonl`, summary in
`e1_summary.json` (sha1 `8065e095…`) + `summary.md`; `run_manifest.json` sha1
`e61201b9…`. Precise contexts were asserted byte-equal to the fixture
(`context_sha1`) before any call; card lines re-validated against the source
(0 integrity failures).

**Atom coverage (deterministic, reported separately):**

| arm | item facts present | rate | all-present cases | chars range |
|---|---:|---:|---:|---|
| complete | 247/249 | 0.992 | 29/30 | 2287–89664 |
| precise | 138/249 | 0.554 | 7/30 | 4000–4022 |
| cards | 200/249 | 0.803 | 15/30 | 273–2812 |

**Strict accuracy (modal of replicates; `partial` ≠ correct):**

| arm | correct | partial | incorrect |
|---|---:|---:|---:|
| complete | 26/30 | 1 | 3 |
| precise | 13/30 | 1 | 16 |
| cards | 11/30 | 2 | 17 |

**Paired ledger, cards vs precise (the frozen comparison):**

- classes: `repaired 7`, `regressed 9`, `stayed_correct 4`, `stayed_incorrect 10`
- **net = −2** (cards 11 vs precise 13); changed cases: repairs 20, 25, 28, 29,
  30, 32, 41; regressions 12, 13, 14, 22, 24, 27, 31, 37, 40.
- secondary, complete vs precise: `repaired 16`, `regressed 3`, **net +13**
  (unbudgeted ceiling arm; not a budget-comparable claim).
- identical-context oscillation: 17 of 90 case-arms non-unanimous on this
  substrate/batch.

**Kill gate (literal §5):** cards ≤ precise on atoms → **False** (cards strictly
beat on both atom-rate and all-present); cards beat precise on answers →
**False** (net −2). Kill = False ⇒ per §5 the paired ledger is presented before
any E2 decision; **no E2 was run** and no criterion was changed after results.

**Case 26 / M0042 audit (no repair applied):** M0042 is a control-arm payload
candidate, not an E1 required memory; it emitted no card in E0 payloads mode
and the gap is carried unchanged to E2. In E1 the case-26 cards arm covers
M0013 3/3 and M0040 1/1 in 649 chars (all-present true; precise all-present
false at 4006 chars).

**Honest reading:** cards converted more of the needed facts into the context
(0.554 → 0.803 item rate; all-present 7 → 15) but did **not** convert that into
better answers at equal budget (net −2); the unbudgeted `complete` arm scored
far above both (26/30), so on this substrate the remaining gap is not explained
by context organization alone. Per the frozen contract this is a **mixed
result**: it neither kills the phase nor authorizes E2; the paired ledger above
is the basis for the user's E2 decision.

## 11. E2 — controlled M0042 repair (pre-registration, frozen before execution)

Authorized 2026-09-16, after E1 (§10): cards improved atom delivery but not
answers (net −2) and the literal kill gate was false. E2 is a **mechanistic
repair ablation**, not a retrofit of E1.

**Hypothesis**: the case-26 error stems from the representation/selection of
M0042 (a payload candidate with zero scoring segments), and a controlled repair
can improve the answer without degrading the rest.

**Arms** (candidate set = the frozen `payload_ids`, order preserved; budget
4000; everything else identical to E1: questions, prompts, temperature, model,
judge, single batch):

- `cards_v1` — evidence_cards v1 exactly as frozen (must rebuild byte-identical
  to the E0 payloads-mode per-case sha1; asserted; harness aborts otherwise).
- `cards_repair` — v1 **plus the no-score fallback**: for each candidate
  memory that emits zero v1 cards, emit its first `<= 3` segments in source
  order (exact spans with reversible offsets, first-fit by the remaining
  budget, never truncating atoms). The fallback is a general rule, question-
  agnostic (no gold), not a case-26 hack; on this corpus it materializes
  **only for case 26 / M0042** (verified: `repair_changed_cases == [26]`).

**N**: 5 per case-arm (E1 found 17/90 non-unanimous case-arms).

**Primary metric**: strict modal. **Secondaries**: all-present, item rate,
paired ledger (repairs/regressions). The E1 ledger is frozen at `a0edc08` and
is neither re-run nor re-interpreted here.

**Promotion gate (all four, frozen):**

1. case 26 improves in strict modal;
2. global net strict > 0;
3. no material drop in item rate or all-present;
4. the improvement holds in the majority of the five runs (case-26 correct in
   `>= 3/5` repaired replicates and strictly more than the v1 arm).

**Verdict classes (frozen)**: `repair promoted` (all 4); `localized repair
only` (case 26 improved or majority holds but the global net is `<= 0`);
`M0042 hypothesis not supported` (case 26 does not improve) — in which case the
next target is the answerer/composition, since `complete = 26/30` showed the
evidence exists.
