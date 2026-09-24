# companion-demo-v1

- model: deepseek-v4-flash
- calls: 18 (budget 40)
- gates: {"G1_fiction": true, "G2_deletion": false, "G3_correction": false, "G4_isolation": false, "G5_trailer": true, "G6_budget": true, "G7_extraction": false}
- all_pass: False

| step | kind | checks | calls | latency s |
|---|---|---|---|---|
| t1 | turn | {"record_types": ["person_report"], "trailer_ok": true, "used": [], "wrote:person_report": true} | 2 | 10.56 |
| t2 | turn | {"trailer_ok": true, "used": ["M0007"]} | 2 | 11.88 |
| t3 | turn | {"contain:m\u00fasica": true, "trailer_ok": true, "used": ["M0007", "M0010"], "used_nonempty": true} | 2 | 7.98 |
| t4 | turn | {"trailer_ok": true, "used": ["M0007", "M0010"]} | 2 | 10.75 |
| c1 | correct | {"new_status": "active", "ok": true, "old_status": "superseded", "replacement": "M0016", "target": "M0007"} |  |  |
| t5 | turn | {"contain:m\u00e3e": true, "forbid:irm\u00e3": false, "trailer_ok": true, "used": ["M0015", "M0016"], "used_nonempty": true} | 2 | 12.08 |
| t6 | turn | {"record_types": [], "trailer_ok": true, "used": ["M0010"], "wrote:story": false} | 2 | 13.83 |
| t7 | turn | {"forbid:biblioteca": true, "forbid:ilha": true, "trailer_ok": true, "used": ["M0015", "M0016", "M0010"]} | 2 | 10.34 |
| d1 | delete | {"ok": true, "removed": ["M0016"], "target": "M0016"} |  |  |
| t8 | turn | {"forbid:irm\u00e3": false, "forbid:m\u00e3e": false, "trailer_ok": true, "used": ["M0015"]} | 2 | 11.32 |
| i1 | isolation | {"forbid:astronomia": false, "structural": true} | 2 |  |
