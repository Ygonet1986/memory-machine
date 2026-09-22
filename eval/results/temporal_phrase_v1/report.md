# temporal-phrase-v1

| case | arm | gold | present |
|---|---|---|---|
| u3a:12 | W1 | 16gb | ok |
| u3a:12 | W3 | 16gb | ok |
| u3a:12 | W5 | 16gb | ok |
| u3a:19 | W1 | 200$ | MISS |
| u3a:19 | W3 | 200$ | MISS |
| u3a:19 | W5 | 200$ | MISS |
| u3a:22 | W1 | 2week | ok |
| u3a:22 | W3 | 2week | MISS |
| u3a:22 | W5 | 2week | ok |
| u3b:27 | W1 |  | ok |
| u3b:27 | W3 |  | ok |
| u3b:27 | W5 |  | ok |

| arm | verdicts (N=3) | score |
|---|---|---:|
| W1 | correct/correct/correct | 1.00 |
| W3 | incorrect/incorrect/incorrect | 0.00 |
| W5 | correct/correct/correct | 1.00 |
llm calls: 18 · failures: 0

gates: {"T1_fixes_u3a22": true, "T2_no_new_regressions": true, "T3_answers": true, "T4_determinism": true, "T5_infra": true}
