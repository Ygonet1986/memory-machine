"""Document (RAG) store: .txt reference material retrieved by BM25.

Documents are auxiliary reference context. They are retrieved for the current
question and handed to the main chatbot only — they never touch the tape, the
whiteboard, or the memory agents.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from .retrieval import chunk_text, rank

CHUNK_SIZE = 1200
CHUNK_OVERLAP = 200


def documents_dir(base: Path) -> Path:
    return base / "documents"


def add_document(base: Path, src: Path) -> dict[str, Any]:
    src = Path(src)
    if not src.exists() or src.suffix.lower() != ".txt":
        return {"ok": False, "error": "only .txt files are supported"}
    dest_dir = documents_dir(base)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / src.name
    n = 2
    while dest.exists():
        dest = dest_dir / f"{src.stem}-{n}.txt"
        n += 1
    shutil.copy2(src, dest)
    return {"ok": True, "name": dest.name, "path": str(dest)}


def list_documents(base: Path) -> list[dict[str, Any]]:
    d = documents_dir(base)
    if not d.exists():
        return []
    return [{"name": f.name, "size": f.stat().st_size} for f in sorted(d.glob("*.txt"))]


def remove_document(base: Path, name: str) -> bool:
    f = documents_dir(base) / name
    if f.exists() and f.is_file():
        f.unlink()
        return True
    return False


def remove_all_documents(base: Path) -> int:
    """Delete every stored document. Returns the number of files removed."""
    d = documents_dir(base)
    if not d.exists():
        return 0
    removed = 0
    for f in sorted(d.glob("*.txt")):
        f.unlink()
        removed += 1
    return removed


def _chunks(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    return chunk_text(text, size=size, overlap=overlap)


def retrieve(base: Path, query: str, *, top_k: int = 4, budget: int = 4000) -> str:
    """Return the most relevant chunks across all documents, formatted."""
    d = documents_dir(base)
    if not d.exists():
        return ""

    chunks: list[tuple[str, str]] = []  # (doc_name, chunk)
    for f in d.glob("*.txt"):
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for chunk in _chunks(text):
            chunks.append((f.name, chunk))
    if not chunks:
        return ""

    ranked = rank(query, [c[1] for c in chunks], limit=top_k * 4)

    blocks: list[str] = []
    used = 0
    for i, _score in ranked:
        name, chunk = chunks[i]
        block = f"[{name}]\n{chunk.strip()}"
        cost = len(block) + 4
        if blocks and used + cost > budget:
            break
        blocks.append(block)
        used += cost
        if len(blocks) >= top_k:
            break
    return "\n\n".join(blocks)
