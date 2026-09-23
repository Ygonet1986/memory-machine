#!/usr/bin/env python3
"""Deterministic generator: agent partitions + metadata digests (K=2 per case).

Frozen by docs/AGENT_INDEX_V1_PREREG.md. For each frozen case (snapshots +
fixture records), split the records into two partitions by created_at and
build a digest with provenance (term -> source records, dates, confidence).
Planted-omission checks are computed here (A1_miss / A2_recover counts).

    PYTHONPATH=src:.:eval python3 eval/gen_agent_partitions_v1.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "src"))

import delivery_combined_v1 as dc  # noqa: E402
from memory_machine.retrieval import bm25, tokenize  # noqa: E402

MAX_TERMS = 12
DATE_RE = None


def _import_date_re():
    global DATE_RE
    if DATE_RE is None:
        import re
        DATE_RE = re.compile(
            r"\b(?:\d{4}-\d{2}-\d{2}|(?:19|20)\d{2})\b"
            r"|\b(?:january|february|march|april|may|june|july|august|"
            r"september|october|november|december)\b", re.IGNORECASE)
    return DATE_RE


def load_snapshots() -> list[dict[str, Any]]:
    rows = []
    for name in ("u3a", "u3b"):
        path = HERE / "graph_out" / f"u_diag_longmemeval_{name}.jsonl"
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                row["block"] = name
                rows.append(row)
    return rows


def build_partitions() -> list[dict[str, Any]]:
    snapshots = load_snapshots()
    cases, records = dc.load_fixture(HERE / "fixtures" / "composition_u4")
    case_map = {(c["block"], c["case"]): c for c in cases}
    built = []
    for snap in snapshots:
        case = case_map.get((snap["block"], snap["case"]))
        if case is None:
            continue
        case_records = sorted(
            (r for (c, _), r in records.items() if c == snap["case"]),
            key=lambda r: (r["created_at"], r["id"]))
        if len(case_records) < 2:
            continue
        half = len(case_records) // 2
        halves = [case_records[:half], case_records[half:]]
        parts = []
        for number, group in enumerate(halves):
            part_id = f'{snap["block"]}{snap["case"]}-P{number + 1}'
            parts.append({
                "partition_id": part_id,
                "record_ids": [r["id"] for r in group],
                "dates": sorted({r["created_at"][:10] for r in group}),
            })
        built.append({
            "block": snap["block"], "case": snap["case"],
            "question": snap["question"],
            "required": [mid for mid in snap["required_ids"]
                         if any(r["id"] == mid for r in case_records)],
            "partitions": parts,
        })
    return built


def _digest(case: dict[str, Any], records: dict[tuple[int, str], dict]
            ) -> list[dict[str, Any]]:
    date_re = _import_date_re()
    corpus = []
    for part in case["partitions"]:
        text = " ".join(f"{records[(case['case'], rid)]['summary']} "
                        f"{records[(case['case'], rid)]['why']}"
                        for rid in part["record_ids"])
        corpus.append(tokenize(text))
    total = len(corpus)
    df: dict[str, int] = {}
    for tokens in corpus:
        for token in set(tokens):
            df[token] = df.get(token, 0) + 1
    digests = []
    for part, tokens in zip(case["partitions"], corpus):
        tf: dict[str, int] = {}
        for token in tokens:
            tf[token] = tf.get(token, 0) + 1
        scored = []
        for token, count in tf.items():
            idf = math.log((total + 1) / (df.get(token, 0) + 1)) + 1.0
            scored.append((token, count * idf, idf))
        scored.sort(key=lambda item: (-item[1], item[0]))
        entries = []
        for token, score, idf in scored[:MAX_TERMS]:
            sources = []
            for rid in part["record_ids"]:
                record = records[(case["case"], rid)]
                text = f"{record['summary']} {record['why']}"
                if token in set(tokenize(text)):
                    sources.append({"memory_id": rid,
                                    "date": record["created_at"][:10]})
            entries.append({"term": token, "confidence": round(idf, 4),
                            "sources": sources})
        entities = sorted({
            word for rid in part["record_ids"]
            for word in (records[(case["case"], rid)]["summary"] or "").split()
            if word[:1].isupper() and len(word) > 2})[:8]
        dates = sorted({
            match.group(0).lower()
            for rid in part["record_ids"]
            for match in date_re.finditer(
                f"{records[(case['case'], rid)]['summary']} "
                f"{records[(case['case'], rid)]['why']}")})
        digests.append({"partition_id": part["partition_id"],
                        "terms": entries, "entities": entities,
                        "dates": dates[:8]})
    return digests


def digest_score(question: str, digest: dict[str, Any]) -> float:
    q_tokens = set(tokenize(question))
    return round(sum(entry["confidence"] for entry in digest["terms"]
                     if entry["term"] in q_tokens), 4)


def routing_checks(case: dict[str, Any], digests: list[dict[str, Any]],
                   records: dict[tuple[int, str], dict]) -> dict[str, Any]:
    required = set(case["required"])
    scores = [(digest_score(case["question"], d), index, d["partition_id"])
              for index, d in enumerate(digests)]
    scores.sort(key=lambda item: (-item[0], item[1]))
    top1_id = scores[0][2]
    top1_records = set(next(p["record_ids"] for p in case["partitions"]
                            if p["partition_id"] == top1_id))
    lexical_hits = bm25(case["question"], [
        f"{records[(case['case'], rid)]['summary']} "
        f"{records[(case['case'], rid)]['why']}"
        for part in case["partitions"] for rid in part["record_ids"]])
    flat = [(part["partition_id"], rid) for part in case["partitions"]
            for rid in part["record_ids"]]
    order = sorted(range(len(flat)), key=lambda i: -lexical_hits[i])
    lexical_partition = flat[order[0]][0]
    lexical_partitions = sorted({flat[i][0] for i in order[:3]})
    union_ids = {top1_id, *lexical_partitions}
    union_records = {rid for part in case["partitions"]
                     if part["partition_id"] in union_ids
                     for rid in part["record_ids"]}
    return {
        "digest_scores": [{"partition_id": pid, "score": score}
                          for score, _index, pid in scores],
        "top1_partition": top1_id,
        "lexical_partition": lexical_partition,
        "lexical_partitions_top3": lexical_partitions,
        "a1_miss": not required.issubset(top1_records),
        "a2_recover": required.issubset(union_records),
    }


def generate(out_dir: Path) -> dict:
    cases = build_partitions()
    _cases, records = dc.load_fixture(HERE / "fixtures" / "composition_u4")
    rows = []
    a1_miss = a2_recover = 0
    for case in cases:
        digests = _digest(case, records)
        checks = routing_checks(case, digests, records)
        a1_miss += 1 if checks["a1_miss"] else 0
        a2_recover += 1 if checks["a2_recover"] else 0
        rows.append({**case, "digests": digests, "checks": checks})
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
                      for row in rows)
    (out_dir / "cases.jsonl").write_text(payload, encoding="utf-8")
    manifest = {
        "generator": "gen_agent_partitions_v1.py",
        "generator_version": 1,
        "cases": len(rows),
        "partitions_per_case": 2,
        "a1_miss_cases": a1_miss,
        "a2_recover_cases": a2_recover,
        "cases_sha256": hashlib.sha256(payload.encode("utf-8")).hexdigest(),
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="eval/fixtures/agent_index_v1")
    args = parser.parse_args()
    print(json.dumps(generate(Path(args.out)), indent=2, ensure_ascii=False,
                     sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
