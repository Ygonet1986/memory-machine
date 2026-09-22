# phrase-coverage-v1

| case | arm | gold | present |
|---|---|---|---|
| u3a:12 | W5 | 16gb | ok |
| u3a:12 | W6 | 16gb | ok |
| u3a:17 | W5 | 1year | MISS |
| u3a:17 | W6 | 1year | MISS |
| u3a:19 | W5 | 200$ | MISS |
| u3a:19 | W6 | 200$ | ok |
| u3a:22 | W5 | 2week | ok |
| u3a:22 | W6 | 2week | ok |
| u3b:27 | W5 |  | ok |
| u3b:27 | W6 |  | ok |

| arm | verdicts (N=3) | score |
|---|---|---:|
| W5 | incorrect/incorrect/incorrect | 0.00 |
| W6 | incorrect/incorrect/incorrect | 0.00 |
llm calls: 12 · failures: 0

w5 frozen: True
gates: {"P1_target_fixed": false, "P2_no_removals": true, "P3_answers": true, "P4_determinism": true, "P5_infra": true, "P6_w5_frozen": true}
