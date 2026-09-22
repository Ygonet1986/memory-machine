# numeral-inclusion-v1

| case | arm | basis | gold | present |
|---|---|---|---|---|
| u3a:12 | W3 | phrase | 16gb | ok |
| u3a:12 | W4 | phrase | 16gb | ok |
| u3a:19 | W3 | phrase | 200$ | MISS |
| u3a:19 | W4 | phrase | 200$ | ok |
| u3a:22 | W3 | phrase | 2week | MISS |
| u3a:22 | W4 | phrase | 2week | MISS |
| u3b:27 | W3 | atom_fallback |  | ok |
| u3b:27 | W4 | atom_fallback |  | ok |

| case | W3 | W4 |
|---|---|---|
| u3a:19 | incorrect/partial/incorrect | correct/correct/incorrect |
| u3a:22 | incorrect/incorrect/incorrect | incorrect/incorrect/incorrect |
llm calls: 24 · failures: 0

gates: {"N1_fixes_u3a19": true, "N2_no_new_regressions": true, "N3_answers": true, "N4_determinism": true, "N5_infra": true}
