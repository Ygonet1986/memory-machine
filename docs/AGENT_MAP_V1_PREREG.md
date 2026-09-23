# agent-map-v1 — pre-registration (verifiable per-agent map, lab)

Status: **frozen before execution**. Date: 2026-09-23. Track: synthetic lab.

Owner direction after `agent-index-v1` (M0364: union preserved coverage but the
summary-digest arm lost half of it): give each agent a **verifiable map** -
pointers to the records/passages it manages - instead of a summary label, and
let the system **verify the map against the tape** before waking an agent.
Separate *locating* from *thinking*: the cheap search may examine many
partitions without LLM calls.

**Declared scope limit**: K=2 artificial partitions per case test the
**mechanism**, not call savings with the four real groups; the companion
`docs/SHADOW_ROUTING_ADDENDUM.md` measures the real data only at `met:true`.

## 1. The map (declared)

Per partition, a **term index with pointers**: every token of the
partition's records maps to the record ids (and their dates) where it
occurs - a projection rebuilt from the tape, never a summary that must be
"correct". Map search = product BM25 of the question against the
partition's record texts; partition score = the best record score inside it
(ties by partition order).

## 2. Arms

- **A0 all** - both partitions (baseline).
- **A1 map top-1** - the partition with the best map score.
- **A3 map + tape verification** - consult partitions in map order until the
  question-token coverage of the consulted texts reaches **tau = 0.5** or
  **K_max = 3** partitions were consulted (whichever first). Covering tokens
  is a **stopping hypothesis**, not proof of evidence: gates L1/L3 are the
  decisive tests.
- **A2 map ∪ tape top-3** - A1 plus the partitions hosting the lexical top-3
  records (reference from the previous line).

## 3. Metrics and gates

Per case: routing coverage (required records hosted by the consulted
partitions), partitions consulted. Gates:

- **L1** no case lost: coverage(A3) == coverage(A0) per case.
- **L2** fewer activations: total consulted(A3) < total consulted(A0).
- **L3** verification economy: total consulted(A3) <= total consulted(A2).
- **L4** determinism (two runs equal).
- **L5** every map entry carries pointers (term -> record ids with dates).

`all_pass` = L1-L5. Delivery/routing only: no answer gate (the previous
answer pipeline sat at the floor). Nothing is promoted; windows OFF; the
shadow window is untouched.

## 4. Execution protocol

Harness `eval/agent_map_v1.py` reusing the frozen `agent_index_v1` fixture;
outputs `eval/results/agent_map_v1/{report.json,report.md}`;
`tests/test_agent_map_v1.py`; proof regenerated; execution record appended;
committed together with the companion shadow addendum.

## Execution record (2026-09-23)

Deterministic, 27 cases.

| arm | routing coverage | consulted partitions |
|---|---:|---:|
| A0 all | 1.0000 | 54 |
| A1 map top-1 | **0.6728** | 27 |
| A2 map ∪ tape top-3 | 1.0000 | 54 |
| **A3 map + verification (tau=0.5, K_max=3)** | **0.7469** | **29** |

Gates: **L1 false**; L2 true (29 < 54); L3 true (29 <= 54); L4 true; L5
true; `all_pass` false.

Findings:

- **The verifiable map beats the summary digest at top-1**: coverage 0.6728
  vs the digest arm's 0.5321 (M0364) - pointers to records locate evidence
  better than a term label, supporting the map-over-label mechanism.
- **The token-coverage stopping rule (tau = 0.5) is refuted as an
  evidence-preserving rule in this lab**: it stopped after ~1.07 partitions
  on average, saving activations (29 vs 54) but losing a quarter of the
  coverage (0.7469 < 1.0). This is exactly the pre-declared caution: the
  threshold can be satisfied without the evidence. Per instruction, no
  re-fit; **L1 is the decisive gate and it fails**.
- Named next hypothesis (new pre-registration required): an evidence-seeking
  stopping rule (e.g., map-score plateau/margin, or bounded direct-tape
  rescue per recall) instead of question-token coverage.
- **No promotion; windows OFF; the shadow window is untouched.** Scope
  limit restated: K=2 artificial partitions test the mechanism, not real
  (4-group) economy; that measurement is the companion addendum's job at
  `met: true` (its S1 mirrors L1 and will test tau on real data).
