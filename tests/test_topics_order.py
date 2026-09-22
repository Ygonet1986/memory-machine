"""Deterministic topic ordering under coarse clocks (Windows regression).

Windows' clock granularity can stamp two topics with the same ``created_at``;
ordering must still be deterministic, with the later id first. This pins the
tie-breaker that keeps auto-topic selection reproducible on every platform.
"""

from __future__ import annotations

from datetime import datetime

from app import topics as topics_mod


class FrozenClock:
    """`datetime` stub whose now() has second granularity (coarse clock)."""

    frozen = datetime.now().replace(microsecond=0)

    @classmethod
    def now(cls) -> datetime:
        return cls.frozen


def test_same_second_topics_order_by_id(tmp_path, monkeypatch):
    monkeypatch.setattr(topics_mod, "datetime", FrozenClock)
    first = topics_mod.create_topic(tmp_path, label="a")
    second = topics_mod.create_topic(tmp_path, label="b")
    assert first["created_at"] == second["created_at"]  # coarse clock tie
    assert first["id"] != second["id"]

    ordered = topics_mod.list_topics(tmp_path)
    assert [t["id"] for t in ordered] == [second["id"], first["id"]]
    assert topics_mod.today_topic(tmp_path)["id"] == second["id"]
    assert topics_mod.most_recent_topic(tmp_path)["id"] == second["id"]
