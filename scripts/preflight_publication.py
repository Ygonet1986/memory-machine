#!/usr/bin/env python3
"""Preflight before publishing the repository (history-wide, not just HEAD).

Scans every blob in every commit for secrets and personal/restricted files,
checks .gitignore, license/authorship and that PR workflows carry no secrets.

    python3 scripts/preflight_publication.py [--root .]

Exit 0 = clear to publish; 1 = critical findings (do not publish).
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from memory_machine.secrets import scan_text  # noqa: E402

# Personal / restricted file patterns that must never be versioned.
FORBIDDEN_NAMES = re.compile(
    r"(^|/)(\.env(\..*)?|settings\.json|credentials(\..*)?|id_rsa|id_ed25519|"
    r".*\.pem|.*\.key|\.netrc|\.aws/.*|\.ssh/.*)$",
    re.IGNORECASE,
)
# History-only personal data (removed from HEAD) that matters for *public*
# publication; accepted for a private first push via --accept-private-history.
PRIVATE_HISTORY_PATHS = re.compile(
    r"(^|/)(\.opencode/|\.config/opencode/|MemoryMachine/data/|sessions/)",
    re.IGNORECASE,
)
FORBIDDEN_PATHS = re.compile(
    r"(^|/)(eval/data/|MemoryMachine/data/)",
    re.IGNORECASE,
)
# Strings that are canonical test fixtures, reviewed and accepted.
FIXTURE_STRINGS = (
    "sk-abcdefghijklmnopqrstuvwxyz123456",
    "Bearer abcdefghijklmnopqrstuvwxyz012345",
    "-----BEGIN RSA PRIVATE KEY-----",
)
LARGE_BLOB_BYTES = 5 * 1024 * 1024
TEXT_SUFFIXES = {
    ".py", ".md", ".txt", ".json", ".jsonl", ".toml", ".yml", ".yaml", ".sh",
    ".ts", ".cfg", ".ini", ".example", ".spec", ".cff", ".mjs", ".js",
}
REQUIRED_GITIGNORE = [".env", ".venv/", "eval/data/", "dist/", "build/",
                      "__pycache__/"]


def git(*args: str) -> str:
    result = subprocess.run(["git", *args], cwd=ROOT, capture_output=True,
                            text=True, check=True)
    return result.stdout


def git_bytes(*args: str) -> bytes:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True,
                          check=True).stdout


BINARY_SUFFIXES = {".icns", ".png", ".ico", ".jpg", ".jpeg", ".gif", ".pdf",
                   ".dmg", ".whl", ".pyc", ".wav", ".mp3", ".zip", ".gz"}


def is_text_candidate(path: str, size: int) -> bool:
    suffix = Path(path).suffix.lower()
    if suffix in BINARY_SUFFIXES:
        return False
    if suffix in TEXT_SUFFIXES:
        return True
    return "/" not in path and not suffix and size <= 1_000_000


def blobs() -> dict[str, list[str]]:
    """All blob shas in all commits, mapped to the paths that used them."""
    out: dict[str, list[str]] = {}
    for line in git("rev-list", "--objects", "--all").splitlines():
        sha, _, path = line.partition(" ")
        if not path:
            continue
        out.setdefault(sha, []).append(path)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--accept-private-history", action="store_true",
        help="accepted findings that only matter for public publication "
             "(private first push); they are reported but do not fail")
    args = parser.parse_args()

    findings: list[str] = []
    accepted: list[str] = []
    warnings: list[str] = []

    # 1. secret scan over every blob in history + every commit message
    seen_text = 0
    for sha, paths in blobs().items():
        size = int(git("cat-file", "-s", sha).strip())
        path = paths[0]
        if size <= LARGE_BLOB_BYTES and is_text_candidate(path, size):
            try:
                content = git_bytes("cat-file", "blob", sha).decode(
                    "utf-8", errors="replace")
            except subprocess.CalledProcessError:
                continue
            seen_text += 1
            for rule in scan_text(content):
                message = f"secret [{rule}] in blob {sha[:10]} ({path})"
                if path.startswith("tests/") and any(
                        fixture in content for fixture in FIXTURE_STRINGS):
                    accepted.append(f"test fixture: {message}")
                else:
                    findings.append(message)
        if size > LARGE_BLOB_BYTES:
            warnings.append(f"large blob {size // 1024 // 1024}MB: {path} ({sha[:10]})")
    for rule in scan_text(git("log", "--all", "--format=%B")):
        findings.append(f"secret [{rule}] in a commit message")

    # 2. forbidden file names/paths anywhere in history
    for sha, paths in blobs().items():
        for path in paths:
            if FORBIDDEN_NAMES.search(path) or FORBIDDEN_PATHS.search(path):
                findings.append(f"forbidden path in history: {path}")
                break
            if PRIVATE_HISTORY_PATHS.search(path):
                accepted.append(f"history-only personal data: {path}")
                break

    # 3. .gitignore coverage (current tree)
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    for entry in REQUIRED_GITIGNORE:
        if entry not in gitignore.splitlines():
            warnings.append(f".gitignore missing entry: {entry}")

    # 4. license and authorship
    license_path = ROOT / "LICENSE"
    if not license_path.exists():
        findings.append("LICENSE missing")
    else:
        text = license_path.read_text(encoding="utf-8")
        if not text.startswith("MIT License"):
            findings.append("LICENSE is not MIT")
        if "Igor Coutrim Lacerda" not in text:
            warnings.append("LICENSE author line not found")

    # 5. PR workflow must not touch secrets
    ci = ROOT / ".github" / "workflows" / "ci.yml"
    if not ci.exists():
        findings.append(".github/workflows/ci.yml missing")
    elif re.search(r"secrets\.", ci.read_text(encoding="utf-8")):
        findings.append("ci.yml references secrets (must not, it runs on forks)")
    scientific = ROOT / ".github" / "workflows" / "scientific.yml"
    if scientific.exists() and "secrets." not in scientific.read_text(encoding="utf-8"):
        warnings.append("scientific.yml has no secrets (expected for live runs)")

    accepted = sorted(set(accepted))
    print(f"scanned {seen_text} text blobs across history")
    for warning in warnings:
        print(f"  WARN  {warning}")
    for item in accepted:
        label = "ACCEPTED" if args.accept_private_history else "REVIEW"
        print(f"  {label}  {item}")
    for finding in findings:
        print(f"  FAIL  {finding}")
    if findings:
        print(f"PREFLIGHT FAILED: {len(findings)} critical finding(s)")
        return 1
    if accepted and not args.accept_private_history:
        print(f"PREFLIGHT: {len(accepted)} reviewed finding(s) require a decision "
              f"(use --accept-private-history for a private first push)")
        return 1
    print("PREFLIGHT PASS: clear to publish")
    return 0


if __name__ == "__main__":
    sys.exit(main())
