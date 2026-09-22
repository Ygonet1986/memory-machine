# diagnostic-trace-v1

- cases: ['u3a:12', 'u3a:19', 'u3a:22', 'u3b:27'] · arms: ['W0', 'W1', 'W3'] · runs: 3 · llm calls: 72
- T1 stage consistency: True

| case | arm | origin | ingestion | delivery | answer verdicts | value used |
|---|---|---|---|---|---|---|
| u3a:12 | W0 | ok | ok | ok | correct/correct/correct | 3/3 |
| u3a:12 | W1 | ok | ok | ok | correct/correct/correct | 3/3 |
| u3a:12 | W3 | ok | ok | ok | correct/correct/correct | 3/3 |
| u3a:19 | W0 | ok | ok | MISS number:200 | incorrect/partial/incorrect | 0/3 |
| u3a:19 | W1 | ok | ok | MISS number:200 | incorrect/incorrect/incorrect | 0/3 |
| u3a:19 | W3 | ok | ok | MISS number:200 | incorrect/incorrect/partial | 0/3 |
| u3a:22 | W0 | ok | ok | ok | correct/correct/correct | 0/3 |
| u3a:22 | W1 | ok | ok | ok | correct/correct/correct | 0/3 |
| u3a:22 | W3 | ok | ok | ok | incorrect/incorrect/incorrect | 0/3 |
| u3b:27 | W0 | ok | ok | ok | partial/correct/correct | 3/3 |
| u3b:27 | W1 | ok | ok | ok | correct/incorrect/correct | 2/3 |
| u3b:27 | W3 | ok | ok | ok | correct/incorrect/correct | 3/3 |
