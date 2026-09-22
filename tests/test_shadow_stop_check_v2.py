"""Stopping-rule checker v2: coverage-only output on schema-2 records."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import shadow_stop_check_v2 as checker  # noqa: E402

BASE = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def _line(session: str, sha: str, day: int, *, cached: bool = False,
          judged: bool = False, lexical: int = 2, event: int = 0) -> str:
    return json.dumps({
        "v": 2,
        "ts": (BASE + timedelta(days=day)).isoformat(timespec="seconds"),
        "session_id": session,
        "cached": cached,
        "judged_subsample": judged,
        "question": {"sha256": sha, "chars": 40, "tokens": 8},
        "lexical": {
            "candidates": [{"memory_id": f"{sha}-L{i}"} for i in range(lexical)],
            "delivered": [], "delivered_chars": 0, "empty": lexical == 0,
            "comparator_p1_margin50": [], "comparator_p2_margin90": [],
        },
        "active": [],
        "event_log": [{"memory_id": f"{sha}-E{i}"} for i in range(event)],
    })


def _write(tmp_path: Path, lines: list[str]) -> Path:
    path = tmp_path / "admission_shadow.jsonl"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _full_sample(tmp_path: Path) -> Path:
    lines: list[str] = []
    index = 0
    blocks = (
        (120, dict(lexical=3, event=1, judged=True)),
        (40, dict(lexical=3, event=0, judged=True)),
        (30, dict(lexical=0, event=1, judged=False)),
        (10, dict(lexical=0, event=0, judged=False)),
    )
    for count, fields in blocks:
        for _ in range(count):
            lines.append(_line(f"ses-{index % 15:02d}", f"sha{index:04d}",
                               index % 21, **fields))
            index += 1
    lines.append("{not json")
    return _write(tmp_path, lines)


def test_full_sample_meets_every_criterion(tmp_path):
    report = checker.check([_full_sample(tmp_path)])
    assert set(report) == checker.OUTPUT_KEYS
    counts = report["counts"]
    assert report["met"] is True, report["missing"]
    assert counts["unique_scored_records"] == 200
    assert counts["sessions"] == 15
    assert counts["days"] == 21
    assert counts["event_log_records"] == 150
    assert counts["lexical_two_plus"] == 160
    assert counts["zero_candidates"] == 10
    assert counts["judged_subsample"] == 160


def test_duplicates_malformed_and_not_met(tmp_path):
    lines = [
        _line("s1", "same", 0),
        _line("s1", "same", 0),
        _line("s1", "other", 1, lexical=0, event=0),
        "{bad json",
        "{bad json",
        "{bad json",
    ]
    report = checker.check([_write(tmp_path, lines)])
    counts = report["counts"]
    assert counts["scored_records"] == 3
    assert counts["unique_scored_records"] == 2
    assert counts["duplicates"] == 1
    assert counts["malformed_records"] == 3
    assert report["met"] is False
    assert "min_unique_scored_records" in report["missing"]
    assert "max_malformed_ratio" in report["missing"]


def test_discover_finds_nested_logs(tmp_path):
    nested = tmp_path / "sessions" / "ses-1"
    nested.mkdir(parents=True)
    _write(nested, [_line("s1", "a" * 8, 0)])
    files = checker.discover_logs([str(tmp_path)], [])
    assert files == [nested / "admission_shadow.jsonl"]
