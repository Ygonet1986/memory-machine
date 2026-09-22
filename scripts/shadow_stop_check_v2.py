#!/usr/bin/env python3
"""Stopping-rule checker v2 for the admission-shadow-v2 product window.

Reports ONLY the coverage criteria frozen in
``docs/ADMISSION_SHADOW_V2_PREREG.md`` (counts, sessions, days, category
coverage, judged-subsample size, malformed records). It computes no
admission-outcome metric - the sample must not be inspected before the stop.

    python3 scripts/shadow_stop_check_v2.py --log DIR [--log FILE] [--glob PAT]

Exit codes: 0 = all criteria met (stop), 2 = not met, 1 = usage/IO error.
"""

from __future__ import annotations

import argparse
import glob as globlib
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

CRITERIA = {
    "min_unique_scored_records": 200,
    "min_sessions": 15,
    "min_days": 21,
    "min_event_log_records": 30,
    "min_lexical_two_plus": 100,
    "min_zero_candidates": 10,
    "min_judged_subsample": 40,
    "max_malformed_ratio": 0.01,
}
LOG_NAME = "admission_shadow.jsonl"
OUTPUT_KEYS = {"criteria", "counts", "met", "missing", "files", "checked_at"}


def discover_logs(paths: list[str], patterns: list[str]) -> list[Path]:
    found: set[Path] = set()
    for raw in paths:
        path = Path(raw).expanduser()
        if path.is_dir():
            found.update(path.rglob(LOG_NAME))
        elif path.is_file():
            found.add(path)
        else:
            raise FileNotFoundError(f"--log not found: {raw}")
    for pattern in patterns:
        found.update(Path(p) for p in globlib.glob(str(Path(pattern).expanduser()),
                                                   recursive=True)
                     if Path(p).is_file())
    return sorted(found)


def parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)


def valid_record(entry: object) -> bool:
    if not isinstance(entry, dict) or entry.get("v") != 2:
        return False
    if not isinstance(entry.get("session_id"), str) or not entry["session_id"]:
        return False
    question = entry.get("question")
    if not isinstance(question, dict) or not question.get("sha256"):
        return False
    if not isinstance(entry.get("cached"), bool):
        return False
    if not isinstance(entry.get("judged_subsample"), bool):
        return False
    lexical = entry.get("lexical")
    if not isinstance(lexical, dict) or not isinstance(lexical.get("candidates"), list):
        return False
    if not isinstance(entry.get("active"), list):
        return False
    if not isinstance(entry.get("event_log"), list):
        return False
    return parse_timestamp(entry.get("ts")) is not None


def check(files: list[Path]) -> dict[str, object]:
    counts = {
        "valid_records": 0, "scored_records": 0, "unique_scored_records": 0,
        "duplicates": 0, "cached_records": 0, "malformed_records": 0,
        "sessions": 0, "days": 0, "event_log_records": 0,
        "lexical_two_plus": 0, "zero_candidates": 0, "judged_subsample": 0,
    }
    sessions: set[str] = set()
    seen: dict[tuple[str, str], dict[str, object]] = {}
    stamps: list[datetime] = []
    files_info: list[dict[str, object]] = []

    for path in files:
        payload = path.read_bytes()
        files_info.append({"path": str(path),
                           "sha256": hashlib.sha256(payload).hexdigest(),
                           "lines": payload.count(b"\n")})
        for line in payload.decode("utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                counts["malformed_records"] += 1
                continue
            if not valid_record(entry):
                counts["malformed_records"] += 1
                continue
            counts["valid_records"] += 1
            sessions.add(str(entry["session_id"]))
            stamps.append(parse_timestamp(entry["ts"]))  # type: ignore[arg-type]
            if entry["cached"]:
                counts["cached_records"] += 1
                continue
            counts["scored_records"] += 1
            key = (str(entry["session_id"]), str(entry["question"]["sha256"]))
            if key in seen:
                counts["duplicates"] += 1
                continue
            seen[key] = entry

    scored = list(seen.values())
    counts["unique_scored_records"] = len(scored)
    counts["sessions"] = len(sessions)
    if stamps:
        counts["days"] = (max(stamps).date() - min(stamps).date()).days + 1
    for entry in scored:
        lexical = entry["lexical"]
        lexical_count = len(lexical.get("candidates") or [])
        event_count = len(entry.get("event_log") or [])
        if event_count:
            counts["event_log_records"] += 1
        if lexical_count >= 2:
            counts["lexical_two_plus"] += 1
        if lexical_count == 0 and event_count == 0:
            counts["zero_candidates"] += 1
        if entry.get("judged_subsample"):
            counts["judged_subsample"] += 1

    total_lines = counts["valid_records"] + counts["malformed_records"]
    malformed_ratio = (counts["malformed_records"] / total_lines
                       if total_lines else 0.0)
    checks = {
        name: counts[key] >= threshold
        for name, (key, threshold) in {
            "min_unique_scored_records": ("unique_scored_records", 200),
            "min_sessions": ("sessions", 15),
            "min_days": ("days", 21),
            "min_event_log_records": ("event_log_records", 30),
            "min_lexical_two_plus": ("lexical_two_plus", 100),
            "min_zero_candidates": ("zero_candidates", 10),
            "min_judged_subsample": ("judged_subsample", 40),
        }.items()}
    checks["max_malformed_ratio"] = malformed_ratio <= CRITERIA["max_malformed_ratio"]
    missing = [name for name, ok in checks.items() if not ok]
    report = {
        "criteria": dict(CRITERIA),
        "counts": dict(counts, malformed_ratio=round(malformed_ratio, 6)),
        "met": not missing,
        "missing": missing,
        "files": files_info,
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    assert set(report) == OUTPUT_KEYS
    return report


def render(report: dict[str, object]) -> str:
    lines = ["# admission-shadow-v2 stopping-rule check", "",
             f"checked_at: {report['checked_at']}",
             f"files: {len(report['files'])}", ""]
    for name, value in report["criteria"].items():
        lines.append(f"- {name}: {value}")
    lines += ["", "counts:"]
    for name, value in report["counts"].items():
        lines.append(f"  {name}: {value}")
    lines += ["", "met: " + str(report["met"])]
    if report["missing"]:
        lines.append("missing: " + ", ".join(report["missing"]))
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log", action="append", default=[])
    parser.add_argument("--glob", action="append", default=[])
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        files = discover_logs(args.log, args.glob)
    except OSError as error:
        print(f"shadow_stop_check_v2: {error}", file=sys.stderr)
        return 1
    if not files:
        print("shadow_stop_check_v2: no logs found", file=sys.stderr)
        return 1
    report = check(files)
    print(json.dumps(report, indent=2, sort_keys=True) if args.json
          else render(report))
    return 0 if report["met"] else 2


if __name__ == "__main__":
    sys.exit(main())
