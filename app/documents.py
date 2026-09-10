"""Document (RAG) store: .txt reference material retrieved by keyword.

Documents are auxiliary reference context. They are retrieved for the current
question and handed to the main chatbot only — they never touch the tape, the
whiteboard, or the memory agents. Retrieval is deterministic keyword scoring
(no embeddings, no external service).
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any

STOPWORDS = {
    "the", "and", "for", "are", "was", "what", "did", "we", "about", "using",
    "with", "that", "our", "this", "you", "how", "why", "not", "can", "all",
    "from", "have", "has", "will", "would", "should", "there", "they", "your",
}

CHUNK_SIZE = 1200
CHUNK_OVERLAP = 200


def documents_dir(base: Path) -> Path:
    return base / "documents"


def _tokenize(text: str) -> list[str]:
    toks = re.findall(r"[a-z0-9]+", text.lower())
    return [t for t in toks if len(t) > 2 and t not in STOPWORDS]


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
    out = []
    for f in sorted(d.glob("*.txt")):
        out.append({"name": f.name, "size": f.stat().st_size})
    return out


def remove_document(base: Path, name: str) -> bool:
    f = documents_dir(base) / name
    if f.exists() and f.is_file():
        f.unlink()
        return True
    return False


def _chunks(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    text = text.strip()
    if not text:
        return []
    if len(text) <= size:
        return [text]
    out: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        out.append(text[start:end])
        if end == len(text):
            break
        start = end - overlap
    return out


def retrieve(
    base: Path,
    query: str,
    *,
    top_k: int = 4,
    budget: int = 4000,
) -> str:
    """Return the most relevant chunks across all documents, formatted."""
    d = documents_dir(base)
    if not d.exists():
        return ""
    q_tokens = _tokenize(query)
    if not q_tokens:
        return ""

    scored: list[tuple[float, str, str]] = []  # (score, doc_name, chunk)
    for f in d.glob("*.txt"):
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for chunk in _chunks(text):
            chunk_tokens = set(_tokenize(chunk))
            score = float(sum(1 for t in q_tokens if t in chunk_tokens))
            if score > 0:
                scored.append((score, f.name, chunk))

    scored.sort(key=lambda x: (-x[0], x[1]))

    blocks: list[str] = []
    used = 0
    for score, name, chunk in scored[: top_k * 4]:
        block = f"[{name}]\n{chunk.strip()}"
        cost = len(block) + 4
        if blocks and used + cost > budget:
            break
        blocks.append(block)
        used += cost
        if len(blocks) >= top_k:
            break
    return "\n\n".join(blocks)
