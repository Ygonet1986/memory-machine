# Lifecycle v1 — arms A/B/D report (deterministic, frozen definitions)

- fixture: `/Users/igorcoutrimlacerda/memory-machine/eval/fixtures/lifecycle_v1` · projection policy `lifecycle-v1`
- required memories (probes, ingested only): 17
- note: global metrics use the final promoted set; per-probe values apply the temporal guard (seq < after_seq)
- rebuild identical: True

| arm | promoted | promotion precision | promotion recall | active-set reduction (received) |
|---|---:|---:|---:|---:|
| A | 32 | 0.531 | 1.000 | 0.000 |
| B | 17 | 0.765 | 0.765 | 0.469 |
| D | 20 | 0.850 | 1.000 | 0.375 |

## Arm B confusion (gold rows × predicted columns)

| gold \ pred | semantic | episodic | event_only | reject |
|---|---:|---:|---:|---:|
| semantic | 11 | 1 | 1 | 0 |
| episodic | 2 | 2 | 3 | 0 |
| event_only | 1 | 0 | 8 | 0 |
| reject | 0 | 0 | 0 | 3 |

## Arm B false-semantic

- predicted semantic: 14, wrong: 3 (precision error 0.214; FP rate 0.158)

## Per-probe (temporal: seq < after_seq)

| probe | required | found | recall |
|---|---:|---:|---:|
| P01 | 1 | 1 | 1.00 |
| P02 | 1 | 1 | 1.00 |
| P03 | 1 | 1 | 1.00 |
| P04 | 1 | 1 | 1.00 |
| P05 | 1 | 0 | 0.00 |
| P06 | 1 | 1 | 1.00 |
| P07 | 1 | 0 | 0.00 |
| P08 | 1 | 1 | 1.00 |
| P09 | 1 | 1 | 1.00 |
| P10 | 1 | 1 | 1.00 |
| P11 | 1 | 1 | 1.00 |
| P12 | 1 | 1 | 1.00 |
| P13 | 1 | 0 | 0.00 |
| P14 | 1 | 1 | 1.00 |
| P15 | 2 | 2 | 1.00 |
| P16 | 1 | 1 | 1.00 |
| P17 | 1 | 1 | 1.00 |
| P18 | 2 | 2 | 1.00 |
| P19 | — | — | skipped (ingestion) |
| P20 | 1 | 0 | 0.00 |

## Arm B hard cases (promoted / total)

- ack: 1/6
- build: 1/1
- correction: 2/2
- decision: 1/1
- decision_change: 1/1
- duplicate_exact: 0/1
- duplicate_normalized: 0/1
- experiment_result: 2/2
- failure_context: 1/1
- greeting: 0/1
- important_never_used: 1/1
- invalid_record: 0/1
- lesson: 1/1
- negation: 0/1
- operational: 0/2
- restriction: 1/1
- semantic_duplicate: 1/1
- temporary_preference: 0/1
- temporary_state: 0/2
- useful_low_appearance: 1/1
- valid_repetition: 2/2
- weak_future_intent: 1/1
