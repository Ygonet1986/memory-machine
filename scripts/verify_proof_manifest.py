#!/usr/bin/env python3
"""Anti-disappearance check for the conformance proof manifest (L10).

Every test node id recorded in ``docs/CONFORMANCE_PROOF.txt`` must still be
collected. New tests are allowed (additions are printed, not failures); a
missing expected node id fails the CI. The check never hardcodes a test count.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = ROOT / "docs" / "CONFORMANCE_PROOF.txt"


def collected_ids() -> set[str]:
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q"],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    if result.returncode not in (0, 5):  # 5 = no tests collected
        print(result.stdout)
        print(result.stderr, file=sys.stderr)
        raise SystemExit(f"FAIL: pytest --collect-only exited {result.returncode}")
    return {
        line.strip().split(" ")[0]
        for line in result.stdout.splitlines()
        if line.strip().startswith("tests/")
    }


def main() -> int:
    strict = "--strict" in sys.argv
    expected = {
        line.strip() for line in EXPECTED.read_text(encoding="utf-8").splitlines()
        if line.strip().startswith("tests/")
    }
    now = collected_ids()
    missing = sorted(expected - now)
    added = sorted(now - expected)
    print(f"expected={len(expected)} collected={len(now)} "
          f"missing={len(missing)} new={len(added)}")
    if added:
        print("new tests (allowed, consider regenerating the manifest):")
        for node in added:
            print(f"  + {node}")
    if missing:
        print("MISSING expected tests:")
        for node in missing:
            print(f"  - {node}")
        return 1
    if strict and added:
        print("FAIL (strict): collected tests are not in the committed manifest.")
        print("Regenerate docs/CONFORMANCE_PROOF.txt and commit it:")
        print("  python3 -m pytest --collect-only -q > docs/CONFORMANCE_PROOF.txt")
        return 1
    print("PASS: no expected test disappeared"
          + (" (strict: manifest is exact)" if strict else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
