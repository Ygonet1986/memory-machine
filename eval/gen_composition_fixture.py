#!/usr/bin/env python3
"""E0 — build the committed composition fixture from the volatile U3 roots.

Reads the frozen U3 artifacts once and writes a self-contained, byte-stable
fixture under ``eval/fixtures/composition_u4/``:

  cases.jsonl    one row per case: block, case, cat, question, gold (reference,
                 measurement only), required_ids, and the frozen control arm
                 (graph_augment_precise): context, payload_ids (candidate order
                 preserved), payload_chars, verdict.
  records.jsonl  the verbatim tape records needed by E1 (required memories) and
                 E2 (payload candidates): id, type, status, created_at,
                 summary, why, derived_from, source, views, files, why_sha1.
  manifest.json  counts, file digests, source roots/snapshots + digests,
                 builder version and the E0 guard notes.

The fixture is generated once and committed; E1/E2 never read the /tmp roots.

Run: PYTHONPATH=src python3 eval/gen_composition_fixture.py [--out DIR]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "src"))

TMP = Path("/var/folders/3z/9n8mh2p12ld771wy19z5v7rw0000gn/T")
BLOCKS = {
    "u3a": {
        "root": TMP / "mm-graph-shared-wnps8c6d",
        "snapshot": HERE / "graph_out" / "u_diag_longmemeval_u3a.jsonl",
    },
    "u3b": {
        "root": TMP / "mm-graph-shared-7ggare_r",
        "snapshot": HERE / "graph_out" / "u_diag_longmemeval_u3b.jsonl",
    },
}
CONTROL_ARM = "graph_augment_precise"
RECORD_FIELDS = (
    "id", "type", "status", "created_at", "summary", "why",
    "derived_from", "source", "views", "files",
)


def sha1_bytes(blob: bytes) -> str:
    return hashlib.sha1(blob).hexdigest()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rows_of(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def stream_records(path: Path) -> dict[str, dict[str, Any]]:
    """Records by id, tolerant to pretty-printed multi-line JSON objects.

    Two U3 tapes (cases 18, 40) store records as concatenated multi-line JSON
    objects, so a line-based JSONL read is not enough; ``raw_decode`` walks
    the stream and recovers every object.
    """
    text = path.read_text(encoding="utf-8")
    decoder = json.JSONDecoder()
    out: dict[str, dict[str, Any]] = {}
    pos = 0
    while pos < len(text):
        while pos < len(text) and text[pos] in " \t\r\n":
            pos += 1
        if pos >= len(text):
            break
        obj, pos = decoder.raw_decode(text, pos)
        out[obj["id"]] = obj
    return out


def verify(fixtures: Path) -> int:
    """Cross-check the fixture against the (still present) U3 sources.

    Verifies, per case: fixture contexts byte-equal the frozen snapshots and
    every needed record's ``why`` sha1 byte-equals the source tape record.
    """
    cases = rows_of(fixtures / "cases.jsonl")
    records = {(row["case"], row["id"]): row for row in rows_of(fixtures / "records.jsonl")}
    failures: list[str] = []
    checked_records = 0
    for case in cases:
        block = case["block"]
        spec = BLOCKS[block]
        case_id = int(case["case"])
        snapshot_rows = {int(row["case"]): row for row in rows_of(spec["snapshot"])}
        source = snapshot_rows.get(case_id)
        if source is None:
            failures.append(f"case {case_id}: missing from snapshot")
            continue
        arm = source["arms"][CONTROL_ARM]
        if sha1_bytes(str(arm.get("context") or "").encode("utf-8")) != case["context_sha1"]:
            failures.append(f"case {case_id}: context differs from snapshot")
        tape = stream_records(spec["root"] / f"case_{case_id:02d}" / "tape.jsonl")
        for memory_id in set(case["required_ids"]) | set(case["payload_ids"]):
            fixture_record = records.get((case_id, memory_id))
            tape_record = tape.get(memory_id)
            if fixture_record is None or tape_record is None:
                failures.append(f"case {case_id}: record {memory_id} missing")
                continue
            why_sha = sha1_bytes(str(tape_record.get("why") or "").encode("utf-8"))
            if fixture_record["why_sha1"] != why_sha:
                failures.append(f"case {case_id}: why differs for {memory_id}")
            checked_records += 1
    print(f"verify: {len(cases)} cases, {checked_records} record checks, "
          f"failures {len(failures)}")
    for failure in failures[:10]:
        print(f"  FAIL {failure}")
    return 0 if not failures else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="eval/fixtures/composition_u4")
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    if args.verify:
        return verify(Path(args.out))
    out = Path(args.out)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    cases: list[dict[str, Any]] = []
    needed: dict[tuple[int, str], dict[str, Any]] = {}
    tapes: dict[int, dict[str, dict[str, Any]]] = {}
    for block, spec in BLOCKS.items():
        root: Path = spec["root"]
        snapshot: Path = spec["snapshot"]
        if not root.exists():
            raise SystemExit(f"source root missing (volatile /tmp): {root}")
        for row in rows_of(snapshot):
            case = int(row["case"])
            tape_records = tapes.get(case)
            if tape_records is None:
                tape_records = stream_records(root / f"case_{case:02d}" / "tape.jsonl")
                tapes[case] = tape_records
            arm = row["arms"][CONTROL_ARM]
            payload_ids = list(arm["payload_ids"])
            cases.append(
                {
                    "block": block,
                    "case": case,
                    "cat": row.get("cat", ""),
                    "question": row["question"],
                    "gold": row.get("gold", ""),
                    "required_ids": list(row["required_ids"]),
                    "payload_ids": payload_ids,
                    "payload_chars": int(arm.get("payload_chars") or 0),
                    "context_sha1": sha1_bytes(str(arm.get("context") or "").encode("utf-8")),
                    "context": arm.get("context") or "",
                    "verdict_precise": arm.get("verdict", ""),
                }
            )
            for memory_id in set(row["required_ids"]) | set(payload_ids):
                if (case, memory_id) in needed:
                    continue
                if memory_id not in tape_records:
                    raise SystemExit(f"case {case}: record {memory_id} not on tape")
                record = tape_records[memory_id]
                entry = {key: record.get(key) for key in RECORD_FIELDS}
                entry["case"] = case
                entry["why_sha1"] = sha1_bytes(str(record.get("why") or "").encode("utf-8"))
                needed[(case, memory_id)] = entry

    records = [needed[key] for key in sorted(needed)]
    cases_blob = "".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in cases
    ).encode("utf-8")
    records_blob = "".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in records
    ).encode("utf-8")
    (out / "cases.jsonl").write_bytes(cases_blob)
    (out / "records.jsonl").write_bytes(records_blob)

    manifest = {
        "builder": "eval/gen_composition_fixture.py",
        "version": 1,
        "sha1": sha1_bytes(cases_blob + records_blob),
        "blocks": {block: str(spec["root"]) for block, spec in BLOCKS.items()},
        "snapshots": {
            block: {"path": str(spec["snapshot"]), "sha256": sha256_file(spec["snapshot"])}
            for block, spec in BLOCKS.items()
        },
        "control_arm": CONTROL_ARM,
        "cases": len(cases),
        "records": len(records),
        "files": {
            "cases.jsonl": sha256_file(out / "cases.jsonl"),
            "records.jsonl": sha256_file(out / "records.jsonl"),
        },
        "guards": {
            "atoms_exact_substrings": True,
            "offsets_reversible": True,
            "selection_reads_no_gold": True,
            "card_rules_frozen_before_e1": "docs/COMPOSITION_V1.md",
        },
    }
    (out / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"fixture: {out} | cases {len(cases)} | records {len(records)} | "
          f"sha1 {manifest['sha1']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
