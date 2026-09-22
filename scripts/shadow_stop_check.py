#!/usr/bin/env python3
"""Stopping-rule checker for the admission-shadow-v1 collection phase.

Reports ONLY the frozen coverage criteria from
``docs/ADMISSION_SHADOW_STOPPING_RULE.md`` (counts, sessions, days, category
coverage, malformed lines). It deliberately computes no admission-outcome
metric (no precision, no availability, no score distributions) - the sample
must not be inspected before the stopping rule is met.

    python3 scripts/shadow_stop_check.py --log DIR_OR_FILE [--log ...]
    python3 scripts/shadow_stop_check.py --glob 'PATH/**/admission_shadow.jsonl'

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
    "min_unique_scored_records": 300,
    "min_sessions": 20,
    "min_days": 21,
    "min_event_log_records": 50,
    "min_both_records": 30,
    "min_zero_candidate_records": 10,
    "min_short_queries": 50,
    "min_long_queries": 50,
    "max_malformed_ratio": 0.01,
}
SHORT_TOKENS = 5
LONG_TOKENS = 12
LOG_NAME = "admission_shadow.jsonl"

OUTPUT_KEYS = {
    "criteria", "counts", "met", "missing", "files", "checked_at",
}


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
        expanded = globlib.glob(str(Path(pattern).expanduser()), recursive=True)
        found.update(Path(p) for p in expanded if Path(p).is_file())
    return sorted(found)


def parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    text = value.replace("Z", "+00:00")
    try:
        stamp = datetime.fromisoformat(text)
    except ValueError:
        return None
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)


def valid_record(entry: object) -> bool:
    if not isinstance(entry, dict) or entry.get("v") != 1:
        return False
    if not isinstance(entry.get("session_id"), str) or not entry["session_id"]:
        return False
    question = entry.get("question")
    if not isinstance(question, dict) or not question.get("sha256"):
        return False
    if not isinstance(entry.get("cached"), bool):
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
        "sessions": 0, "days": 0, "event_log_records": 0, "both_records": 0,
        "zero_candidate_records": 0, "short_queries": 0, "long_queries": 0,
    }
    sessions: set[str] = set()
    seen: dict[tuple[str, str], dict[str, object]] = {}
    stamps: list[datetime] = []
    file_info: list[dict[str, object]] = []

    for path in files:
        payload = path.read_bytes()
        file_info.append({
            "path": str(path),
            "sha256": hashlib.sha256(payload).hexdigest(),
            "lines": payload.count(b"\n"),
        })
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
        active = entry["active"] or []
        event = entry["event_log"] or []
        tokens = entry["question"].get("tokens")
        if event:
            counts["event_log_records"] += 1
        if active and event:
            counts["both_records"] += 1
        if not active and not event:
            counts["zero_candidate_records"] += 1
        if isinstance(tokens, int):
            if tokens <= SHORT_TOKENS:
                counts["short_queries"] += 1
            if tokens >= LONG_TOKENS:
                counts["long_queries"] += 1

    total_lines = counts["valid_records"] + counts["malformed_records"]
    malformed_ratio = (counts["malformed_records"] / total_lines
                       if total_lines else 0.0)
    checks = {
        "min_unique_scored_records": counts["unique_scored_records"]
        >= CRITERIA["min_unique_scored_records"],
        "min_sessions": counts["sessions"] >= CRITERIA["min_sessions"],
        "min_days": counts["days"] >= CRITERIA["min_days"],
        "min_event_log_records": counts["event_log_records"]
        >= CRITERIA["min_event_log_records"],
        "min_both_records": counts["both_records"] >= CRITERIA["min_both_records"],
        "min_zero_candidate_records": counts["zero_candidate_records"]
        >= CRITERIA["min_zero_candidate_records"],
        "min_short_queries": counts["short_queries"] >= CRITERIA["min_short_queries"],
        "min_long_queries": counts["long_queries"] >= CRITERIA["min_long_queries"],
        "max_malformed_ratio": malformed_ratio <= CRITERIA["max_malformed_ratio"],
    }
    missing = [name for name, ok in checks.items() if not ok]
    report = {
        "criteria": dict(CRITERIA, short_tokens=SHORT_TOKENS,
                         long_tokens=LONG_TOKENS),
        "counts": dict(counts, malformed_ratio=round(malformed_ratio, 6)),
        "met": not missing,
        "missing": missing,
        "files": file_info,
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    assert set(report) == OUTPUT_KEYS
    return report


def render(report: dict[str, object]) -> str:
    counts = report["counts"]
    lines = ["# admission-shadow-v1 stopping-rule check", "",
             f"checked_at: {report['checked_at']}",
             f"files: {len(report['files'])}", ""]
    for name, value in report["criteria"].items():
        lines.append(f"- {name}: {value}")
    lines += ["", "counts:"]
    for name, value in counts.items():
        lines.append(f"  {name}: {value}")
    lines += ["", "met: " + str(report["met"])]
    if report["missing"]:
        lines.append("missing: " + ", ".join(report["missing"]))
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log", action="append", default=[],
                        help="log file or directory (repeatable)")
    parser.add_argument("--glob", action="append", default=[],
                        help="glob pattern matching log files (repeatable)")
    parser.add_argument("--json", action="store_true", help="print JSON only")
    args = parser.parse_args()
    try:
        files = discover_logs(args.log, args.glob)
    except OSError as error:
        print(f"shadow_stop_check: {error}", file=sys.stderr)
        return 1
    if not files:
        print("shadow_stop_check: no logs found", file=sys.stderr)
        return 1
    report = check(files)
    print(json.dumps(report, indent=2, sort_keys=True) if args.json
          else render(report))
    return 0 if report["met"] else 2


if __name__ == "__main__":
    sys.exit(main())
