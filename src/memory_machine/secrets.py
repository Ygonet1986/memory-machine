"""Secret scanning for memory records.

Before anything is written to the tape, its content is scanned for secret-like
patterns (API keys, tokens, private keys). If a match is found, the write is
refused — no secrets may reach the long-term memory layer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


class SecretError(ValueError):
    """Raised when a memory record contains secret-like content."""


@dataclass
class ScanHit:
    rule: str
    excerpt: str


_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"sk-[A-Za-z0-9_-]{16,}"), "openai-style api key"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "private key"),
    (re.compile(r"AIza[0-9A-Za-z_-]{20,}"), "google api key"),
    (re.compile(r"AKIA[0-9A-Z]{16}"), "aws access key id"),
    (re.compile(r"ghp_[A-Za-z0-9]{30,}"), "github token"),
    (re.compile(r"Bearer\s+[A-Za-z0-9._~+/=-]{24,}", re.IGNORECASE), "bearer token"),
    (re.compile(r"eyJ[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,}"), "jwt"),
]


def scan_text(text: str) -> list[ScanHit]:
    hits: list[ScanHit] = []
    for pattern, rule in _PATTERNS:
        for m in pattern.finditer(text or ""):
            excerpt = m.group(0)
            if len(excerpt) > 40:
                excerpt = excerpt[:40] + "..."
            hits.append(ScanHit(rule=rule, excerpt=excerpt))
    return hits


def assert_clean(text: str) -> None:
    hits = scan_text(text)
    if hits:
        rules = ", ".join(sorted({h.rule for h in hits}))
        raise SecretError(f"secret-like content detected ({rules})")
