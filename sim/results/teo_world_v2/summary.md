# teo-world-v2 — execution summary

- reserved seed base: 20260926
- episodes.jsonl sha256: `f7e9381a107402720e7a97ac6f2954a4e25966815fef40ab3ccf8a25cfc4ad7b`
- summary.json sha256: `3770d212914ad1dbe0bd03145e1b069d74d7b957b27c94a2cec2faa9d31948f6`

## Identifiability floor (>= 4 sigma)
- linear: min |v|*H = 2.0000 (100.00 sigma) -> pass
- const_accel: min |c|*H^2/2 = 1.0157 (50.79 sigma) -> pass
- attract: min |d|*(lambda*H/2)^3/24 = 0.0852 (4.26 sigma) -> pass
- oscill: min A (against a constant fit) = 0.9002 (45.01 sigma) -> pass

## R_fam (p95 realized reach)
- linear: 1.9000
- const_accel: 2.8894
- attract: 1.9159
- oscill: 1.6975

## Pooled primary (c3 - c1; M3 < 0 better, M5 > 0 better)
- M3 diff mean=-0.0693 CI=[-0.1057, -0.0388]
- M5 diff mean=2.1224 CI=[1.9219, 2.3126]
- B- attribution M3 mean=-0.0693 CI=[-0.1057, -0.0388]
- B- attribution M5 mean=2.1224 CI=[1.9219, 2.3126]

## Per-family profile (A1 vs V2: m1, m3, m4, m5; adoption diagnostics)
- linear: A1 m1=0.0978 m3=0.9203 m4=0.000 m5=0.000 | V2 m1=0.2110 m3=0.7742 m4=0.000 m5=1.828 (adopt/rep=0.64 first=3.0 reid=0.641)
- const_accel: A1 m1=0.0487 m3=0.9070 m4=0.016 m5=0.031 | V2 m1=0.1004 m3=0.7227 m4=0.062 m5=2.438 (adopt/rep=0.91 first=3.0 reid=0.906)
- attract: A1 m1=0.1669 m3=0.6680 m4=0.203 m5=0.000 | V2 m1=0.4266 m3=0.7477 m4=0.000 m5=2.188 (adopt/rep=0.80 first=3.1 reid=0.797)
- oscill: A1 m1=0.3404 m3=0.7742 m4=0.453 m5=0.031 | V2 m1=0.3212 m3=0.7484 m4=0.000 m5=2.109 (adopt/rep=0.59 first=3.0 reid=0.594)

## Gate
- m3_win=True m5_win=True m4_guard=True lofo_ok=True bminus_ok=True
- advance = **True**

M4 = announced detection = first entry into review (V2) or the sustained trigger (A1/B-); per-family guard in summary.json.
