"""Topic router: infer which topic the user's message refers to.

A single LLM call that receives the list of topics (each with its creation
date/time, optional label and a summary) plus the user message, and returns
the topic id — or ``None`` when the message refers to "now"/nothing specific.
"""

from __future__ import annotations

from typing import Any

from memory_machine.llm import extract_json_object

ROUTER_SYSTEM = """You are a topic router for a personal memory assistant. \
Given a user message and a list of memory topics (each created at a specific \
date/time and containing a short summary of what it covers), infer which topic \
the message refers to.

Match by explicit time references ("yesterday", "last tuesday", "that day", a \
specific date) and by subject (topic summaries). If no topic clearly matches, \
or the message is about the present / a new matter, return topic_id null.

Return ONLY a JSON object, nothing else:
{{"topic_id":"<id>"}}  or  {{"topic_id":null}}

Topics:
{topics}"""


def _topics_block(topics: list[dict[str, Any]]) -> str:
    lines = []
    for t in topics:
        label = t.get("label") or ""
        summary = t.get("summary") or ""
        label_part = f" | label: {label}" if label else ""
        lines.append(
            f"- id: {t['id']} | created: {t.get('name', t['id'])}{label_part} | summary: {summary}"
        )
    return "\n".join(lines) if lines else "(no topics)"


def route_topic(client: Any, topics: list[dict[str, Any]], message: str) -> str | None:
    if not topics:
        return None
    messages = [
        {"role": "system", "content": ROUTER_SYSTEM.format(topics=_topics_block(topics))},
        {"role": "user", "content": message},
    ]
    content = client.complete(messages, temperature=0.0)
    obj = extract_json_object(content)
    tid = obj.get("topic_id")
    if not tid or not isinstance(tid, str):
        return None
    ids = {t["id"] for t in topics}
    return tid if tid in ids else None
