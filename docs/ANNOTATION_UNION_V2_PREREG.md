# annotation-union-v2 — pre-registration (hypothesis 2: offer A ∪ L5 to the agents)

Status: **frozen before execution**. Date: 2026-09-22. Track: synthetic lab.

Basis (`annotation-coverage-v1`, M0345): the annotations cover 0.8226 of the
62 required records, L5 covers 0.9355, and the union A ∪ L5 covers 0.9839
(61/62); the undue proxy is 14 non-required candidates across 30 cases.
Input-list coverage alone does **not** prove the agents will use the added
records - this experiment measures the **final annotations** under repeated
runs. u3a-18/M0018 remains a lexical gap outside the union; the W4 money
holdout stays independent.

## 1. Arms (same prompt, same model, temperature 0, N=3)

- **A (control)**: candidate list = the frozen annotated ids (`agent_ids`).
- **U (candidate)**: candidate list = `agent_ids` ∪ lexical top-5 (L5, same
  deterministic computation as M0345).

## 2. Frozen prompt (mirrors the product's agent contract)

```
You are a memory agent. You watch a set of persistent memory records.

Your memories (only these; never invent others):

{records}

Question: {question}

Identify which of YOUR memories MUST be remembered for the current work and
annotate them.

Return ONLY a JSON object, nothing else:

{"annotations":[{"memory_id":"M0001","note":"<why this matters now>","relevance":0.0}]}

Rules:
- Only annotate memory ids that appear in YOUR list above.
- relevance is a number from 0.0 (marginal) to 1.0 (critical).
- If nothing must be remembered, return "annotations":[].
```

`{records}` lists each candidate as `[id | type] summary + why` truncated to
400 characters (declared); candidates are shuffled? No - order is declared:
the arm's list order (A order = snapshot order; U = A followed by the new L5
ids in rank order) so the experiment is reproducible.

## 3. Metrics (per run, per case; declared)

- **coverage** = |required ∩ output ids| / |required| (required restricted to
  fixture records), missing required ids and recovered misses recorded;
- **undue** = |output ids not in required| (annotations of non-required
  records);
- aggregates over 30 cases x 3 runs: mean coverage per arm, total undue per
  arm, per-case modal coverage difference, the u3a-17 row.

## 4. Gates

- **H2-1** mean coverage(U) > mean coverage(A).
- **H2-2** undue(U) <= undue(A) + 10 (aggregate over the 30 cases, mean over
  runs) - bounded noise for the 14 added candidates.
- **H2-3** u3a-17: M0043 annotated in >= 2/3 runs under U.
- **H2-4** infrastructure failures <= 20%.

`all_pass` = H2-1..H2-4. Any failure: report, no re-fit; a pass is lab-only
and prepares (never promotes) an off-by-default product design; windows
remain OFF and the W4 holdout is untouched.

## 5. Execution protocol

Harness `eval/annotation_union_v2.py`, outputs
`eval/results/annotation_union_v2/{report.json,report.md}`,
`tests/test_annotation_union_v2.py` (recorded report only; recompute skips
without snapshots/key), proof regenerated, execution record appended,
committed. Cost cap: 30 cases x 2 arms x 3 runs = 180 calls.

## Execution record (2026-09-22)

180 calls (30 cases x 2 arms x 3 runs), 0 infrastructure failures.

| arm | mean coverage | undue/case |
|---|---:|---:|
| A (annotated list) | 0.486 | 0.044 |
| **U (A ∪ L5)** | **0.539** | 0.067 |

- recovered required under U (all runs): **9**;
- **u3a-17: M0043 annotated 0/3 under U** even when offered.

Gates: H2-1 **true** (coverage improves, modestly); H2-2 **true** (undue
bounded); **H2-3 false**; H2-4 true; `all_pass` false.

Findings:

- **Input-list coverage does not transfer**: the union covers 0.984 of the
  required input records, but the agents' final coverage is only 0.539 - the
  annotation step remains the bottleneck, and offering candidates helps only
  marginally (0.486 -> 0.539).
- **The u3a-17 failure is mechanical, verified post-hoc (not gated)**: the
  answering fact sits at character **6,927 of 15,244** in M0043, while the
  agent sees only the first **400 characters** per candidate - the excerpt
  does not contain "over a year". Offering the record cannot help when the
  text window hides the fact.
- Named next hypotheses (no changes made): (a) a **question-windowed
  per-candidate excerpt** shown to the agents (instead of the head 400),
  pre-registered with N=3 on the same cases; (b) if (a) recovers M0043, the
  combined **union + window** design becomes the candidate. The W4 money
  holdout remains independent; windows OFF; nothing promoted.
