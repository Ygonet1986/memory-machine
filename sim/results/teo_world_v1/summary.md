# teo-world-v1 — execution summary

- episodes.jsonl sha256: `904ef626b62aaf15cc8e791cf5f4edda5cd94b1e321a8d16a6e4548114678315`
- summary.json sha256: `02f862ccf3e6a865dd96c9c4dc1a22935db7ce678165d113789727b4958a3800`

## Identifiability floor (>= 4 sigma; sigma=0.02)
- linear: min |v|*H = 2.0000 (100.00 sigma) -> pass
- const_accel: min |c|*H^2/2 = 1.0302 (51.51 sigma) -> pass
- attract: min |d|*(lambda*H/2)^3/24 = 0.0883 (4.42 sigma) -> pass
- oscill: min A (against a constant fit) = 0.9002 (45.01 sigma) -> pass

## R_fam (p95 realized reach)
- linear: 1.9000
- const_accel: 3.1449
- attract: 1.9225
- oscill: 1.7443

## Pooled primary (c3 - c1; M3 negative/lower is better, M5 positive is better)
- M3 diff mean=-0.0858 CI=[-0.1196, -0.0531]
- M5 diff mean=0.6961 CI=[0.5703, 0.8203]
- B- attribution M3 mean=-0.0858 CI=[-0.1196, -0.0531]
- B- attribution M5 mean=0.6961 CI=[0.5703, 0.8203]

## Per-family profile (m1, m3, m4, m5)
- linear: A1 m1=0.0983 m3=0.9336 m4=0.016 m5=0.000 | B m1=0.0760 m3=0.7344 m4=0.234 m5=0.641 (reid=1.000)
- const_accel: A1 m1=0.0491 m3=0.8938 m4=0.000 m5=0.000 | B m1=0.1067 m3=0.7617 m4=0.688 m5=1.469 (reid=1.000)
- attract: A1 m1=0.1698 m3=0.6414 m4=0.172 m5=0.000 | B m1=0.1498 m3=0.6148 m4=0.172 m5=0.531 (reid=1.000)
- oscill: A1 m1=0.4229 m3=0.7477 m4=0.438 m5=0.109 | B m1=0.4327 m3=0.7609 m4=0.453 m5=0.266 (reid=0.641)

M4 = announced detection (consumer trigger; §6). Sustained-statistic reading reported as m4_sustained in summary.json.

## Gate
- m3_win=True m5_win=True m4_guard=False lofo_ok=True bminus_ok=True
- advance = **False**

