"""Stopping-rule checker: coverage-only output, categories, treatment rules."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import shadow_stop_check as checker  # noqa: E402

BASE = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def _line(session: str, sha: str, day: int, *, cached: bool = False,
          active: int = 1, event: int = 0, tokens: int = 8, v: int = 1) -> str:
    return json.dumps({
        "v": v,
        "ts": (BASE + timedelta(days=day)).isoformat(timespec="seconds"),
        "session_id": session,
        "cached": cached,
        "question": {"sha256": sha, "chars": 40, "tokens": tokens},
        "active": [{"memory_id": "M0001"}] * active,
        "event_log": [{"memory_id": "M0002"}] * event,
    })


def _write(tmp_path: Path, lines: list[str]) -> Path:
    path = tmp_path / "admission_shadow.jsonl"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _full_sample(tmp_path: Path) -> Path:
    lines: list[str] = []
    index = 0
    blocks = (
        (180, dict(active=1, event=1, tokens=8)),
        (60, dict(active=1, event=0, tokens=3)),
        (50, dict(active=1, event=0, tokens=15)),
        (10, dict(active=0, event=0, tokens=8)),
    )
    for count, fields in blocks:
        for _ in range(count):
            session = f"ses-{index % 20:02d}"
            day = index % 21
            lines.append(_line(session, f"sha{index:04d}", day, **fields))
            index += 1
    for extra in range(20):
        lines.append(_line(f"ses-{extra % 20:02d}", f"cache{extra:04d}", extra,
                           cached=True))
    lines.append("{not json")
    return _write(tmp_path, lines)


def test_not_met_reports_missing_criteria(tmp_path):
    path = _write(tmp_path, [_line("s1", "a" * 8, 0), _line("s2", "b" * 8, 0)])
    report = checker.check([path])
    assert report["met"] is False
    assert "min_unique_scored_records" in report["missing"]
    assert "min_sessions" in report["missing"]
    assert "min_event_log_records" in report["missing"]
    assert report["counts"]["unique_scored_records"] == 2
    assert report["counts"]["sessions"] == 2


def test_all_criteria_met_on_full_sample(tmp_path):
    path = _full_sample(tmp_path)
    report = checker.check([path])
    assert set(report) == checker.OUTPUT_KEYS
    assert set(report["counts"]) == {
        "valid_records", "scored_records", "unique_scored_records",
        "duplicates", "cached_records", "malformed_records", "sessions",
        "days", "event_log_records", "both_records", "zero_candidate_records",
        "short_queries", "long_queries", "malformed_ratio"}
    assert report["met"] is True, report["missing"]
    counts = report["counts"]
    assert counts["unique_scored_records"] == 300
    assert counts["sessions"] == 20
    assert counts["days"] == 21
    assert counts["event_log_records"] >= 50
    assert counts["both_records"] >= 30
    assert counts["zero_candidate_records"] >= 10
    assert counts["short_queries"] >= 50
    assert counts["long_queries"] >= 50
    assert counts["cached_records"] == 20
    assert counts["malformed_records"] == 1


def test_duplicates_and_malformed_ratio(tmp_path):
    lines = [
        _line("s1", "same", 0),
        _line("s1", "same", 0),
        _line("s1", "other", 1),
        "{bad json",
        "{bad json",
        "{bad json",
    ]
    path = _write(tmp_path, lines)
    report = checker.check([path])
    counts = report["counts"]
    assert counts["scored_records"] == 3
    assert counts["unique_scored_records"] == 2
    assert counts["duplicates"] == 1
    assert counts["malformed_records"] == 3
    assert report["met"] is False
    assert "max_malformed_ratio" in report["missing"]


def test_discover_logs_finds_nested_files(tmp_path):
    nested = tmp_path / "sessions" / "ses-1"
    nested.mkdir(parents=True)
    _write(nested, [_line("s1", "a" * 8, 0)])
    files = checker.discover_logs([str(tmp_path)], [])
    assert files == [nested / "admission_shadow.jsonl"]
