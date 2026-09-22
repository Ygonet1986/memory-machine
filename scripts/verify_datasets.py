#!/usr/bin/env python3
"""Verify evaluation datasets by hash (L10 scientific CI).

Absent datasets are infrastructure (self-hosted runner/cache needed), not a
scientific failure; a hash mismatch is reported as infrastructure too, because
the run must not be trusted. Prints a final ``dataset_status=...`` marker for
the workflow. Exit code is 0 for verified/absent and 2 for mismatch.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "eval" / "DATASETS.sha256"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    if not MANIFEST.exists():
        print("INCONCLUSIVE_INFRASTRUCTURE: eval/DATASETS.sha256 missing")
        print("dataset_status=absent")
        return 0
    verified: list[str] = []
    absent: list[str] = []
    mismatched: list[str] = []
    for line in MANIFEST.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        digest, rel = line.split(None, 1)
        path = ROOT / rel.strip()
        if not path.exists():
            absent.append(rel.strip())
        elif sha256(path) != digest:
            mismatched.append(rel.strip())
        else:
            verified.append(rel.strip())
    if mismatched:
        print("INCONCLUSIVE_INFRASTRUCTURE: dataset hash mismatch (do not trust the run):")
        for rel in mismatched:
            print(f"  ! {rel}")
        print("dataset_status=mismatch")
        return 2
    if absent:
        print(f"INCONCLUSIVE_INFRASTRUCTURE: {len(absent)} dataset(s) absent "
              f"(self-hosted runner required): {', '.join(absent)}")
        print("dataset_status=absent")
        return 0
    print(f"PASS: {len(verified)} dataset(s) verified by sha256")
    print("dataset_status=verified")
    return 0


if __name__ == "__main__":
    sys.exit(main())
