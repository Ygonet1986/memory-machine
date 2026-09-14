"""Document ingestion: tape -> registry -> graph (Graph Memory Machine, D3/D4).

Commit order is strict and never reversed::

    TXT
     ↓
    Tape confirmed (chunk memories with ``source_document``/``source_span``)
     ↓
    Document registry confirmed (``D####`` in ``documents.jsonl``)
     ↓
    Graph extraction, governed by ``document_structure_level``:
        chunk     - local view (one extraction per chunk memory)
        document  - window view (structure only visible across many chunks)
        both      - chunk then document

The extractor runs last and its failures never undo or block the tape: it
reuses the pending/failed/retry policy of the ``graph`` module. Document-level
projections are strictly additive: they never overwrite chunk rows and every
relation carries its supporting window evidence. When ``enable_graph`` is false
(``--no-document-graph``) the document is ingested into the tape only: no
registry, no extraction of any scope.

``Machine.add_memory`` and ``ingest_attachment`` are intentionally untouched;
this path is the only place ``document_graph_enabled``/``document_structure_level``
are consulted.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .attachments import _file_hash
from .graph import (
    GraphStore,
    WindowRecord,
    _chunk_records,
    apply_batch_extraction,
    apply_record_extraction,
    apply_window_extraction,
)
from .groups import Manifest, add_memory
from .retrieval import chunk_spans
from .secrets import SecretError
from .tape import MemoryRecord, Tape

DEFAULT_CHUNK_SIZE = 600
DEFAULT_CHUNK_OVERLAP = 100
WINDOW_SCOPE_TAG = "document"


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
    scope: str = "chunk",
    batch_size: int,
    batch_max_chars: int,
    max_attempts: int,
) -> dict[str, Any]:
    """Project chunk records (one idempotency unit each) with retry policy."""
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
                    scope=scope,
                )
            else:
                outcome = apply_batch_extraction(
                    store, batch, extractor.extract_batch, tag=tag,
                    extractor_name=name, extractor_version=version,
                    resolver=resolver, max_attempts=max(1, int(max_attempts)),
                    scope=scope,
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
    return _summary(status=None, tag=tag, applied=applied, pending=pending,
                    failed=failed, created_entities=created_entities, mentions=mentions)


def _run_window_extraction(
    store: GraphStore,
    records: list[MemoryRecord],
    extractor: Any,
    resolver: Any,
    *,
    doc_id: str,
    window_chars: int,
    extractor_name: str,
    extractor_version: str,
    max_attempts: int,
) -> dict[str, Any] | None:
    """Project document-level windows (one idempotency unit each).

    Windows are source-ordered chunk groups of at most ``window_chars``
    characters. Each window becomes a ``WindowRecord`` with stable id
    ``f"{doc_id}|w{i:02d}"``; a window's relations carry evidence anchored to
    its real members (never outside them, see ``_resolve_window_evidence``).
    """
    extract_window = getattr(extractor, "extract_window", None)
    if extract_window is None:
        return None
    name = extractor_name or getattr(extractor, "name", "chunk")
    version = extractor_version or getattr(extractor, "version", "v1")
    tag = f"{getattr(extractor, 'tag', None) or f'{name}/{version}'}/{WINDOW_SCOPE_TAG}"

    applied = pending = failed = created_entities = mentions = 0
    window_groups: list[list[MemoryRecord]] = []
    current: list[MemoryRecord] = []
    used = 0
    for record in records:
        cost = len(record.why or "") or len(record.text())
        if current and used + cost > max(1, int(window_chars)):
            window_groups.append(current)
            current = []
            used = 0
        current.append(record)
        used += cost
    if current:
        window_groups.append(current)

    for i, window_members in enumerate(window_groups, start=1):
        members = tuple(window_members)
        first_span = tuple(getattr(members[0], "source_span", ()) or ())
        last_span = tuple(getattr(members[-1], "source_span", ()) or ())
        span = ()
        if len(first_span) == 2 and len(last_span) == 2:
            span = (int(first_span[0]), int(last_span[1]))
        window = WindowRecord(
            id=f"{doc_id}|w{i:02d}",
            members=members,
            source_document=str(getattr(members[0], "source_document", "") or ""),
            source_span=span,
        )
        outcome = apply_window_extraction(
            store, window, extract_window, tag=tag,
            extractor_name=name, extractor_version=version,
            resolver=resolver, max_attempts=max(1, int(max_attempts)),
            scope=WINDOW_SCOPE_TAG,
        )
        status = str(outcome.get("status") or "")
        applied += int(outcome.get("applied") or 0) or int(status == "extracted")
        pending += int(outcome.get("pending") or 0) or int(status == "pending")
        failed += int(outcome.get("failed") or 0) or int(status == "failed")
        created_entities += int(outcome.get("created_entities") or 0)
        mentions += int(outcome.get("new_mentions") or 0)
    return _summary(status=None, tag=tag, applied=applied, pending=pending,
                    failed=failed, created_entities=created_entities, mentions=mentions)


def _summary(
    *,
    status: str | None,
    tag: str,
    applied: int,
    pending: int,
    failed: int,
    created_entities: int,
    mentions: int,
) -> dict[str, Any]:
    if status is None:
        status = (
            "pending" if pending and not applied else
            "partial" if applied and (pending or failed) else
            "extracted" if applied else
            "failed" if failed else "registered"
        )
    return {
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
    structure_level: str = "chunk",
    window_chars: int = 12000,
) -> dict[str, Any]:
    """Ingest one .txt file through the tape -> registry -> graph pipeline.

    ``structure_level`` selects the extraction scopes for this call:
    ``chunk`` (base, D3 behavior), ``document`` (window pass only) or ``both``.
    The tape is always committed first; the registry second; graph extraction
    is last and never propagates failures.
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

    # --------------------------------------------------------------- graph
    graph_active = bool(enable_graph and store is not None and extractor is not None)
    chunk_summary = None
    document_summary = None
    if graph_active:
        records = preexisting or saved
        if structure_level in {"chunk", "both"} and records:
            chunk_summary = _run_extraction(
                store, records, extractor, resolver,
                extractor_name=extractor_name, extractor_version=extractor_version,
                scope="chunk",
                batch_size=batch_size, batch_max_chars=batch_max_chars,
                max_attempts=max_attempts,
            )
        if structure_level in {"document", "both"} and records:
            document_summary = _run_window_extraction(
                store, records, extractor, resolver,
                doc_id=doc_ref["id"] if doc_ref else source,
                window_chars=window_chars,
                extractor_name=extractor_name, extractor_version=extractor_version,
                max_attempts=max_attempts,
            )

    summaries = [s for s in (chunk_summary, document_summary) if s]
    graph: dict[str, Any] = {
        "enabled": bool(enable_graph and store is not None),
        "structure_level": structure_level,
    }
    if summaries:
        applied = sum(s["applied"] for s in summaries)
        pending = sum(s["pending"] for s in summaries)
        failed = sum(s["failed"] for s in summaries)
        created_entities = sum(s["created_entities"] for s in summaries)
        mentions = sum(s["new_mentions"] for s in summaries)
        tags = [s["tag"] for s in summaries]
        graph["status"] = (
            "pending" if pending and not applied else
            "partial" if applied and (pending or failed) else
            "extracted" if applied else
            "failed" if failed else "registered"
        )
        graph["tag"] = "+".join(tags)
        graph["applied"] = applied
        graph["pending"] = pending
        graph["failed"] = failed
        graph["created_entities"] = created_entities
        graph["new_mentions"] = mentions
        graph["chunk"] = chunk_summary
        graph["document"] = document_summary
        if doc_ref is not None:
            store.update_document(
                doc_ref["id"], status=graph["status"], extractor=graph["tag"]
            )
    elif enable_graph and store is not None and extractor is None:
        graph["status"] = "registered"
        graph["tag"] = extractor_name or "chunk"
        graph["applied"] = graph["pending"] = graph["failed"] = 0
        graph["created_entities"] = graph["new_mentions"] = 0
        graph["chunk"] = None
        graph["document"] = None

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