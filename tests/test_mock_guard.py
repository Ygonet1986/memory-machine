"""Mock guard: the offline mock must be explicit, marked and never silent.

Ensures `MEMORY_MACHINE_MOCK=1` is the only way to get the mock from a config,
that it is detectable (`is_mock`), that it warns loudly on first use, and that
direct (live) client construction is unaffected by the env var.
"""

from __future__ import annotations

from memory_machine import llm
from memory_machine.config import Config


def test_mock_requires_explicit_env(monkeypatch):
    monkeypatch.delenv("MEMORY_MACHINE_MOCK", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    try:
        llm.LLMClient.from_config(Config())
    except llm.LLMError:
        pass
    else:  # pragma: no cover - defensive
        raise AssertionError("from_config must require a key when not mocked")


def test_mock_is_marked_and_warns(monkeypatch, capsys):
    monkeypatch.setenv("MEMORY_MACHINE_MOCK", "1")
    llm.MockLLMClient._warned = False  # reset the one-shot warning
    client = llm.LLMClient.from_config(Config())
    assert getattr(client, "is_mock", False) is True
    captured = capsys.readouterr()
    assert "MEMORY_MACHINE_MOCK" in captured.err
    reply = client.complete([
        {"role": "system", "content": 'Return {"annotations": [...]} for M0001'},
    ])
    assert "annotations" in reply and "M0001" in reply


def test_env_mock_does_not_replace_direct_live_clients(monkeypatch):
    monkeypatch.setenv("MEMORY_MACHINE_MOCK", "1")
    live = llm.LLMClient("https://api.example.invalid", "key", "model")
    assert getattr(live, "is_mock", False) is False
