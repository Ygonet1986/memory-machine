# temporal-phrase-v1 — pre-registration (step 2: u3a-22 correction)

Status: **frozen before execution**. Date: 2026-09-22. Track: synthetic lab.

Step 2 of the owner's order: investigating u3a-22 separately with the phrase
metric, then testing a correction that preserves the temporal phrase within
budget. Gates: phrase present AND no stable answer regression.

## 1. Diagnosis (recorded before the rule)

u3a-22 (`How long was I in Japan for?`, gold `two weeks`, required M0038):
the phrase lives in **segment 36/238** of the record's `why`
("I spent two weeks traveling solo around the country"). W0 (head) and W1
(fact window) deliver it; **W3 misses it** - its numeric anchors are
digit-based (first/last data numbers), while `two` is a word number, and the
coverage fill does not reach that segment. This is a W3-class defect, not a
noise effect (W3 answers were incorrect 3/3 vs W1 3/3 correct).

## 2. Policy W5 (single declared delta over W3)

W3 unchanged except: when the question carries a **temporal cue** (how
long/when/duration/weeks/days/months/years/hours/minutes/before/after/ago/
since), the window additionally includes every segment containing a
**temporal phrase** - digit or word number + time unit, detected with the
`phrase_delivery_v1` phrase logic - in distance order to the best segment,
uncapped, bounded by the allocation. No money logic is included (W4 remains
separate and exploratory). Non-temporal questions: identical to W3.

## 3. Arms and gates

Arms **W1** (reference), **W3** (defective reference), **W5** on the tracked
cases (u3a-12, u3a-19, u3a-22, u3b-27); phrase metric from
`phrase_delivery_v1`.

- **T1 fixes the target**: u3a-22: phrase `2week` present under W5 (absent
  under W3; present under W0/W1, already recorded).
- **T2 no new regressions**: on the other tracked cases nothing present
  under W3 becomes absent under W5; budget per case <= W0 length.
- **T3 answer gate (N=3, same answerer, blind judge)**: u3a-22 with
  W1/W3/W5 in the same run: score(W5) > score(W3) and score(W5) >=
  score(W1) - 0.05 (restore the W1 level without a stable regression).
  18 calls cap.
- **T4 determinism** of the delivery stage; **T5** infra failures <= 20%.

`all_pass` = T1-T5. Any failure: report, no re-fit, windows stay OFF.

## 4. Expected readings (declared)

Phrase restored and answers back at the W1 level; u3a-19 unchanged (no
temporal cue in its question); controls untouched. If W5 restores the phrase
but answers stay below W1, the delivery fix is necessary but not sufficient
- recorded as such.

## 5. Execution protocol

Harness `eval/temporal_phrase_v1.py` (`--skip-llm` for delivery only),
outputs `eval/results/temporal_phrase_v1/{report.json,report.md}`,
`tests/test_temporal_phrase_v1.py`, proof regenerated, execution record
appended, committed.

## Execution record (2026-09-22)

Delivery (deterministic) and answer gate (N=3, same answerer, blind judge,
18 calls, 0 failures). No amendment was needed: the rule worked as declared.

| case | arm | gold | present |
|---|---|---|---|
| u3a-22 | W1 | `2week` | ok |
| u3a-22 | **W3** | `2week` | **MISS** |
| u3a-22 | **W5** | `2week` | **ok** |
| u3a-12 / u3a-19 / u3b-27 | W1/W3/W5 | as before | unchanged |

| arm | verdicts (u3a-22, N=3) | score |
|---|---|---|
| W1 | correct/correct/correct | 1.00 |
| W3 | incorrect x3 | 0.00 |
| **W5** | **correct/correct/correct** | **1.00** |

Gates **T1-T5 all true**; `all_pass` true. Findings:

- The diagnosis was precise: the gold phrase sits in segment 36/238 and W3's
  digit-only numeric anchors never reached a **word-number** temporal phrase;
  W5's temporal-phrase anchor restores it within the same allocation
  (budget respected on every case).
- The stable answer regression disappears: W5 matches W1 exactly (3/3
  correct) while W3 remains 0/3 - a clean delivery-stage correction with a
  verified answer-level effect, no noise ambiguity.
- No other tracked case changed (u3a-19's money class untouched; controls
  identical).

Nothing promoted; windows remain OFF. This closes step 2 of the directed
order. Step 3 (apply the phrase metric broadly to item 1 and check whether
the u3a-22 class is recurring) remains, and the corrected money holdout is
still pending before any W4 claim.
