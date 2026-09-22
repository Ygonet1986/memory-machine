# admission-causal-v2 — relation slot, exploratory mechanistic round

Status: **frozen before execution**. Date: 2026-09-22. Track: **synthetic
lab**. Round type: **exploratory/mechanistic, not confirmatory** - the
mechanism was discovered on this same fixture (`admission-causal-v1`), so
any success here is mechanism validation, never independent evidence.

## 1. Hypothesis

Evidence retrieved through a valid causal relation must compete for its **own
structural slot** instead of the lexical relative floor: route provenance
must accompany the evidence into admission.

> `score = 0.162` means "low textual similarity", not "bad evidence".

## 2. Relation slot rule (exact, frozen)

- **Typed relations only**: `justified_by` (depth 1). `based_on` and
  `supersedes` are not followed. No recursive expansion.
- **Trigger**: the question carries a causal cue (why/reason/led/motivo/
  justificativa/because/justification/explain) AND at least one depth-1
  `justified_by` target exists from the **top-3 lexical** candidates.
- **Slot item**: the relation-linked target with the highest BM25 score
  (ties by target order). Exactly **one** relation slot per recall.
- **Provenance mandatory**: the item is admitted only with its relation
  source recorded (`relation_source` memory id) and the relation edge
  verified in the record.
- **No threshold relaxation for other candidates**: P3v4 runs unchanged over
  the expanded pool; the slot item is the only one exempt from the relative
  gain floor and the rare floor.
- **Budget**: the slot item is added only if the total stays within 4000
  characters; total delivered items <= 3 (slot + P3v4's up to 2),
  deterministic order (slot first).
- **Absence clean**: no relations -> no slot (the `causal_absent` scenario
  must keep `undue_rate` at the baseline level).

## 3. Policies

- **B** = P3v4 over lexical top-5 (baseline, as v1).
- **S** = B plus the relation slot rule above.

## 4. Metrics (reported, exploratory)

Availability, precision, per-scenario availability/precision, delivered,
slot usage, `undue_rate` on `causal_absent`, budget compliance. No gates are
declared for the mechanism itself; these **sanity requirements** must hold
or the mechanism is broken: `factual_control` availability >= B and
`causal_absent` undue_rate <= B + 0.05, budget never exceeded.

## 5. Freeze for the holdout

After this round the slot rule, its constants and the P3v4 baseline are
**frozen**; the holdout fixture is generated separately with new rationales,
relations, decoys and absent cases, and evaluated **once** against B under
the joint gates (availability and precision together, no control
regression). See `docs/ADMISSION_CAUSAL_HOLDOUT_PREREG.md`.

## 6. Execution protocol

Harness `eval/admission_causal_v2.py`, outputs
`eval/results/admission_causal_v2/report.json` and `report.md`,
`tests/test_admission_causal_v2.py` (determinism, mechanism, provenance,
absence), proof regenerated, execution record appended, all committed.

## Execution record (2026-09-22, exploratory)

Recorded run; determinism rerun identical. Slot used in 20/20 causal cases
(10 `causal_buried` + 10 `causal_chain`), 0 elsewhere.

| policy | availability | precision | delivered | max items | undue (absent) |
|---|---:|---:|---:|---:|---:|
| B baseline | 0.667 | 0.800 | 50 | 2 | 0.000 |
| **S relation slot** | **1.000** | **0.857** | 70 | 2 | 0.000 |

Per-scenario availability: `causal_buried` 0.50 -> **1.00**,
`causal_chain` 0.50 -> **1.00**, `factual_control` 1.00 (both),
`causal_absent` 1.00 (both). Requirements R1 (factual clean), R2 (absence
clean, undue 0.000), R3 (budget/cap: max 2 items), R4 (determinism) all
**true**.

Debugging note (exploratory): the tokenized causal cue missed `why` because
`why` is a stopword in the product tokenizer, so v1's gated expansion never
fired on the buried questions (its K-abl still expanded and the recorded
conclusion - the relative gain floor rejects relation-linked evidence -
stands; the v1 mechanism test locks it). In v2 the cue is matched on the raw
lowercased question (`\b(why|reason|led|because|justification|explain)\b`
plus Portuguese cues), and all 20 causal cases used the slot.

Interpretation (exploratory only): the mechanism works on the fixture where
it was discovered - **not** independent evidence. The slot adds exactly the
missing gold item, keeps absence clean (no relations -> no slot) and keeps
the factual control untouched. Policy and constants are now frozen for the
holdout round (`docs/ADMISSION_CAUSAL_HOLDOUT_PREREG.md`).
