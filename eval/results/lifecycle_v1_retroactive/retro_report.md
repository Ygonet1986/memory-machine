# Lifecycle v1 — retroactive recovery (step 6)

- counters: {"fallback_not_triggered": 18, "fallback_triggered": 1, "irrelevant_retroactive_hits": 0, "recoverable_false_negative": 4, "retroactively_found": 1, "retroactively_missed": 3, "unrecoverable_due_to_ingestion": 1}
- retroactive recovery rate: 0.250
- retroactive precision@k: 1.000
- trigger quality: {'probes_needing_fallback': 4, 'fired_when_needed': 1, 'rate': 0.25}
- retriever capability: {'required_checked': 4, 'required_found_with_opportunity': 4, 'rate': 1.0}

| probe | trigger | needed | retro top-k |
|---|---|---|---|
| P01 | False | — | — |
| P02 | False | — | — |
| P03 | False | — | M0002(1.7004), M0007(1.7004) |
| P04 | False | — | M0002(1.7004) |
| P05 | False | ['M0012'] | M0012(2.786) |
| P06 | False | — | M0002(1.7004), M0012(1.393) |
| P07 | False | ['M0014'] | M0014(2.3594) |
| P08 | False | — | M0012(1.393) |
| P09 | False | — | — |
| P10 | False | — | — |
| P11 | False | — | M0004(3.489) |
| P12 | False | — | M0002(1.9463) |
| P13 | True | ['M0026'] | M0026(5.7796) |
| P14 | False | — | — |
| P15 | False | — | — |
| P16 | False | — | M0002(2.0794), M0026(1.5547) |
| P17 | False | — | M0012(1.6975), M0014(1.4341) |
| P18 | False | — | — |
| P19 | — | — | skipped (ingestion) |
| P20 | False | ['M0029'] | M0029(3.395), M0002(2.0794), M0012(1.6975) |
