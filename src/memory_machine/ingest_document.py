"""Document ingestion: tape -> registry -> graph (Graph Memory Machine, D3).

Commit order is strict and never reversed::

    TXT
     ↓
    Tape confirmed (chunk memories with ``source_document``/``source_span``)
     ↓
    Document registry confirmed (``D####`` in ``documents.jsonl``)
     ↓
    Graph extraction (chunk-level, provenance on every generated row)

The extractor runs last and its failures never undo or block the tape: it
reuses the pending/failed/retry policy of ``graph.apply_record_extraction`` /
``apply_batch_extraction``. When ``enable_graph`` is false (``--no-document-graph``)
the document is ingested into the tape only: no registry, no extraction.

``Machine.add_memory`` and ``ingest_attachment`` are intentionally untouched;
this path is the only place ``document_graph_enabled`` is consulted.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .attachments import _file_hash
from .graph import (
    GraphStore,
    _chunk_records,
    apply_batch_extraction,
    apply_record_extraction,
)
from .groups import Manifest, add_memory
from .retrieval import chunk_spans
from .secrets import SecretError
from .tape import MemoryRecord, Tape

DEFAULT_CHUNK_SIZE = 600
DEFAULT_CHUNK_OVERLAP = 100


def _file_spans(path: Path, chunk_size: int, overlap: int) -> tuple[str, list[tuple[int, int]]]:
    text = path.read_text(encoding="utf-8", errors="replace").strip()
    if not text:
        return "", []
    spans = [(start, end) for start, end, _ in chunk_spans(text, size=chunk_size, overlap=overlap)]
    return text, spans


def _source_records(tape: Tape, source: str) -> list[MemoryRecord]:
    return [r for r in tape.read() if r.source == source]


def _register_document(
    store: GraphStore,
    *,
    path: Path,
    source: str,
    hash: str,
    spans: list[tuple[int, int]],
    extractor: str,
) -> dict[str, Any] | None:
    """Register/refresh the ``D####`` row. Idempotent by ``source``."""
    if store is None:
        return None
    record, created = store.add_document(
        source=source,
        name=path.name,
        hash=hash,
        path=str(path),
        spans=spans,
        extractor=extractor,
        status="registered",
    )
    if created:
        store.update_document(record.id, extractor=extractor)
    return {"id": record.id, "source": record.source, "created": created}


def _run_extraction(
    store: GraphStore,
    records: list[MemoryRecord],
    extractor: Any,
    resolver: Any,
    *,
    extractor_name: str,
    extractor_version: str,
    batch_size: int,
    batch_max_chars: int,
    max_attempts: int,
) -> dict[str, Any]:
    """Project chunk records with the pending/failed/retry policy.

    Never raises for the caller: a projection failure only marks the affected
    records in the store and is reported in the result.
    """
    name = extractor_name or getattr(extractor, "name", "chunk")
    version = extractor_version or getattr(extractor, "version", "v1")
    tag = getattr(extractor, "tag", None) or f"{name}/{version}"
    applied = pending = failed = created_entities = mentions = 0
    try:
        for batch in _chunk_records(
            records, batch_size=max(1, int(batch_size)), batch_max_chars=int(batch_max_chars)
        ):
            if len(batch) == 1:
                outcome = apply_record_extraction(
                    store, batch[0], extractor.extract, tag=tag,
                    extractor_name=name, extractor_version=version,
                    resolver=resolver, max_attempts=max(1, int(max_attempts)),
                )
            else:
                outcome = apply_batch_extraction(
                    store, batch, extractor.extract_batch, tag=tag,
                    extractor_name=name, extractor_version=version,
                    resolver=resolver, max_attempts=max(1, int(max_attempts)),
                )
            status = str(outcome.get("status") or "")
            applied += int(outcome.get("applied") or 0) or int(status == "extracted")
            pending += int(outcome.get("pending") or 0) or int(status == "pending")
            failed += int(outcome.get("failed") or 0) or int(status == "failed")
            created_entities += int(outcome.get("created_entities") or 0)
            mentions += int(outcome.get("new_mentions") or outcome.get("entities") or 0)
    except Exception as exc:
        failed = len(records)
        for record in records:
            try:
                store.mark_failed(record.id, f"document projection error: {exc}", extractor=tag)
            except Exception:
                pass
    status = (
        "pending" if pending and not applied else
        "partial" if applied and (pending or failed) else
        "extracted" if applied else
        "failed" if failed else "registered"
    )
    return {
        "enabled": True,
        "status": status,
        "tag": tag,
        "applied": applied,
        "pending": pending,
        "failed": failed,
        "created_entities": created_entities,
        "new_mentions": mentions,
    }


def ingest_document(
    tape: Tape,
    manifest: Manifest,
    path: str | Path,
    *,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_CHUNK_OVERLAP,
    model: str = "",
    store: GraphStore | None = None,
    extractor: Any | None = None,
    resolver: Any | None = None,
    enable_graph: bool = True,
    extractor_name: str = "",
    extractor_version: str = "",
    batch_size: int = 8,
    batch_max_chars: int = 12000,
    max_attempts: int = 3,
) -> dict[str, Any]:
    """Ingest one .txt file through the tape -> registry -> graph pipeline.

    The tape is always committed first; the registry second; graph extraction
    is last and never propagates failures. Records use the same shape as
    ``ingest_attachment`` plus the optional D1 provenance fields.
    """
    p = Path(path).expanduser()
    if not p.exists() or p.suffix.lower() != ".txt":
        return {"ok": False, "error": "only existing .txt files are supported"}

    text, spans = _file_spans(p, chunk_size=chunk_size, overlap=overlap)
    if not spans:
        return {"ok": False, "error": "empty file"}

    source = f"{p.name}#{_file_hash(text)}"
    preexisting = _source_records(tape, source)

    # ---------------------------------------------------------------- tape
    saved: list[MemoryRecord] = []
    skipped_secrets = 0
    if not preexisting:
        for i, (start, end) in enumerate(spans, start=1):
            rec = MemoryRecord(
                type="attachment",
                summary=f'Attached document "{p.name}" — chunk {i}/{len(spans)}',
                why=text[start:end],
                files=[str(p)],
                source=source,
                source_document=source,
                source_span=(start, end),
            )
            try:
                rec, _group, _agent, _created = add_memory(tape, manifest, rec, model=model)
            except SecretError:
                skipped_secrets += 1
                continue
            saved.append(rec)

    # ------------------------------------------------------------- registry
    doc_ref = None
    if enable_graph and store is not None:
        doc_ref = _register_document(
            store, path=p, source=source, hash=_file_hash(text),
            spans=spans, extractor=extractor_name or "chunk",
        )
        if extractor is None:
            graph["status"] = "registered"  # tape+registry done, no transport

    # --------------------------------------------------------------- graph
    graph: dict[str, Any] = {"enabled": bool(enable_graph and store is not None)}
    if enable_graph and store is not None and extractor is not None:
        records = preexisting or saved
        if records:
            graph = _run_extraction(
                store, records, extractor, resolver,
                extractor_name=extractor_name, extractor_version=extractor_version,
                batch_size=batch_size, batch_max_chars=batch_max_chars,
                max_attempts=max_attempts,
            )
        if doc_ref is not None:
            store.update_document(doc_ref["id"], status=graph["status"], extractor=graph["tag"])

    return {
        "ok": True,
        "source": source,
        "name": p.name,
        "chunks": len(spans),
        "saved": len(saved),
        "skipped_secrets": skipped_secrets,
        "skipped": bool(preexisting),
        "document": doc_ref,
        "document_graph": graph,
    }