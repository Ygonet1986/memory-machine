# doc-graph-v1 rebuild fidelity — summary

**Decision:** `FAIL`  ·  extractor {'name': 'llm', 'version': 'v1'}
**Params:** {'chunk_size': 400, 'overlap': 50, 'level': 'both', 'window_chars': 12000, 'batch_size': 4}

## Deterministic audit (D1–D8)

### O: clean
- check: {'D1_tape_bytes': 4722, 'D3_validate': 'clean', 'D2_registry_rows': 3}

### A: clean
- check: {'D1_tape_bytes': 4722, 'D3_validate': 'clean', 'D2_registry_rows': 3}

### B: clean
- check: {'D1_tape_bytes': 4722, 'D3_validate': 'clean', 'D2_registry_rows': 3}

**Structural identity (fake arm must be empty): ['entities', 'relations', 'mentions']**

## Semantic Δ matrix (1 − Jaccard)

| metric | Δ(O,A) | Δ(O,B) | Δ(A,B) |
|---|---:|---:|---:|
| entities | 0.5205 | 0.6828 | 0.5923 |
| relations | 0.9762 | 0.9807 | 0.9398 |
| relations_plural | 0.9762 | 0.9807 | 0.9398 |
| windows | 0.3023 | 0.3023 | 0.0889 |
| chunks | 0.1641 | 0.1865 | 0.1368 |
| per_doc_type | 0.2304 | 0.2172 | 0.1970 |
| evidence | 0.0000 | 0.0000 | 0.0400 |

**Evidence coverage (S3, recall / aligned):**
- OA: recall 1.0 (10 eligible of 10 aligned)
- OB: recall 1.0 (8 eligible of 8 aligned)
- AB: recall 0.96 (25 eligible of 25 aligned)

## Extraction health

| arm | pending | failed |
|---|---:|---:|
| O | 0 | 0 |
| A | 0 | 0 |
| B | 0 | 0 |

**Ordering failures (A↔B must be ≤ max(O↔A, O↔B)): ['evidence']**

**Reason:** {'deterministic_clean': True, 'rebuild_ok': True, 'tape_unaltered': True, 'extraction_health': True, 'abor_b_ordering': False}
