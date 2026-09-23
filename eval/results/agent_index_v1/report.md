# agent-index-v1

- cases: 27 · routing coverage: {"A0": 1.0, "A1": 0.5321, "A2": 1.0}
- consulted partitions: {"A0": 54, "A1": 27, "A2": 54}
- answer scores: {"A0": 0.0, "A1": 0.0, "A2": 0.125}
- calls: 72 · failures: 0

gates: {"G1_no_case_lost": true, "G2_advantage": true, "G3_fewer_calls": false, "G4_answers": true, "G5_determinism": true, "G6_infra": true}
all_pass: False

scope: K=2 artificial partitions per case test the routing mechanism; no real-tape call savings are demonstrated
