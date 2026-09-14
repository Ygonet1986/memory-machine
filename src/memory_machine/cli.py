"""Command-line interface for the Memory Machine."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .config import Config, resolve_path
from .coordinator import Machine
from .graph import (
    EXTRACTORS,
    ExtractorSpec,
    GraphStore,
    build_graph,
    explain_relation,
    graph_status,
)
from .llm import LLMError
from .secrets import SecretError
from .sessions import list_sessions, sessions_dir_for
from .tape import PROJECT_TYPES, MemoryRecord
from .views import list_views


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="memory-machine",
        description="Persistent memory tape with memory agents and a shared whiteboard.",
    )
    p.add_argument("-C", "--root", default=".", help="project root directory")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="create an empty project (config + tape + manifest + whiteboard)")

    add = sub.add_parser("add", help="append a memory to the tape")
    add.add_argument("--type", default="decision", choices=sorted(PROJECT_TYPES))
    add.add_argument("--summary", required=True)
    add.add_argument("--why", default="")
    add.add_argument("--files", default="", help="comma-separated file paths")

    subj = sub.add_parser("subject", help="set the current whiteboard subject")
    subj.add_argument("subject")
    subj.add_argument("--objective", default="")

    run = sub.add_parser("run", help="run one cycle (agents -> whiteboard -> main chatbot)")
    run.add_argument("--task", required=True)
    run.add_argument("--no-consolidate", action="store_true")
    run.add_argument("--temperature", type=float, default=0.0)
    run.add_argument("--max-workers", type=int, default=None)
    run.add_argument("--json", action="store_true", help="print result as JSON")

    cons = sub.add_parser("consolidate", help="consolidate the whiteboard (one consolidator agent)")
    cons.add_argument("--llm", action="store_true", help="use the consolidator LLM agent")
    cons.add_argument("--temperature", type=float, default=0.0)

    sub.add_parser("status", help="show tape / groups / agents / whiteboard state")

    wb = sub.add_parser("whiteboard", help="print the whiteboard")
    wb.add_argument("--no-annotations", action="store_true")

    sub.add_parser("context", help="print the main chatbot's conversation context")

    recall = sub.add_parser("recall", help="run memory agents for a question; print whiteboard as JSON")
    recall.add_argument("question")
    recall.add_argument("--temperature", type=float, default=0.0)
    recall.add_argument("--max-workers", type=int, default=None)
    recall.add_argument("--cross-session", action="store_true", help="also search other sessions' tapes")
    recall.add_argument("--views", default="", help="comma-separated view filter (e.g. time/2026-09,type/decision)")
    recall.add_argument("--agent-mode", default="", choices=["", "group", "view"],
                        help="override the agent mode for this recall")
    recall.add_argument("--whiteboard-mode", default="", choices=["", "single", "dimension"],
                        help="override the whiteboard mode for this recall")
    recall.add_argument("--dimension-mode", default="", choices=["", "off", "auto"],
                        help="override dimension-aware routing for this recall")
    recall.add_argument("--attention", default="", choices=["", "off", "prior", "context", "state"],
                        help="override the attention mode for this recall")
    recall.add_argument("--evidence-payload", default="", choices=["", "off", "budgeted", "full"],
                        help="override the evidence payload mode for this recall")

    sub.add_parser("sessions", help="list sessions (JSON)")
    sub.add_parser("views", help="list memory views / projections (JSON)")

    graph = sub.add_parser("graph", help="graph projection: build/status/explain/query/path (JSON)")
    graph.add_argument(
        "action", choices=["build", "status", "explain", "query", "path"]
    )
    graph.add_argument("target", nargs="?", default="", help="relation id, query, or path source")
    graph.add_argument("target_b", nargs="?", default="", help="path target (graph path A B)")
    graph.add_argument("--rebuild", action="store_true", help="discard and rebuild from the tape")
    graph.add_argument(
        "--extractor",
        default="",
        choices=["", *sorted({*EXTRACTORS, "llm"})],
        help="extractor: llm (default on build) or noop (diagnostic); "
        "status defaults to the extractor recorded in meta.json",
    )
    graph.add_argument("--depth", type=int, default=0, help="max semantic depth (0 = config)")
    graph.add_argument("--top-k", type=int, default=0, help="max paths/evidence (0 = config)")

    roll = sub.add_parser("rollup", help="consolidate older tape records (JSON)")
    roll.add_argument("--keep-recent", type=int, default=20)
    roll.add_argument("--temperature", type=float, default=0.0)

    reh = sub.add_parser("rehydrate", help="recover the original memories behind a rollup (JSON)")
    reh.add_argument("memory_id")
    reh.add_argument("--reactivate", action="store_true")

    ckpt = sub.add_parser("checkpoint", help="record a turn back to memory (JSON)")
    ckpt.add_argument("question")
    ckpt.add_argument("summary")
    ckpt.add_argument("--memories", default="", help='JSON list of memory specs, e.g. \'[{"type":"decision","summary":"...","why":"..."}]\'')
    ckpt.add_argument("--temperature", type=float, default=0.0)

    rem = sub.add_parser("remember", help="append a memory (JSON)")
    rem.add_argument("--type", default="decision")
    rem.add_argument("--summary", required=True)
    rem.add_argument("--why", default="")
    rem.add_argument("--files", default="", help="comma-separated file paths")
    rem.add_argument("--views", default="", help="comma-separated view tags (e.g. topic/router)")

    sub.add_parser("list", help="list tape records (JSON)")

    att = sub.add_parser("attach", help="ingest an attached .txt into the tape as chunk memories (JSON)")
    att.add_argument("path")
    att.add_argument("--chunk-size", type=int, default=None)

    arch = sub.add_parser("archive", help="archive a memory (JSON)")
    arch.add_argument("memory_id")

    dele = sub.add_parser("delete", help="delete a memory (JSON)")
    dele.add_argument("memory_id")

    return p


def _machine(args: argparse.Namespace) -> Machine:
    root = Path(args.root).expanduser().resolve()
    return Machine(root)


def cmd_init(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    cfg = Config.load(root)
    cfg.save(root / "config.json")
    Machine(root, config=cfg).save()  # create empty tape/manifest/whiteboard
    print(f"initialized project at {root}")
    print(f"  model: {cfg.model} (api key from ${cfg.api_key_env})")
    print(f"  capacity per agent group: {cfg.capacity}")
    return 0


def cmd_add(args: argparse.Namespace) -> int:
    m = _machine(args)
    files = [f.strip() for f in args.files.split(",") if f.strip()]
    rec = MemoryRecord(type=args.type, summary=args.summary, why=args.why, files=files)
    try:
        res = m.add_memory(rec)
    except SecretError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    print(f"appended {res['record']['id']} [{res['record']['type']}] {res['record']['summary']}")
    print(f"  group {res['group']} -> agent {res['agent']}" + (" (new agent created)" if res["new_agent"] else ""))
    return 0


def cmd_subject(args: argparse.Namespace) -> int:
    m = _machine(args)
    m.set_subject(args.subject, args.objective)
    print(f"subject set: {args.subject}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    m = _machine(args)
    try:
        result = m.run(
            args.task,
            temperature=args.temperature,
            consolidate=not args.no_consolidate,
            max_workers=args.max_workers,
        )
    except LLMError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(result, indent=2))
        return 0

    print(f"subject: {result['subject']}")
    print(f"agents consulted: {result['agents']}  (annotations proposed: {result['raw_annotations']})")
    print("remembered:")
    for a in result["kept_annotations"]:
        print(f"  - {a['memory_id']} ({a['relevance']:.2f}): {a['note']}")
    if not result["kept_annotations"]:
        print("  (none)")
    if result["consolidated"]:
        print("whiteboard consolidated this cycle")
    if result["context_consolidated"]:
        print("chatbot context consolidated this cycle")
    print("reply:")
    print("  " + result["reply"].replace("\n", "\n  "))
    if result["memories_saved"]:
        print("saved to tape:")
        for rec in result["memories_saved"]:
            print(f"  - {rec['id']} [{rec['type']}] {rec['summary']}")
    print(f"tape: {result['tape_records']} records | groups: {result['groups']} | agents: {result['agents']}")
    return 0


def cmd_consolidate(args: argparse.Namespace) -> int:
    m = _machine(args)
    result = m.consolidate(temperature=args.temperature, use_llm=args.llm)
    print(f"consolidated (from {result['consolidated_from']})")
    print(f"persisted to tape: {len(result['persisted'])} record(s)")
    print("summary:")
    print("  " + result["summary"].replace("\n", "\n  "))
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    st = _machine(args).status()
    print(json.dumps(st, indent=2))
    return 0


def cmd_whiteboard(args: argparse.Namespace) -> int:
    m = _machine(args)
    print(m.whiteboard.render(include_annotations=not args.no_annotations))
    return 0


def cmd_context(args: argparse.Namespace) -> int:
    m = _machine(args)
    print(m.context.render() or "(empty context)")
    return 0


def _j(obj: dict[str, Any]) -> int:
    print(json.dumps(obj, ensure_ascii=False))
    return 0


def cmd_recall(args: argparse.Namespace) -> int:
    m = _machine(args)
    if getattr(args, "agent_mode", ""):
        m.config.agent_mode = args.agent_mode
        if args.agent_mode == "view":
            m.config.router_enabled = True
            if m.config.router_mode not in {"views", "cascade"}:
                m.config.router_mode = "views"
            if m.config.view_dimension_mode == "off":
                m.config.view_dimension_mode = "auto"
    if getattr(args, "whiteboard_mode", ""):
        m.config.whiteboard_mode = args.whiteboard_mode
    if getattr(args, "dimension_mode", ""):
        m.config.view_dimension_mode = args.dimension_mode
    if getattr(args, "attention", ""):
        m.config.attention_mode = args.attention
    if getattr(args, "evidence_payload", ""):
        m.config.evidence_payload = args.evidence_payload
    views = [v.strip() for v in (args.views or "").split(",") if v.strip()]
    try:
        result = m.recall(
            args.question,
            cross_session=args.cross_session,
            views=views or None,
            temperature=args.temperature,
            max_workers=args.max_workers,
        )
    except LLMError as e:
        return _j({"ok": False, "error": str(e)})
    return _j(result)


def cmd_views(args: argparse.Namespace) -> int:
    m = _machine(args)
    return _j({"ok": True, "views": list_views(m.tape)})


def _resolve_entity(index: Any, raw: str) -> str:
    text = str(raw or "").strip()
    if not text:
        return ""
    upper = text.upper()
    if upper in index.entities:
        return upper
    return index.resolve(text)


def _relation_detail(index: Any, relation_id: str) -> dict[str, Any] | None:
    relation = index.relations.get(relation_id)
    if relation is None:
        return None
    source = index.entities.get(relation.source)
    target = index.entities.get(relation.target)
    return {
        "id": relation.id,
        "relation": relation.relation,
        "source": relation.source,
        "source_name": source.name if source else relation.source,
        "target": relation.target,
        "target_name": target.name if target else relation.target,
        "memory_id": relation.memory_id,
        "confidence": relation.confidence,
        "kind": relation.kind,
        "extractor": relation.extractor,
        "extractor_version": relation.extractor_version,
    }


def _graph_read(store: GraphStore, machine: Machine, args: argparse.Namespace) -> dict[str, Any]:
    from .graph_recall import GraphRecall

    try:
        index = store.index()
    except Exception as exc:
        return {"ok": False, "error": f"graph unreadable: {exc}"}
    if not index.entities:
        return {"ok": False, "error": "graph is empty (run graph build first)"}
    depth = args.depth or machine.config.graph_depth
    top_k = args.top_k or machine.config.graph_top_k
    recall = GraphRecall(index, embedder=machine._embedder(), depth=depth, top_k=top_k)

    if args.action == "query":
        if not args.target:
            return {"ok": False, "error": "query needs a question or entity name"}
        result = recall.recall(args.target)
        payload = result.to_dict()
        payload["ok"] = True
        payload["entities"] = [
            {"id": eid, "name": index.entities[eid].name, "type": index.entities[eid].type}
            for eid in result.seeds
            if eid in index.entities
        ]
        for item in payload["evidence"]:
            item["path_details"] = [
                detail
                for path in item.get("paths", [])
                for detail in [_relation_detail(index, rid) for rid in path.get("relations", [])]
                if detail
            ]
        return payload

    source = _resolve_entity(index, args.target)
    target = _resolve_entity(index, args.target_b)
    if not source or not target:
        return {
            "ok": False,
            "error": f"unknown entity: {args.target!r} / {args.target_b!r}",
        }
    trails = index.paths(source, target, max_depth=depth, limit=top_k)
    paths: list[dict[str, Any]] = []
    memories: list[str] = []
    for trail in trails:
        details = [d for d in (_relation_detail(index, r.id) for r in trail) if d]
        for detail in details:
            if detail["memory_id"] and detail["memory_id"] not in memories:
                memories.append(detail["memory_id"])
        paths.append(
            {
                "nodes": [source] + [relation.target for relation in trail],
                "relations": [relation.id for relation in trail],
                "detail": details,
            }
        )
    return {
        "ok": True,
        "source": {"id": source, "name": index.entities[source].name},
        "target": {"id": target, "name": index.entities[target].name},
        "paths": paths,
        "evidence": memories,
    }


def cmd_graph(args: argparse.Namespace) -> int:
    m = _machine(args)
    store = GraphStore(resolve_path(m.root, m.config.graph_path))
    name = args.extractor
    if not name:
        recorded = str(store.meta().get("tag") or "").split("/")[0]
        name = recorded or ("llm" if args.action == "build" else "noop")
    resolver = None
    if name == "llm":
        from .graph_extract import GraphExtractor

        extractor_name = "llm"
        if args.action == "build":
            from .graph_resolve import GraphResolver

            try:
                extractor = GraphExtractor(m._ensure_client())
            except LLMError as exc:
                return _j({"ok": False, "error": str(exc)})
            spec = ExtractorSpec(extractor.extract, extractor.version)
            resolver = GraphResolver(
                embedder=m._embedder(),
                auto=m.config.graph_confidence_auto,
                hypothesis=m.config.graph_confidence_hypothesis,
            )
        else:  # status/explain only need the tag, never a client
            spec = ExtractorSpec(lambda record: {}, GraphExtractor.VERSION)
    else:
        spec = EXTRACTORS.get(name)
        if spec is None:
            return _j({"ok": False, "error": f"unknown extractor: {name}"})
        extractor_name = name
    tag = f"{extractor_name}/{spec.version}"
    if args.action == "status":
        return _j(
            graph_status(
                store,
                m.tape,
                extract_types=m.config.graph_extract_types,
                extractor_tag=tag,
            )
        )
    if args.action == "explain":
        if not args.target:
            return _j({"ok": False, "error": "explain needs a relation id"})
        return _j(explain_relation(store, m.tape, args.target))
    if args.action in {"query", "path"}:
        return _j(_graph_read(store, m, args))
    return _j(
        build_graph(
            m.tape,
            store,
            spec,
            extract_types=m.config.graph_extract_types,
            rebuild=args.rebuild,
            extractor_name=extractor_name,
            resolver=resolver,
            max_attempts=m.config.graph_max_attempts,
        )
    )


def cmd_sessions(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser().resolve()
    sdir = sessions_dir_for(root)
    if sdir is None:
        return _j({"ok": False, "error": "not a session store (expected .../sessions/<id>)"})
    return _j({"ok": True, "sessions": list_sessions(sdir)})


def cmd_rollup(args: argparse.Namespace) -> int:
    m = _machine(args)
    return _j(m.rollup(keep_recent=args.keep_recent, temperature=args.temperature))


def cmd_rehydrate(args: argparse.Namespace) -> int:
    m = _machine(args)
    return _j(m.rehydrate(args.memory_id, reactivate=args.reactivate))


def cmd_checkpoint(args: argparse.Namespace) -> int:
    m = _machine(args)
    memories: list[dict[str, Any]] = []
    if args.memories:
        try:
            parsed = json.loads(args.memories)
            if isinstance(parsed, list):
                memories = parsed
        except json.JSONDecodeError:
            memories = []
    try:
        result = m.checkpoint(
            args.question, args.summary, memories=memories, temperature=args.temperature
        )
    except LLMError as e:
        return _j({"ok": False, "error": str(e)})
    return _j(result)


def cmd_remember(args: argparse.Namespace) -> int:
    m = _machine(args)
    files = [f.strip() for f in args.files.split(",") if f.strip()]
    views = [v.strip() for v in (args.views or "").split(",") if v.strip()]
    rec = MemoryRecord(type=args.type, summary=args.summary, why=args.why, files=files, views=views)
    try:
        return _j(m.add_memory(rec))
    except SecretError as e:
        return _j({"ok": False, "error": str(e)})


def cmd_list(args: argparse.Namespace) -> int:
    m = _machine(args)
    return _j({"ok": True, "records": m.list_records()})


def cmd_attach(args: argparse.Namespace) -> int:
    m = _machine(args)
    return _j(m.attach(args.path, chunk_size=args.chunk_size))


def cmd_archive(args: argparse.Namespace) -> int:
    m = _machine(args)
    ok = m.tape.set_status(args.memory_id, "archived")
    return _j({"ok": ok, "id": args.memory_id, "status": "archived"})


def cmd_delete(args: argparse.Namespace) -> int:
    m = _machine(args)
    ok = m.tape.delete(args.memory_id)
    return _j({"ok": ok, "id": args.memory_id})


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    handlers: dict[str, Any] = {
        "init": cmd_init,
        "add": cmd_add,
        "subject": cmd_subject,
        "run": cmd_run,
        "consolidate": cmd_consolidate,
        "status": cmd_status,
        "whiteboard": cmd_whiteboard,
        "context": cmd_context,
        "recall": cmd_recall,
        "checkpoint": cmd_checkpoint,
        "remember": cmd_remember,
        "list": cmd_list,
        "attach": cmd_attach,
        "archive": cmd_archive,
        "delete": cmd_delete,
        "sessions": cmd_sessions,
        "views": cmd_views,
        "graph": cmd_graph,
        "rollup": cmd_rollup,
        "rehydrate": cmd_rehydrate,
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
