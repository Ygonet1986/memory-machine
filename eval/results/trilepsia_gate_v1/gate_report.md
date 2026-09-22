# Scientific gate report (G1-G8, informational)

- run: `eval/results/trilepsia_gate_v1`
- summary: `e4_summary.json` · answers: 360/360
- **verdict: FAIL_QUALITY** — primary quality gate failed

| gate | status | detail |
|---|---|---|
| G1_response_regression | FAIL | {"metric": "paired net vs measured floor", "value": -1, "floor": 0.1389} |
| G2_evidence_recall | NOT_MEASURED | needs the frozen public harness |
| G3_composition_recall | NOT_MEASURED | needs the frozen public harness |
| G4_category_floors | NOT_MEASURED | needs the frozen public harness |
| G5_calls_online | NOT_MEASURED | needs call telemetry in the public harness |
| G6_latency | NOT_MEASURED | needs p50/p95 telemetry |
| G7_data_safety | PASS | {"provenance_failures": 0, "deterministic": true, "budget_ok": true} |
| G8_rollback | NOT_MEASURED | manual checklist item |
