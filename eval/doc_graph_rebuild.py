"""doc-graph-v1 — rebuild-fidelity harness (pre-registered).

Pre-registered design (docs/DOC_GRAPH_V1.md, no post-hoc changes):

  question    does a rebuild from the same original TXT + config + extractor
              preserve structure and provenance of the original projection?
  canonical   pinned corpus, chunk_size/overlap, structure_level="both",
              window_chars; the canonical snapshot bytes seed every arm.
  arms        O = original ingest; A, B = two INDEPENDENT rebuilds from the
              canonical bytes (each a fresh extractor draw, as in U4.2).
  deterministic D1..D8   program-controlled identity, bar = 100% on every arm.
  semantic    S1 entity / S2 relation / S3 evidence coverage / S4 structural
              drift / S5 extraction health — registered, pairwise Δ matrix.
  rule        faithful on m iff Δ(A,B|m) <= max(Δ(O,A|m), Δ(O,B|m));
              no tolerance constant; no criterion chosen after the fact.
  self-check  the deterministic (fake) arm must yield Δ = 0 on the
              structure sets — otherwise the harness itself is broken.

Run (deterministic self-check):
  PYTHONPATH=src python3 eval/doc_graph_rebuild.py --out /tmp/dg --fake
Run (LLM execution arm, requires API key):
  PYTHONPATH=src python3 eval/doc_graph_rebuild.py --out /tmp/dg --llm --api-key ...
"""

from __future__ import annotations

import argparse
import copy
import json
import shutil
import sys
import tempfile
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

from memory_machine.config import Config  # noqa: E402
from memory_machine.documents import documents_dir  # noqa: E402  (noqa: F401)
from memory_machine.graph import (  # noqa: E402
    GraphStore,
    build_graph,
    noop_extractor,
)
from memory_machine.groups import Manifest  # noqa: E402
from memory_machine.ingest_document import (  # noqa: E402
    ingest_document,
    validate_originals,
)
from memory_machine.tape import MemoryRecord, Tape  # noqa: E402

CHUNK_SIZE_DEFAULT = 400
OVERLAP_DEFAULT = 50
WINDOW_CHARS_DEFAULT = 12000
LEVEL_DEFAULT = "both"
VOLATILE_KEYS = ("created_at", "updated_at", "built_at")

CORPUS = {
    "tech-notes.txt": (
        "Infrastructure notes. The API reads memory from Postgres and caches "
        "responses in Redis; Redis is deployed as a cluster of three nodes. "
        "The ingestion service writes to Postgres through a batched writer. "
        "Docker runs every service in containers; Kubernetes schedules the "
        "containers across the cluster. The queue is backed by RabbitMQ, and a "
        "dead-letter queue stores failed jobs. Sentry monitors errors, Grafana "
        "dashboards ingest metrics, Prometheus scrapes the metrics every "
        "fifteen seconds. The gateway fronted by HAProxy routes the mobile "
        "clients to the API replicas. Central logging goes to Loki and every "
        "service reads its configuration from Consul."
    ),
    "novella.txt": (
        "Kalak crossed the rock in the morning mist and found the garden "
        "behind the old lighthouse. The gardener owned a hedgehog named "
        "Petronante, kept the watering can beside the well, and feared the "
        "deep. Kalak asked for shelter; the gardener offered bread and told "
        "the story of the tide that swallowed the pier. At dusk Kalak "
        "repaired the broken gate with rope and sanded the wooden post. The "
        "hedgehog curled under the bench, the cat watched from the sill, and "
        "the sea drummed below the cliff. Before leaving, Kalak planted three "
        "rosebushes by the gate and carved a message into the post that the "
        "tide would never reach."
    ),
    "decisions.txt": (
        "Quarterly decision log. The team adopted the build pipeline from "
        "Jenkins to GitHub Actions after two outages; the migration reverted "
        "the Docker cache strategy to layer caching. The caretaker agreed to "
        "open the west wing on weekends. We rejected the analytics vendor for "
        "price reasons and opted for the open-source collector instead. The "
        "reviewer recommended keeping the legacy schema read-only and "
        "promoting the new event store to the source of truth. Rollout stays "
        "graduated: ten percent the first week, then fifty, then one hundred. "
        "A follow-up meeting will audit the retention policy and archive the "
        "cold buckets to cheaper storage."
    ),
}


class WindowExtractor:
    """Deterministic chunk + window extractor (no transport)."""

    name = "winfake"
    version = "v1"

    @property
    def tag(self) -> str:
        return "winfake/v1"

    def _result(self, record: MemoryRecord) -> dict[str, Any]:
        return {
            "entities": [
                {"name": "Kalak", "type": "character"},
                {"name": "rock", "type": "object"},
            ],
            "relations": [
                {"source": "Kalak", "relation": "crossed", "target": "rock",
                 "confidence": 0.9},
            ],
            "mentions": ["Kalak"],
        }

    def extract(self, record: MemoryRecord) -> dict[str, Any]:
        return self._result(record)

    def extract_batch(self, records: list[MemoryRecord]) -> dict[str, Any]:
        return {r.id: self._result(r) for r in records}

    def extract_window(self, window: Any) -> dict[str, Any]:
        members = window.members
        return {
            "entities": [
                {"name": "Kalak", "type": "character"},
                {"name": "rock", "type": "object"},
            ],
            "relations": [
                {
                    "source": "Kalak",
                    "relation": "influences",
                    "target": "rock",
                    "confidence": 0.8,
                    "evidence": [
                        {"memory_id": members[0].id,
                         "span": list(members[0].source_span)},
                        {"memory_id": members[-1].id,
                         "span": list(members[-1].source_span)},
                    ],
                },
            ],
        }


# ----------------------------------------------------------------- forms


def norm(name: str) -> str:
    """Pre-registered normalization: NFC -> lowercase -> no accents -> [a-z0-9 ]."""
    text = unicodedata.normalize("NFD", unicodedata.normalize("NFC", str(name).lower()))
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = "".join(ch for ch in text if ch.isalnum() or ch in " ")
    return " ".join(text.split())


def norm_plural(name: str) -> str:
    """S2b variant: naive plural-strip on the verb (trailing s, len > 3)."""
    lowered = norm(name)
    if len(lowered) > 3 and lowered.endswith("s") and not lowered.endswith("ss"):
        return lowered[:-1]
    return lowered


def drop_volatile(d: dict[str, Any]) -> dict[str, Any]:
    out = {k: v for k, v in d.items() if k not in VOLATILE_KEYS}
    for key in ("span", "source_span", "evidence"):
        if key in out and isinstance(out[key], list):
            out[key] = json.dumps(out[key], sort_keys=True)
    return out


def basename_field(d: dict[str, Any], key: str, default: str = "") -> dict[str, Any]:
    out = copy.deepcopy(d)
    if key in d:
        try:
            out[key] = Path(str(d[key])).name
        except Exception:
            out[key] = default
    return out


# -------------------------------------------------------------- snapshots


def snapshot_rows(store: GraphStore) -> dict[str, list[dict[str, Any]]]:
    return {
        "documents": [drop_volatile(basename_field(d.to_dict(), "original"))
                      for d in store.documents()],
        "entities": [drop_volatile(e.to_dict()) for e in store.entities()],
        "relations": [drop_volatile(r.to_dict()) for r in store.relations()],
        "mentions": [drop_volatile(m.to_dict()) for m in store.mentions()],
    }


def row_key(path: tuple[str, ...]) -> str:
    return json.dumps(path, sort_keys=True)


def identity_multisets(snap: dict[str, list[dict[str, Any]]]) -> dict[str, Counter[str]]:
    return {
        k: Counter(sorted(row_key(d) for d in v))
        for k, v in snap.items()
    }


# -------------------------------------------------------------- audit (D)


def window_members(tape: Tape, doc_source: str,
                   window_span: tuple[int, int]) -> list[MemoryRecord]:
    return [
        r for r in tape.read()
        if r.source == doc_source and r.type == "attachment"
        and r.source_span
        and int(window_span[0]) <= int(r.source_span[0])
        and int(r.source_span[1]) <= int(window_span[1])
    ]


def provenance_audit(store: GraphStore, tape: Tape,
                     documents_root: Path) -> list[str]:
    """D5..D8: provenance, evidence closure, scope, bounds. Returns problems."""
    problems: list[str] = []
    docs = store.documents()
    doc_sources = {d.source for d in docs}
    doc_id_by_source = {d.source: d.id for d in docs}
    doc_span_by_doc: dict[str, tuple[int, int]] = {}
    chunk_mem_by_doc: dict[str, set[str]] = {}
    window_to_members: dict[str, tuple[MemoryRecord, ...]] = {}

    for doc in docs:
        spans = [tuple(s) for s in doc.spans]
        if not spans:
            problems.append(f"{doc.id}: registry spans empty")
            continue
        doc_span_by_doc[doc.source] = (min(s[0] for s in spans),
                                       max(s[1] for s in spans))
        if min(s[0] for s in spans) != 0:
            problems.append(f"{doc.id}: document spans do not start at 0")
        if len({frozenset(s) for s in spans}) != len(spans):
            problems.append(f"{doc.id}: duplicate chunk span in registry")
        chunk_mem_by_doc[doc.source] = {
            r.id for r in tape.read()
            if r.source == doc.source and r.type == "attachment"
        }

    windows: dict[str, tuple[int, int]] = {}
    for rel in store.relations():
        mid = str(rel.memory_id or "")
        if mid.startswith("D") and "|w" in mid:
            span = tuple(rel.source_span) if rel.source_span else ()
            if len(span) == 2:
                windows[mid] = (int(span[0]), int(span[1]))
    for wid, wspan in windows.items():
        doc_id = wid.split("|")[0]
        doc = store.document_by_id(doc_id)
        if doc is None:
            problems.append(f"{wid}: window without registry document")
            continue
        members = window_members(tape, doc.source, wspan)
        if not members:
            problems.append(f"{wid}: no chunk members inside span {wspan}")
        window_to_members[wid] = tuple(members)

    def check_row(kind: str, rid: str, memory_id: str, scope: str,
                  source_document: str, span: Any) -> None:
        if scope not in {"chunk", "document"}:
            problems.append(f"{kind} {rid}: bad extraction_scope {scope!r}")
        if source_document and source_document not in doc_sources:
            problems.append(f"{kind} {rid}: source_document outside registry")
        if span and not (len(span) == 2 and int(span[0]) <= int(span[1])):
            problems.append(f"{kind} {rid}: malformed span {span!r}")
        if scope == "chunk":
            if memory_id and memory_id not in chunk_mem_by_doc.get(source_document, ()):
                problems.append(f"{kind} {rid}: chunk memory {memory_id} "
                                "not in its document's tape chunks")
        elif scope == "document":
            if not memory_id or "|w" not in memory_id:
                problems.append(f"{kind} {rid}: document scope without window id")
            elif doc_id_by_source.get(source_document) and \
                    not memory_id.startswith(doc_id_by_source[source_document]):
                problems.append(f"{kind} {rid}: window id {memory_id} does not "
                                "belong to document {source_document}")

    for rel in store.relations():
        scope = str(rel.extraction_scope or "")
        memory_id = str(rel.memory_id or "")
        source = str(getattr(rel, "source_document", "") or "")
        check_row("relation", rel.id, memory_id, scope, source,
                  getattr(rel, "source_span", ()))
        if scope == "document" and window_to_members.get(memory_id) is not None:
            member_ids = {str(m.id) for m in window_to_members[memory_id]}
            for ev in rel.evidence:
                ev_id = (str(ev.get("memory_id") or "")
                         if isinstance(ev, dict) else str(getattr(ev, "memory_id", "")))
                if ev_id and ev_id not in member_ids:
                    problems.append(
                        f"relation {rel.id}: evidence {ev_id} outside window "
                        f"{memory_id} (D6)")
                if isinstance(ev, dict) and isinstance(ev.get("span"), list):
                    span = ev["span"]
                    if len(span) == 2 and not (int(span[0]) <= int(span[1])):
                        problems.append(
                            f"relation {rel.id}: malformed evidence span")

    for ent in store.entities():
        check_row("entity", ent.id, str(ent.memory_id or ""),
                  str(ent.extraction_scope or ""),
                  str(getattr(ent, "source_document", "") or ""),
                  getattr(ent, "source_span", ()))
    for mem in store.mentions():
        check_row("mention", f"mention({mem.memory_id})", str(mem.memory_id or ""),
                  str(mem.extraction_scope or ""),
                  str(getattr(mem, "source_document", "") or ""),
                  getattr(mem, "span", ()))

    for rel in store.relations():
        source = str(getattr(rel, "source_document", "") or "")
        span = getattr(rel, "source_span", None)
        if source in doc_span_by_doc and span and len(span) == 2:
            lo, hi = doc_span_by_doc[source]
            if not (int(lo) <= int(span[0]) and int(span[1]) <= int(hi)):
                problems.append(
                    f"relation {rel.id}: span {span} outside document bounds")

    return problems


def deterministic_audit(store: GraphStore, tape: Tape, documents_root: Path,
                        canonical_registry: list[dict[str, Any]]) -> dict[str, Any]:
    """D1..D8 verdicts for one arm. Returns {passed, problems, checks}."""
    registry = [drop_volatile(basename_field(d.to_dict(), "original"))
                for d in store.documents()]
    checks: dict[str, Any] = {}

    tape_bytes = tape.path.read_bytes() if Path(tape.path).exists() else b""
    checks["D1_tape_bytes"] = len(tape_bytes)
    checks["D3_validate"] = "clean"
    try:
        validate_originals(store, documents_root)
    except Exception as exc:  # DocumentRebuildError
        checks["D3_validate"] = str(exc)

    checks["D2_registry_rows"] = len(registry)
    problems: list[str] = []
    if checks["D3_validate"] != "clean":
        problems.append(f"D3: validate_originals rejected: {checks['D3_validate']}")
    if registry != canonical_registry:
        problems.append("D2: registry differs from canonical registry")

    prov = provenance_audit(store, tape, documents_root)
    problems.extend(prov)
    return {
        "passed": not problems,
        "problems": problems,
        "checks": checks,
    }


# ---------------------------------------------------------- semantic (S)


def semantic_sets(snap: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    ents = Counter()
    rels = Counter()
    rels2 = Counter()
    ev = Counter()  # aligned later, placeholder
    for e in snap["entities"]:
        ents[(norm(e["name"]), norm(e.get("type") or "unknown"),
              str(e.get("extraction_scope") or ""),
              str(e.get("source_document") or ""))] += 1
    for r in snap["relations"]:
        key = (norm(r["source"]), norm(r["relation"]), norm(r["target"]),
               str(r.get("extraction_scope") or ""),
               str(r.get("source_document") or ""))
        rels[key] += 1
        key2 = (norm(r["source"]), norm_plural(r["relation"]), norm(r["target"]),
                str(r.get("extraction_scope") or ""),
                str(r.get("source_document") or ""))
        rels2[key2] += 1
    window_ids: list[str] = []
    chunk_ids: list[str] = []
    for r in snap["relations"]:
        mid = str(r.get("memory_id") or "")
        if mid.startswith("D") and "|w" in mid:
            window_ids.append(mid)
        elif mid.startswith("M"):
            chunk_ids.append(mid)
    windows = Counter(window_ids)
    chunks = Counter(chunk_ids)
    per_doc_type = Counter(
        (str(e.get("source_document") or ""), str(e.get("extraction_scope") or ""),
         norm(e.get("type") or "unknown"))
        for e in snap["entities"]
    )
    events = Counter(e.get("type") or "" for e in snap["entities"]
                     if norm(e.get("type") or "") == "event")
    return {
        "entities": ents,
        "relations": rels,
        "relations_plural": rels2,
        "windows": windows,
        "chunks": chunks,
        "per_doc_type": per_doc_type,
        "events": events,
        "mentions": len(snap["mentions"]),
    }


def jaccard(a: Counter[str], b: Counter[str]) -> float:
    if not a and not b:
        return 1.0
    inter = sum((a & b).values())
    union = sum((a | b).values()) or 0
    return inter / union if union else 0.0


def precision(a: Counter[str], b: Counter[str]) -> float:
    if not a:
        return 1.0
    inter = sum((a & b).values())
    return inter / sum(a.values()) if sum(a.values()) else 0.0


def recall(a: Counter[str], b: Counter[str]) -> float:
    return precision(b, a)


_EV = "evidence"


def delta_table(sets: dict[str, dict[str, Any]]) -> dict[str, dict[str, float]]:
    names = ("entities", "relations", "relations_plural", "windows", "chunks",
             "per_doc_type")
    table: dict[str, dict[str, float]] = {}
    for name in names:
        table[name] = {
            "oa": 1.0 - jaccard(sets["O"][name], sets["A"][name]),
            "ob": 1.0 - jaccard(sets["O"][name], sets["B"][name]),
            "ab": 1.0 - jaccard(sets["A"][name], sets["B"][name]),
        }
    return table


def evidence_alignment(snaps: dict[str, dict[str, list[dict[str, Any]]]],
                       key_fn: Any) -> dict[str, dict[str, Any]]:
    """S3 evidence coverage. Returns, per pair, the distance 1−recall (0 =
    identical), the eligibility counts, and the raw recall for the report."""
    result: dict[str, dict[str, Any]] = {}
    pairs = [("O", "A"), ("O", "B"), ("A", "B")]
    for x, y in pairs:
        rows_x = {(key_fn(r["source"]), key_fn(r["relation"]), key_fn(r["target"]),
                   str(r.get("extraction_scope") or ""),
                   str(r.get("source_document") or "")): r
                  for r in snaps[x]["relations"]}
        rows_y = {(key_fn(r["source"]), key_fn(r["relation"]), key_fn(r["target"]),
                   str(r.get("extraction_scope") or ""),
                   str(r.get("source_document") or "")): r
                  for r in snaps[y]["relations"]}
        recalls = []
        eligible = 0
        for key in rows_x:
            if key in rows_y:
                ex = _evidence_ids(rows_x[key]["evidence"])
                ey = _evidence_ids(rows_y[key]["evidence"])
                if ex:
                    eligible += 1
                    recalls.append(len(ex & ey) / len(ex))
        if recalls:
            recall = round(sum(recalls) / len(recalls), 4)
            result[f"{x}{y}"] = {
                "distance": round(1.0 - recall, 4),
                "recall": recall,
                "eligible_pairs": eligible,
                "aligned_relations": sum(1 for k in rows_x if k in rows_y),
            }
        else:
            result[f"{x}{y}"] = {
                "distance": None,
                "recall": None,
                "eligible_pairs": 0,
                "aligned_relations": sum(1 for k in rows_x if k in rows_y),
            }
    return result


def _evidence_ids(raw: Any) -> set[str]:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (TypeError, ValueError):
            raw = []
    return {str(ev.get("memory_id") or "") for ev in raw}


# ----------------------------------------------------------------- build


def build_extractor(use_llm: bool, args: argparse.Namespace) -> tuple[Any, str, str]:
    if not use_llm:
        return WindowExtractor(), "winfake", "v1"
    from memory_machine.graph_extract import GraphExtractor
    from memory_machine.llm import LLMClient

    config = Config.load(Path(args.out) or Path.cwd())
    client = LLMClient.from_config(config, api_key=args.api_key)
    extractor = GraphExtractor(client, version=args.extractor_version or None)
    return extractor, "llm", extractor.version


def build_project(root: Path, extractor: Any, extractor_name: str,
                  version: str, args: argparse.Namespace) -> dict[str, Any]:
    root.mkdir(parents=True, exist_ok=True)
    tape = Tape(root / "tape.jsonl")
    manifest = Manifest(capacity=50)
    store = GraphStore(root / "graph")
    results = []
    for fname, text in CORPUS.items():
        src = root / fname
        src.write_text(text, encoding="utf-8")
        results.append(
            ingest_document(
                tape, manifest, src, chunk_size=args.chunk_size,
                overlap=args.overlap, store=store, extractor=extractor,
                enable_graph=True, structure_level=args.level,
                window_chars=args.window_chars,
                extractor_name=extractor_name, extractor_version=version,
                batch_size=args.batch_size,
            )
        )
    return {"tape": tape, "store": store, "results": results}


def build_arm(arm: str, out_dir: Path, canonical: dict[str, Any],
              use_llm: bool, args: argparse.Namespace) -> dict[str, Any]:
    root = out_dir / f"{arm}_root"
    root.mkdir(parents=True, exist_ok=True)
    (root / "tape.jsonl").write_bytes(
        (canonical["tape_path"]).read_bytes())
    doc_dir = root / "documents"
    doc_dir.mkdir(parents=True, exist_ok=True)
    for preserved in sorted(canonical["originals"]):
        shutil.copy2(preserved, doc_dir / preserved.name)

    registry_path = root / "graph" / "documents.jsonl"
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(canonical["registry_path"], registry_path)
    rewrite_originals(registry_path, doc_dir)

    store = GraphStore(root / "graph")
    extractor, name, version = build_extractor(use_llm, args)
    result = build_graph(
        canonical["tape"], store, extractor, extractor_name=name,
        rebuild=True, atomic=True,
        document_structure_level=args.level, window_chars=args.window_chars,
        document_extractor=extractor, batch_size=args.batch_size,
        batch_max_chars=args.batch_max_chars,
    )
    return {"root": root, "store": store, "extractor": (name, version),
            "result": result, "registry_path": registry_path,
            "documents_root": doc_dir}


def rewrite_originals(registry_path: Path, documents_root: Path) -> None:
    """Point the registry's preserved-file paths at the arm-local documents dir.

    The stored ``original`` path is absolute (finding F-1); for an independent
    rebuild the arm must validate its own originals, so the path is normalized
    to (documents_root, name) — hash and name are untouched, so the provenance
    identity is preserved.
    """
    rows = [json.loads(line) for line in
            registry_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    text = registry_path.read_text(encoding="utf-8")
    for row in rows:
        name = Path(str(row.get("original", ""))).name
        if name:
            text = text.replace(row["original"], str(documents_root / name))
    registry_path.write_text(text, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, help="work + report dir")
    parser.add_argument("--fake", action="store_true",
                        help="deterministic extractor (default): harness self-check")
    parser.add_argument("--llm", action="store_true",
                        help="real GraphExtractor (execution arm)")
    parser.add_argument("--api-key", default="", help="override the API key")
    parser.add_argument("--extractor-version", default="")
    parser.add_argument("--chunk-size", type=int, default=CHUNK_SIZE_DEFAULT)
    parser.add_argument("--overlap", type=int, default=OVERLAP_DEFAULT)
    parser.add_argument("--window-chars", type=int, default=WINDOW_CHARS_DEFAULT)
    parser.add_argument("--level", default=LEVEL_DEFAULT,
                        choices=("chunk", "document", "both"))
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--batch-max-chars", type=int, default=0)
    args = parser.parse_args()

    use_llm = bool(args.llm)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "build").mkdir(exist_ok=True)

    extractor, name, version = build_extractor(use_llm, args)
    project = build_project(out_dir / "build" / "o", extractor, name, version, args)
    tape, store_o = project["tape"], project["store"]
    canonical = {
        "tape": tape,
        "tape_path": tape.path,
        "registry_path": store_o.directory / "documents.jsonl",
        "originals": sorted((documents_dir(out_dir / "build" / "o")).glob("*.txt")),
    }
    if not canonical["originals"]:
        print("no preserved originals in canonical project; aborting")
        return 1

    arm_a = build_arm("A", out_dir, canonical, use_llm, args)
    arm_b = build_arm("B", out_dir, canonical, use_llm, args)

    canonical_registry = [
        drop_volatile(basename_field(d.to_dict(), "original"))
        for d in store_o.documents()
    ]

    arms = {
        "O": {"store": store_o, "tape": tape,
              "documents_root": documents_dir(out_dir / "build" / "o"),
              "result": {"ok": True}},
        "A": arm_a,
        "B": arm_b,
    }
    audits: dict[str, Any] = {}
    for label in ("O", "A", "B"):
        audits[label] = deterministic_audit(
            arms[label]["store"], tape, arms[label]["documents_root"],
            canonical_registry,
        )

    self_results = []
    for result in (arm_a["result"], arm_b["result"]):
        if not result.get("ok"):
            self_results.append(result.get("error"))

    det_fail = [p for label in ("O", "A", "B") for p in audits[label]["problems"]]
    det_fail.extend(self_results)

    canonical_tape_bytes = canonical["tape_path"].read_bytes()
    arm_tape_bytes_ok = all(
        (arms[label]["root"] / "tape.jsonl").read_bytes() == canonical_tape_bytes
        for label in ("A", "B")
    )
    if not arm_tape_bytes_ok:
        det_fail.append("D1: an arm's tape copy differs from the canonical tape")

    snaps = {"O": snapshot_rows(store_o),
             "A": snapshot_rows(arm_a["store"]),
             "B": snapshot_rows(arm_b["store"])}
    mset_o = identity_multisets(snaps["O"])
    mset_a = identity_multisets(snaps["A"])
    mset_b = identity_multisets(snaps["B"])
    determinism_gap = [
        k for k in mset_o if mset_o[k] != mset_a[k] or mset_o[k] != mset_b[k]
    ]

    sets = {label: semantic_sets(snaps[label]) for label in ("O", "A", "B")}
    delta = delta_table(sets)
    ev_all = evidence_alignment(snaps, norm)
    ev = {pair.lower(): ev_all[pair]["distance"] for pair in ("OA", "OB", "AB")}
    delta["evidence"] = ev
    evidence_meta = {pair: {k: v for k, v in ev_all[pair].items()
                            if k != "distance"} for pair in ("OA", "OB", "AB")}
    if any(ev_all[p]["eligible_pairs"] == 0 for p in ("OA", "OB", "AB")):
        evidence_meta["note"] = "no evidence-bearing aligned relations"
    health = {
        label: {
            "pending": len(arms[label]["store"].pending_rows()),
            "failed": len(arms[label]["store"].failed_rows()),
        }
        for label in ("O", "A", "B")
    }
    health_fail = any(health[label]["pending"] or health[label]["failed"]
                      for label in ("O", "A", "B"))

    ordering_fail: list[str] = []
    ordering_skipped: list[str] = []
    for metric, row in delta.items():
        ab, oa, ob = row.get("ab"), row.get("oa"), row.get("ob")
        if ab is None or oa is None or ob is None:
            ordering_skipped.append(metric)
            continue
        if ab > max(oa, ob):
            ordering_fail.append(metric)

    meta = {label: arms[label]["store"].meta() for label in ("O", "A", "B")}

    reasons = {
        "deterministic_clean": not det_fail,
        "rebuild_ok": not self_results,
        "tape_unaltered": arm_tape_bytes_ok,
        "extraction_health": not health_fail,
        "abor_b_ordering": not ordering_fail,
    }
    if use_llm:
        # The deterministic metrics still gate the LLM execution arm; structure
        # identity is NOT required there (semantic arm). The single extra bar
        # is the pre-registered §7 ordering on every semantic metric.
        passed = all(reasons.values())
    else:
        # Self-check: the deterministic arm must reproduce the projection
        # exactly (Δ = 0 on the structure sets).
        reasons["structural_identity_fake_arm"] = not determinism_gap
        nondeterministic = any(
            delta[m]["ab"] or delta[m]["oa"] or delta[m]["ob"]
            for m in ("entities", "relations", "relations_plural",
                      "windows", "chunks", "per_doc_type", "evidence")
        )
        reasons["ab_zero_fake_arm"] = not nondeterministic
        passed = all(reasons.values())
    decision = "PASS" if passed else "FAIL"

    report = {
        "question": "Given the same original TXT and the same config/extractor, "
                    "does the rebuilt documental graph preserve structure and "
                    "provenance of the original projection?",
        "preregistered": "docs/DOC_GRAPH_V1.md",
        "arm_extractor": {"name": name, "version": version},
        "params": {"chunk_size": args.chunk_size, "overlap": args.overlap,
                   "level": args.level, "window_chars": args.window_chars,
                   "batch_size": args.batch_size},
        "canonical": {k: str(v) for k, v in canonical.items()
                      if k not in ("tape", "tape_path")},
        "audits": audits,
        "rebuild_errors": self_results,
        "determinism_gap_sets": determinism_gap,
        "delta": delta,
        "evidence": evidence_meta,
        "health": health,
        "ordering_failures": ordering_fail,
        "ordering_skipped": ordering_skipped,
        "meta_tags": {label: (meta[label].get("tag"), meta[label].get("document_tag"))
                      for label in ("O", "A", "B")},
        "decision": decision,
        "reason": reasons,
    }
    (out_dir / "doc_graph_rebuild.json").write_text(
        json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")

    md = render_report(report)
    (out_dir / "doc_graph_rebuild_summary.md").write_text(md, encoding="utf-8")
    print(md)
    print(f"\nDECISION: {decision}")
    return 0 if decision == "PASS" else 1


def render_report(r: dict[str, Any]) -> str:
    lines = [
        "# doc-graph-v1 rebuild fidelity — summary",
        "",
        f"**Decision:** `{r['decision']}`  ·  extractor {r['arm_extractor']}",
        f"**Params:** {r['params']}",
        "",
        "## Deterministic audit (D1–D8)",
        "",
    ]
    for label in ("O", "A", "B"):
        aud = r["audits"][label]
        lines.append(f"### {label}: {'clean' if aud['passed'] else 'PROBLEMS'}")
        if aud["problems"]:
            lines += [f"- {p}" for p in aud["problems"]]
        lines += [f"- check: {aud['checks']}"]
        lines.append("")
    if r["rebuild_errors"]:
        lines.append("**Rebuild errors:**")
        lines += [f"- {e}" for e in r["rebuild_errors"]]
        lines.append("")
    lines.append("**Structural identity (fake arm must be empty): "
                 f"{r['determinism_gap_sets']}**")
    lines.append("")
    lines.append("## Semantic Δ matrix (1 − Jaccard)")
    lines.append("")
    lines.append("| metric | Δ(O,A) | Δ(O,B) | Δ(A,B) |")
    lines.append("|---|---:|---:|---:|")
    for metric, row in r["delta"].items():
        fmt = lambda v: "n/a" if v is None else f"{v:.4f}"  # noqa: E731
        lines.append(f"| {metric} | {fmt(row['oa'])} | {fmt(row['ob'])} "
                     f"| {fmt(row['ab'])} |")
    lines.append("")
    if r.get("evidence"):
        ev = r["evidence"]
        if ev.get("note"):
            lines.append(f"**Evidence coverage:** {ev['note']}")
        else:
            lines.append("**Evidence coverage (S3, recall / aligned):**")
            for pair in ("OA", "OB", "AB"):
                m = ev[pair]
                lines.append(f"- {pair}: recall {m['recall']} "
                             f"({m['eligible_pairs']} eligible of "
                             f"{m['aligned_relations']} aligned)")
        lines.append("")
    lines.append("## Extraction health")
    lines.append("")
    lines.append("| arm | pending | failed |")
    lines.append("|---|---:|---:|")
    for label, h in r["health"].items():
        lines.append(f"| {label} | {h['pending']} | {h['failed']} |")
    lines.append("")
    if r.get("ordering_failures"):
        lines.append(f"**Ordering failures (A↔B must be ≤ max(O↔A, O↔B)): "
                     f"{r['ordering_failures']}**")
    else:
        lines.append("**Ordering failures: none "
                     f"(skipped {r.get('ordering_skipped')})**")
    lines.append("")
    lines.append(f"**Reason:** {r['reason']}")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    sys.exit(main())