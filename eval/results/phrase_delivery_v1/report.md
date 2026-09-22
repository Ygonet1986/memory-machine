# phrase-delivery-v1

| case | arm | basis | gold phrase/info | present | answer verdicts |
|---|---|---|---|---|---|
| u3a:12 | W0 | phrase | 16gb | ok | correct/correct/correct |
| u3a:12 | W1 | phrase | 16gb | ok | correct/correct/correct |
| u3a:12 | W3 | phrase | 16gb | ok | correct/correct/correct |
| u3a:19 | W0 | phrase | 200$ | MISS | incorrect/partial/incorrect |
| u3a:19 | W1 | phrase | 200$ | MISS | incorrect/incorrect/incorrect |
| u3a:19 | W3 | phrase | 200$ | MISS | incorrect/incorrect/partial |
| u3a:22 | W0 | phrase | 2week | ok | correct/correct/correct |
| u3a:22 | W1 | phrase | 2week | ok | correct/correct/correct |
| u3a:22 | W3 | phrase | 2week | MISS | incorrect/incorrect/incorrect |
| u3b:27 | W0 | atom_fallback |  | ok | partial/correct/correct |
| u3b:27 | W1 | atom_fallback |  | ok | correct/incorrect/correct |
| u3b:27 | W3 | atom_fallback |  | ok | correct/incorrect/correct |

gates: {"P1_detects_u3a22": true, "P2_controls": true, "P3_locates_u3a19": true, "P4_hashes": true, "P5_determinism": true}
