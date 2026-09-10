from pathlib import Path

from app.topics import (
    active_id,
    create_topic,
    delete_topic,
    display_name,
    list_topics,
    most_recent_topic,
    set_active,
    set_label,
    set_summary,
    today_topic,
    topic_root,
    touch_activity,
)


def test_create_topic_name_is_timestamp(tmp_path):
    base = Path(tmp_path)
    t = create_topic(base)
    assert t["name"]  # e.g. "2026-09-08 23:35"
    assert t["label"] == ""
    assert t["id"]
    assert topic_root(base, t["id"]).is_dir()
    assert active_id(base) == t["id"]


def test_create_topic_with_label(tmp_path):
    base = Path(tmp_path)
    t = create_topic(base, label="Refactor auth")
    assert t["label"] == "Refactor auth"
    assert display_name(t) == "Refactor auth"


def test_create_topic_unique_ids(tmp_path):
    base = Path(tmp_path)
    t1 = create_topic(base)
    t2 = create_topic(base)
    assert t1["id"] != t2["id"]
    assert len(list_topics(base)) == 2


def test_set_active(tmp_path):
    base = Path(tmp_path)
    create_topic(base)
    t2 = create_topic(base)
    assert set_active(base, t2["id"]) is True
    assert active_id(base) == t2["id"]
    assert set_active(base, "nope") is False


def test_set_label(tmp_path):
    base = Path(tmp_path)
    t = create_topic(base)
    updated = set_label(base, t["id"], "my label")
    assert updated["label"] == "my label"
    assert display_name(updated) == "my label"
    assert set_label(base, "nope", "x") is None


def test_set_summary(tmp_path):
    base = Path(tmp_path)
    t = create_topic(base)
    updated = set_summary(base, t["id"], "deciding the database")
    assert updated["summary"] == "deciding the database"


def test_today_topic(tmp_path):
    base = Path(tmp_path)
    t = create_topic(base)
    found = today_topic(base)
    assert found is not None
    assert found["id"] == t["id"]


def test_display_name_falls_back_to_name(tmp_path):
    base = Path(tmp_path)
    t = create_topic(base)
    assert display_name(t) == t["name"]


def test_delete_topic_removes_dir_and_index(tmp_path):
    base = Path(tmp_path)
    t1 = create_topic(base)
    t2 = create_topic(base)  # active
    result = delete_topic(base, t1["id"])
    assert result["ok"] is True
    assert not topic_root(base, t1["id"]).exists()
    assert [t["id"] for t in list_topics(base)] == [t2["id"]]
    assert active_id(base) == t2["id"]


def test_delete_active_topic_reassigns_active(tmp_path):
    base = Path(tmp_path)
    t1 = create_topic(base)
    t2 = create_topic(base)
    assert active_id(base) == t2["id"]
    result = delete_topic(base, t2["id"])
    assert result["ok"] is True
    assert active_id(base) == t1["id"]


def test_delete_last_topic_leaves_empty(tmp_path):
    base = Path(tmp_path)
    t = create_topic(base)
    delete_topic(base, t["id"])
    assert list_topics(base) == []
    assert active_id(base) == ""


def test_touch_activity_and_most_recent(tmp_path):
    import time

    base = Path(tmp_path)
    t1 = create_topic(base)
    t2 = create_topic(base)
    assert most_recent_topic(base)["id"] == t2["id"]

    time.sleep(0.01)
    touch_activity(base, t1["id"])
    assert most_recent_topic(base)["id"] == t1["id"]
