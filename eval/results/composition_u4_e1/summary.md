# E1 composition ceiling — summary (three arms, one batch)

- fixture: `/Users/igorcoutrimlacerda/memory-machine/eval/fixtures/composition_u4` (sha1 `24b390955b228bbfad5150bc7412ca67c6ae4cc5`)
- model `deepseek-v4-flash` · judge `deepseek-v4-flash` · N=3 (flips N=5: [12, 13, 14, 20, 22, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 37, 40, 41])

## Atom coverage (deterministic; separate from accuracy)

| arm | item facts present | rate | all-present cases | chars range |
|---|---|---|---|---|
| complete | 247/249 | 0.992 | 29/30 | 2287–89664 |
| precise | 138/249 | 0.554 | 7/30 | 4000–4022 |
| cards | 200/249 | 0.803 | 15/30 | 273–2812 |

## Strict accuracy (paired; modal of replicates)

- classes: {'regressed': 9, 'stayed_incorrect': 10, 'stayed_correct': 4, 'repaired': 7}
- net cards vs precise: **-2**

## Kill gate (literal)

- cards ≤ precise on atoms: False
- cards beat precise on answers: False
- **kill: False** (present paired ledger before any E2 decision)

## Case 26 / M0042 audit (no repair in E1)

{
  "required_ids": [
    "M0013",
    "M0040"
  ],
  "payload_ids": [
    "M0013",
    "M0040",
    "M0011",
    "M0042"
  ],
  "m0042_in_required": false,
  "m0042_in_payload_candidates": true,
  "m0042_note": "E0 payloads-mode gap: M0042 is a control-arm payload candidate with no scoring segment (no question-token match, no hard fact), so it emits no card. It is NOT an E1 required memory, so the gap is not exercised by this ceiling test and is carried unchanged to E2; no repair is applied in E1.",
  "arms": {
    "complete": {
      "chars": 25914,
      "all_item_facts_present": true,
      "items": {
        "M0013": {
          "delivered": true,
          "item_total": 3,
          "item_present": 3,
          "all_total": 130,
          "all_present": 130
        },
        "M0040": {
          "delivered": true,
          "item_total": 1,
          "item_present": 1,
          "all_total": 115,
          "all_present": 111
        }
      },
      "m0042_cards": null
    },
    "precise": {
      "chars": 4006,
      "all_item_facts_present": false,
      "items": {
        "M0013": {
          "delivered": true,
          "item_total": 3,
          "item_present": 2,
          "all_total": 130,
          "all_present": 27
        },
        "M0040": {
          "delivered": true,
          "item_total": 1,
          "item_present": 1,
          "all_total": 115,
          "all_present": 23
        }
      },
      "m0042_cards": null
    },
    "cards": {
      "chars": 649,
      "all_item_facts_present": true,
      "items": {
        "M0013": {
          "delivered": true,
          "item_total": 3,
          "item_present": 3,
          "all_total": 130,
          "all_present": 13
        },
        "M0040": {
          "delivered": true,
          "item_total": 1,
          "item_present": 1,
          "all_total": 115,
          "all_present": 7
        }
      },
      "m0042_cards": null
    }
  }
}
