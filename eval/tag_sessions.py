"""Write-time view tagging for external benchmarks (Fase 2).

LongMemEval/LoCoMo sessions have no views. This module labels each session with
a coarse topic taxonomy and a free subject slug in batched LLM calls, caching
the result per session id so reruns are free. The labels become `topic/*` and
`subject/*` views on the session's memory record, so the dimension-aware view
router and the view agents can run on external data.

Run standalone to tag and inspect:  PYTHONPATH=src python3 eval/tag_sessions.py --dataset longmemeval --limit 20
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from memory_machine.llm import extract_json_object

TAXONOMY = [
    "work", "tech", "health", "family", "travel", "food",
    "finance", "hobbies", "education", "home", "events", "other",
]

TAGGER_PROMPT = """You label memory sessions with a coarse topic taxonomy and a \
subject slug. The labels become retrieval views, so they must be reusable across \
sessions.

Topics (choose 1-3, exactly these words, lowercase):
{taxonomy}

For each session below, return its topics and a subject: a short lowercase slug \
(2-3 hyphenated words) naming the project, person, place or domain the session \
is about. Reuse the same subject for sessions about the same thing.

Sessions:

{sessions}

Return ONLY JSON, nothing else:
{{"labels":[{{"id":"<session id>","topics":["tech","work"],"subject":"memory-machine"}}]}}"""


def _slug(text: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return text[:40] or "general"


def _cache_path(dataset: str) -> Path:
    return Path(__file__).resolve().parent / "data" / f"tags_{dataset}.json"


def load_cache(dataset: str) -> dict[str, dict[str, Any]]:
    path = _cache_path(dataset)
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_cache(dataset: str, cache: dict[str, dict[str, Any]]) -> None:
    path = _cache_path(dataset)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")


def _parse_labels(content: str) -> list[dict[str, Any]]:
    obj = extract_json_object(content)
    labels = obj.get("labels")
    if not isinstance(labels, list):
        return []
    out: list[dict[str, Any]] = []
    for item in labels:
        if not isinstance(item, dict) or not item.get("id"):
            continue
        topics = [
            str(t).strip().lower()
            for t in (item.get("topics") or [])
            if str(t).strip().lower() in TAXONOMY
        ]
        out.append(
            {
                "id": str(item["id"]),
                "topics": list(dict.fromkeys(topics))[:3] or ["other"],
                "subject": _slug(str(item.get("subject") or "")),
            }
        )
    return out


def tag_sessions(
    dataset: str,
    sessions: list[dict[str, Any]],
    client: Any,
    *,
    batch: int = 8,
    max_chars: int = 600,
    verbose: bool = True,
) -> dict[str, dict[str, Any]]:
    """Tag sessions with topics/subject, using and updating the on-disk cache."""
    cache = load_cache(dataset)
    todo = [s for s in sessions if s["id"] not in cache]
    for start in range(0, len(todo), batch):
        chunk = todo[start : start + batch]
        lines = [
            f"[{s['id']}]\n{s['text'][:max_chars]}" for s in chunk
        ]
        messages = [
            {
                "role": "system",
                "content": TAGGER_PROMPT.format(
                    taxonomy=", ".join(TAXONOMY), sessions="\n\n".join(lines)
                ),
            },
            {"role": "user", "content": "Label the sessions."},
        ]
        try:
            content = client.complete(messages, temperature=0.0)
            labels = _parse_labels(content)
        except Exception:
            labels = []
        by_id = {item["id"]: item for item in labels}
        for s in chunk:
            cache[s["id"]] = by_id.get(
                s["id"], {"id": s["id"], "topics": ["other"], "subject": "general"}
            )
        if verbose:
            print(f"  tagged {min(start + batch, len(todo))}/{len(todo)}", flush=True)
        save_cache(dataset, cache)
    return cache


def views_for(tags: dict[str, Any] | None) -> list[str]:
    if not tags:
        return []
    views = [f"topic/{t}" for t in tags.get("topics") or []]
    subject = tags.get("subject")
    if subject:
        views.append(f"subject/{subject}")
    return views


def main() -> None:
    import os
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dataset", choices=["longmemeval", "locomo"], default="longmemeval")
    p.add_argument("--limit", type=int, default=10, help="questions to sample sessions from")
    p.add_argument("--batch", type=int, default=8)
    p.add_argument("--model", default="deepseek-v4-flash")
    p.add_argument("--api-key", default="")
    args = p.parse_args()

    from memory_machine.llm import LLMClient

    api_key = args.api_key or os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key:
        raise SystemExit("set DEEPSEEK_API_KEY (or --api-key)")

    from external_bench import DATA, load_locomo, load_longmemeval

    path = DATA / ("longmemeval_s_cleaned.json" if args.dataset == "longmemeval" else "locomo10.json")
    tasks = (
        load_longmemeval(path, args.limit, 7)
        if args.dataset == "longmemeval"
        else load_locomo(path, args.limit, 7)
    )
    sessions: dict[str, dict[str, Any]] = {}
    for task in tasks:
        for s in task["sessions"]:
            sessions.setdefault(s["id"], s)
    client = LLMClient("https://api.deepseek.com", api_key, args.model, retries=1, backoff=0.5)
    tags = tag_sessions(args.dataset, list(sessions.values()), client, batch=args.batch)
    sample = list(tags.items())[:10]
    for sid, label in sample:
        print(f"  {sid}: {label['topics']} subject={label['subject']}")
    print(f"cached {len(tags)} sessions -> {_cache_path(args.dataset)}")


if __name__ == "__main__":
    main()
