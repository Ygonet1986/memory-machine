"""LLM client (OpenAI-compatible chat completions) + robust JSON helpers.

The client is intentionally minimal and dependency-free (stdlib ``urllib``),
mirroring the existing DeepSeek sidecar pattern. Any object exposing
``complete(messages, *, temperature) -> str`` can be used in place of an
``LLMClient`` (e.g. a fake in tests).
"""

from __future__ import annotations

import json
import os
import ssl
import time
import urllib.error
import urllib.request
from typing import Any

from .config import Config

_RETRYABLE_HTTP = {429, 500, 502, 503, 504}


def _ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    try:
        import certifi  # noqa: PLC0415

        ctx.load_verify_locations(certifi.where())
    except Exception:
        pass
    return ctx


class LLMError(RuntimeError):
    pass


class LLMClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        *,
        timeout: int = 120,
        retries: int = 3,
        backoff: float = 1.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.retries = retries
        self.backoff = backoff

    @classmethod
    def from_config(cls, config: Config, api_key: str | None = None) -> "LLMClient":
        key = api_key or os.environ.get(config.api_key_env, "")
        if not key:
            raise LLMError(f"{config.api_key_env} is not set")
        return cls(config.base_url, key, config.model)

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        """POST with retry/backoff on transient HTTP errors and network failures."""
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        last_err: Exception | None = None
        for attempt in range(self.retries + 1):
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers=headers,
                method="POST",
            )
            try:
                with urllib.request.urlopen(
                    req, timeout=self.timeout, context=_ssl_context()
                ) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                if e.code in _RETRYABLE_HTTP and attempt < self.retries:
                    last_err = e
                    time.sleep(self.backoff * (2 ** attempt))
                    continue
                body = e.read().decode("utf-8", errors="replace")[:2000]
                raise LLMError(f"HTTP {e.code}: {body}") from e
            except Exception as e:
                if attempt < self.retries:
                    last_err = e
                    time.sleep(self.backoff * (2 ** attempt))
                    continue
                raise LLMError(str(e)) from e
        raise LLMError(f"request failed after {self.retries} retries: {last_err}")

    def complete(self, messages: list[dict[str, str]], *, temperature: float = 0.0) -> str:
        content, _reasoning = self.complete_with_reasoning(messages, temperature=temperature)
        return content

    def stream(
        self, messages: list[dict[str, str]], *, temperature: float = 0.0
    ):
        """Yield ``(content_delta, reasoning_delta)`` tuples from a streaming call."""
        if not self.api_key:
            raise LLMError("api key is not set")
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "stream": True,
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=self.timeout, context=_ssl_context()) as resp:
            for line in resp:
                line = line.decode("utf-8", errors="replace").strip()
                if not line.startswith("data:"):
                    continue
                data = line[len("data:"):].strip()
                if data == "[DONE]":
                    break
                try:
                    obj = json.loads(data)
                except json.JSONDecodeError:
                    continue
                try:
                    delta = obj["choices"][0].get("delta") or {}
                except (KeyError, IndexError, TypeError):
                    continue
                yield delta.get("content") or "", delta.get("reasoning_content") or ""

    def complete_with_reasoning(
        self, messages: list[dict[str, str]], *, temperature: float = 0.0
    ) -> tuple[str, str]:
        """Return ``(content, reasoning_content)`` from a chat completion.

        Reasoning models (e.g. DeepSeek v4) emit a ``reasoning_content`` field
        alongside the final ``content``. Both are captured; callers that only
        want the answer use :meth:`complete`.
        """
        if not self.api_key:
            raise LLMError("api key is not set")
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        data = self._post(payload)
        try:
            message = data["choices"][0]["message"]
            return message.get("content") or "", message.get("reasoning_content") or ""
        except (KeyError, IndexError, TypeError) as e:
            raise LLMError("unexpected LLM response shape") from e


def extract_json_object(text: str) -> dict[str, Any]:
    """Extract the first JSON object from model output.

    Tolerates: bare objects, fenced ```json blocks, and leading prose.
    Returns an empty dict when no object is found.
    """
    if not text:
        return {}
    stripped = text.strip()
    try:
        obj = json.loads(stripped)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass

    # Fenced JSON block
    fence_start = stripped.find("```")
    if fence_start != -1:
        after = stripped[fence_start + 3 :]
        nl = after.find("\n")
        after = after[nl + 1 :] if nl != -1 else after
        fence_end = after.find("```")
        if fence_end != -1:
            try:
                obj = json.loads(after[:fence_end].strip())
                if isinstance(obj, dict):
                    return obj
            except json.JSONDecodeError:
                pass

    # First balanced object via raw_decode at each '{' position
    decoder = json.JSONDecoder()
    i = 0
    while True:
        i = stripped.find("{", i)
        if i == -1:
            return {}
        try:
            obj, _ = decoder.raw_decode(stripped[i:])
        except json.JSONDecodeError:
            i += 1
            continue
        if isinstance(obj, dict):
            return obj
        i += 1
