"""Ingest attached .txt files onto the tape as labeled chunk memories.

Attachments are an explicit, labeled exception to the "external context never
touches the tape" rule: the text is intentionally memorized so the memory
agents can recall it. Each chunk becomes a record of type ``attachment`` whose
summary says it is an attached text.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from .groups import Manifest, add_memory
from .retrieval import chunk_text
from .secrets import SecretError
from .tape import MemoryRecord, Tape

DEFAULT_CHUNK_SIZE = 600


def _file_hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8", errors="replace")).hexdigest()[:12]


def ingest_attachment(
    tape: Tape,
    manifest: Manifest,
    path: str | Path,
    *,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    model: str = "",
) -> dict[str, Any]:
    """Split a .txt file into chunks and append each as an ``attachment`` record."""
    p = Path(path).expanduser()
    if not p.exists() or p.suffix.lower() != ".txt":
        return {"ok": False, "error": "only existing .txt files are supported"}

    text = p.read_text(encoding="utf-8", errors="replace")
    chunks = chunk_text(text, size=chunk_size)
    if not chunks:
        return {"ok": False, "error": "empty file"}

    source = f"{p.name}#{_file_hash(text)}"
    if any(r.source == source for r in tape.read()):
        return {
            "ok": True,
            "skipped": True,
            "reason": "already attached",
            "source": source,
            "chunks": len(chunks),
        }

    saved: list[dict[str, Any]] = []
    skipped_secrets = 0
    new_agents = 0
    for i, chunk in enumerate(chunks, start=1):
        rec = MemoryRecord(
            type="attachment",
            summary=f'Attached text "{p.name}" — chunk {i}/{len(chunks)}',
            why=chunk,
            files=[str(p)],
            source=source,
        )
        try:
            rec, _group, _agent, created = add_memory(tape, manifest, rec, model=model)
        except SecretError:
            skipped_secrets += 1
            continue
        saved.append(rec.to_dict())
        if created:
            new_agents += 1

    return {
        "ok": True,
        "source": source,
        "chunks": len(chunks),
        "saved": len(saved),
        "skipped_secrets": skipped_secrets,
        "new_agents": new_agents,
        "memories": saved,
    }
