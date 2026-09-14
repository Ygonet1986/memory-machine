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
import shutil
from typing import Any

from .attachments import _file_hash
from .documents import documents_dir
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


class DocumentRebuildError(Exception):
    """A required original document is missing or its hash no longer matches."""


def _settle_meta(
    store: GraphStore,
    *,
    tag: str,
    document_tag: str | None = None,
    structure_level: str | None = None,
) -> None:
    """Stamp meta after a document-aware pass.

    The window pass overwrites ``meta.tag`` with the document-scope tag; that
    would make the next ``build_graph`` demand a rebuild (tag mismatch). Keep
    ``meta.tag`` at the chunk-level tag and record the window tag separately so
    re-runs stay idempotent and ``graph status`` still reads ``meta.tag``.
    """
    meta = dict(store.meta())
    meta["tag"] = tag
    if document_tag:
        meta["document_tag"] = document_tag
    else:
        meta.pop("document_tag", None)
    if structure_level is not None:
        meta["document_structure_level"] = structure_level
    meta["counts"] = store.counts()
    store.write_meta(meta)


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
    original: str = "",
) -> dict[str, Any]:
    """Register/refresh the ``D####`` row. Idempotent by ``source``."""
    if store is None:
        return None
    record, created = store.add_document(
        source=source,
        name=path.name,
        hash=hash,
        path=str(path),
        original=original,
        spans=spans,
        extractor=extractor,
        status="registered",
    )
    if created:
        store.update_document(record.id, extractor=extractor)
    return {"id": record.id, "source": record.source, "created": created}


def _preserve_original(base: Path, source: Path) -> str:
    """Copy the ingested .txt into the originals dir (D5, decision #8).

    ``base`` is the originals dir itself (``<root>/documents/``). Returns the
    preserved path; copies only when the target is missing. An
    already-preserved file is re-verified but never duplicated.
    """
    target = (base or documents_dir(source.parent)) / source.name
    if target.exists():
        return str(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return str(target)


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
    documents_root: Path | None = None,
) -> dict[str, Any]:
    """Ingest one .txt file through the tape -> registry -> graph pipeline.

    ``structure_level`` selects the extraction scopes for this call:
    ``chunk`` (base, D3 behavior), ``document`` (window pass only) or ``both``.
    The tape is always committed first; the registry second; graph extraction
    is last and never propagates failures. ``documents_root`` is where the
    original document is preserved (default ``<tape-dir>/documents``) for the
    D5 rebuild/provenance chain.
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
    docs_root = documents_root or documents_dir(tape.path.parent)
    doc_ref = None
    if enable_graph and store is not None:
        original = _preserve_original(docs_root, p)
        doc_ref = _register_document(
            store, path=p, source=source, hash=_file_hash(text),
            spans=spans, extractor=extractor_name or "chunk",
            original=original,
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
        extractor_tag = chunk_summary["tag"] if chunk_summary else (
            f"{extractor_name or getattr(extractor, 'name', 'chunk')}/"
            f"{extractor_version or getattr(extractor, 'version', 'v1')}"
        )
        _settle_meta(
            store,
            tag=extractor_tag,
            document_tag=document_summary["tag"] if document_summary else None,
            structure_level=structure_level,
        )
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


# ------------------------------------------------------- document-aware rebuild (D5)


def validate_originals(store: GraphStore, documents_root: Path) -> list[dict[str, Any]]:
    """Hash-validate every preserved original against the registry.

    Never approximates: a missing or adulterated file is reported verbatim
    with the expected hash. Raises ``DocumentRebuildError`` listing every
    offending document before any extraction is started.
    """
    problems: list[dict[str, Any]] = []
    root_exists = documents_root.exists()
    for doc in store.documents():
        original = Path(doc.original) if doc.original else documents_root / doc.name
        if not root_exists or not original.exists():
            problems.append({
                "id": doc.id,
                "source": doc.source,
                "name": doc.name,
                "expected_hash": doc.hash,
                "error": "original missing",
                "path": str(original),
            })
            continue
        actual = _file_hash(original.read_text(encoding="utf-8", errors="replace").strip())
        if actual != doc.hash:
            problems.append({
                "id": doc.id,
                "source": doc.source,
                "name": doc.name,
                "expected_hash": doc.hash,
                "actual_hash": actual,
                "error": "hash mismatch (document was altered)",
                "path": str(original),
            })
    if problems:
        raise DocumentRebuildError(
            "document originals are missing or altered; refusing to rebuild "
            f"approximately: {problems}"
        )
    return problems


def rebuild_document_projection(
    store: GraphStore,
    tape: Tape,
    documents_root: Path,
    extractor: Any,
    resolver: Any,
    *,
    structure_level: str = "chunk",
    window_chars: int = 12000,
    batch_size: int = 8,
    batch_max_chars: int = 0,
    max_attempts: int = 3,
    extractor_name: str = "",
    extractor_version: str = "",
) -> dict[str, Any]:
    """Re-project the document layer (chunk + optional window scopes) from the
    tape, the ``D####`` registry and the preserved originals.

    Used by ``build_graph(rebuild=...)`` (D5). Originals are hash-validated
    first (``validate_originals``), then each document replays exactly the same
    chunk/window passes as :func:`ingest_document`: same tags, same retry and
    idempotency units. Never reconstructs approximately.
    """
    validate_originals(store, documents_root)
    docs = store.documents()
    if not docs:
        return {"ok": True, "skipped": True, "documents": 0}

    name = extractor_name or getattr(extractor, "name", "chunk")
    version = extractor_version or getattr(extractor, "version", "v1")
    total: dict[str, int] = {"documents": len(docs), "chunks": 0, "applied": 0,
                             "pending": 0, "failed": 0, "created_entities": 0}
    levels: list[str] = []
    for doc in docs:
        records = sorted(
            [r for r in tape.read() if r.source == doc.source and r.type == "attachment"],
            key=lambda r: (r.source_span[0] if r.source_span else 0),
        )
        if not records:
            continue
        total["chunks"] += len(records)
        if structure_level in {"chunk", "both"}:
            levels.append("chunk")
            summary = _run_extraction(
                store, records, extractor, resolver,
                extractor_name=name, extractor_version=version,
                scope="chunk", batch_size=batch_size,
                batch_max_chars=batch_max_chars, max_attempts=max_attempts,
            )
            total["applied"] += summary.get("applied") or 0
            total["pending"] += summary.get("pending") or 0
            total["failed"] += summary.get("failed") or 0
            total["created_entities"] += summary.get("created_entities") or 0
        if structure_level in {"document", "both"}:
            levels.append("document")
            summary = _run_window_extraction(
                store, records, extractor, resolver,
                doc_id=doc.id, window_chars=window_chars,
                extractor_name=name, extractor_version=version,
                max_attempts=max_attempts,
            )
            if summary is not None:
                total["applied"] += summary.get("applied") or 0
                total["pending"] += summary.get("pending") or 0
                total["failed"] += summary.get("failed") or 0
                total["created_entities"] += summary.get("created_entities") or 0
    total["structure_level"] = structure_level
    total["tag"] = f"{name}/{version}" if levels == ["chunk"] else (
        f"{name}/{version}/document" if levels == ["document"] else
        (f"{name}/{version}+{name}/{version}/document" if levels else "")
    )
    if levels:
        extractor_tag = getattr(extractor, "tag", None) or f"{name}/{version}"
        _settle_meta(
            store,
            tag=extractor_tag,
            document_tag=(
                f"{extractor_tag}/{WINDOW_SCOPE_TAG}" if "document" in levels else None
            ),
            structure_level=structure_level,
        )
    return total
    return {"ok": True, **total}