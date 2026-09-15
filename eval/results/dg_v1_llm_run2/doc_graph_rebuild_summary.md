# doc-graph-v1 rebuild fidelity — summary

**Decision:** `FAIL`  ·  extractor {'name': 'llm', 'version': 'v1'}
**Params:** {'chunk_size': 400, 'overlap': 50, 'level': 'both', 'window_chars': 12000, 'batch_size': 4}

## Deterministic audit (D1–D8)

### O: clean
- check: {'D1_tape_bytes': 4752, 'D3_validate': 'clean', 'D2_registry_rows': 3}

### A: clean
- check: {'D1_tape_bytes': 4752, 'D3_validate': 'clean', 'D2_registry_rows': 3}

### B: clean
- check: {'D1_tape_bytes': 4752, 'D3_validate': 'clean', 'D2_registry_rows': 3}

**Structural identity (fake arm must be empty): ['entities', 'relations', 'mentions']**

## Semantic Δ matrix (1 − Jaccard)

| metric | Δ(O,A) | Δ(O,B) | Δ(A,B) |
|---|---:|---:|---:|
| entities | 0.3832 | 0.5537 | 0.5763 |
| relations | 0.9417 | 0.9531 | 0.9899 |
| relations_plural | 0.9417 | 0.9453 | 0.9899 |
| windows | 0.1429 | 0.4138 | 0.4068 |
| chunks | 0.1747 | 0.0471 | 0.2047 |
| per_doc_type | 0.1596 | 0.2051 | 0.1935 |
| evidence | 0.8960 | 0.9059 | 1.0000 |

**Evidence coverage (S3' — O-anchored units A↔B denominator |evidence_O|):**
- OA: distance 0.896, recall 0.104 over 202 O-anchored units (missing 0/181)
- OB: distance 0.9059, recall 0.0941 over 202 O-anchored units (missing 0/183)
- AB: distance 1.0, recall 0.0 over 202 O-anchored units (missing 181/183)

## Extraction health

| arm | pending | failed |
|---|---:|---:|
| O | 0 | 0 |
| A | 0 | 0 |
| B | 0 | 0 |

**Ordering failures (A↔B must be ≤ max(O↔A, O↔B)): ['entities', 'relations', 'relations_plural', 'chunks', 'evidence']**

**Reason:** {'deterministic_clean': True, 'rebuild_ok': True, 'tape_unaltered': True, 'extraction_health': True, 'abor_b_ordering': False}
