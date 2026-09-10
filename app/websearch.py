"""Web search layer (no API key): DuckDuckGo Instant Answer.

Search results are auxiliary context for the current turn only. They are
handed to the main chatbot and never touch the tape, the whiteboard, or the
memory agents.
"""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from typing import Any

from memory_machine.llm import _ssl_context

DDG_URL = "https://api.duckduckgo.com/"
USER_AGENT = "MemoryMachine/0.1 (+personal use)"

# Signals that a question likely needs current / external information.
_WEB_TRIGGERS = {
    # English
    "latest", "current", "currently", "today", "tonight", "now", "news",
    "recent", "recently", "price", "prices", "cost", "release", "released",
    "version", "update", "updates", "live", "2025", "2026", "2027",
    "search", "google", "online", "internet",
    # Portuguese
    "hoje", "agora", "atual", "atualmente", "recente", "recentes", "noticia",
    "notícia", "noticias", "notícias", "preco", "preço", "precos", "preços",
    "lancamento", "lançamento", "versao", "versão", "ultima", "última",
    "ultimo", "último", "cotacao", "cotação", "busca", "buscar", "pesquise",
    "pesquisar", "internet", "online",
}


def needs_web(query: str) -> bool:
    """Heuristic: does this question likely need a web search?"""
    q = (query or "").lower()
    tokens = set(re.findall(r"[a-z0-9à-ÿ]+", q))
    return bool(tokens & _WEB_TRIGGERS)


def search(query: str, *, limit: int = 5, timeout: int = 20) -> list[dict[str, Any]]:
    query = query.strip()
    if not query:
        return []
    params = urllib.parse.urlencode(
        {"q": query, "format": "json", "no_html": 1, "skip_disambig": 1}
    )
    url = f"{DDG_URL}?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
    except Exception:
        return []

    results: list[dict[str, Any]] = []
    if data.get("AbstractText"):
        results.append(
            {
                "title": data.get("AbstractSource") or "Result",
                "url": data.get("AbstractURL") or "",
                "snippet": data["AbstractText"],
            }
        )
    for t in data.get("RelatedTopics") or []:
        if not isinstance(t, dict):
            continue
        if "Text" in t:
            results.append(
                {
                    "title": t.get("Text", "")[:90],
                    "url": t.get("FirstURL", ""),
                    "snippet": t.get("Text", ""),
                }
            )
        elif "Topics" in t:
            for sub in t["Topics"]:
                if isinstance(sub, dict) and "Text" in sub:
                    results.append(
                        {
                            "title": sub.get("Text", "")[:90],
                            "url": sub.get("FirstURL", ""),
                            "snippet": sub.get("Text", ""),
                        }
                    )
    return results[:limit]


def format_results(results: list[dict[str, Any]]) -> str:
    if not results:
        return ""
    blocks = []
    for r in results:
        line = f"- {r.get('title', '')}"
        if r.get("snippet"):
            line += f": {r.get('snippet', '')}"
        if r.get("url"):
            line += f" ({r.get('url')})"
        blocks.append(line)
    return "\n".join(blocks)
