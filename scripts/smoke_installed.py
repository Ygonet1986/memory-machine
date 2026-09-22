#!/usr/bin/env python3
"""Cross-platform installed smoke test (L1/L10).

Builds the wheel, installs it into a clean venv, then proves the installed
product works without PYTHONPATH: init -> remember -> recall (offline mock) ->
restart -> persistence. Runs on Linux, macOS and Windows.

    python3 scripts/smoke_installed.py
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(cmd: list[str], env: dict[str, str] | None = None) -> str:
    shown = " ".join(str(part) for part in cmd)
    print(f"+ {shown}", flush=True)
    result = subprocess.run(
        [str(part) for part in cmd], check=False, text=True,
        capture_output=True, env=env,
    )
    if result.returncode != 0:
        print(result.stdout)
        print(result.stderr, file=sys.stderr)
        raise SystemExit(f"FAIL: command exited {result.returncode}: {shown}")
    return result.stdout


def main() -> int:
    work = Path(tempfile.mkdtemp(prefix="mm-smoke-"))
    print(f"smoke workdir: {work}")
    venv_dir = work / "venv"
    venv.EnvBuilder(with_pip=True).create(venv_dir)
    bin_dir = venv_dir / ("Scripts" if os.name == "nt" else "bin")
    python = bin_dir / ("python.exe" if os.name == "nt" else "python")
    pip = [str(python), "-m", "pip"]

    run(pip + ["install", "--quiet", "--upgrade", "pip", "setuptools", "wheel"])
    wheel_dir = work / "wheel"
    run(pip + ["wheel", "--quiet", "--no-deps", "-w", str(wheel_dir), str(ROOT)])
    wheel = next(wheel_dir.glob("memory_machine-*.whl"), None)
    if wheel is None:
        raise SystemExit("FAIL: wheel not built")
    print(f"wheel: {wheel.name}")
    run(pip + ["install", "--quiet", "--no-deps", str(wheel)])

    cli = bin_dir / ("memory-cli.exe" if os.name == "nt" else "memory-cli")
    if not cli.exists():
        raise SystemExit("FAIL: memory-cli entry point missing")

    env = dict(os.environ, MEMORY_MACHINE_MOCK="1")
    env.pop("DEEPSEEK_API_KEY", None)
    memory = work / "memory"

    run([str(cli), "--help"], env=env)
    run([str(python), "-m", "memory_machine", "-C", str(memory), "init"], env=env)
    run([
        str(cli), "-C", str(memory), "remember", "--type", "decision",
        "--summary", "Use Postgres for the primary datastore",
        "--why", "ACID + JSONB",
    ], env=env)
    if not (memory / "tape.jsonl").exists():
        raise SystemExit("FAIL: remember did not create the tape")

    recalled = run([str(cli), "-C", str(memory), "recall",
                    "which database did we choose?"], env=env)
    if "M0001" not in recalled or "mock note" not in recalled:
        raise SystemExit("FAIL: recall(mock) did not return the memory")
    listed = run([str(cli), "-C", str(memory), "list"], env=env)
    if "Use Postgres" not in listed:
        raise SystemExit("FAIL: memory did not survive the process restart")

    # Mock determinism: the same question must reproduce the same annotations.
    again = run([str(cli), "-C", str(memory), "recall",
                 "which database did we choose?"], env=env)
    def annotations(blob: str) -> object:
        import json as _json

        for line in blob.splitlines():
            if line.startswith("{"):
                return _json.loads(line).get("annotations")
        return None
    if annotations(recalled) != annotations(again):
        raise SystemExit("FAIL: mock recall is not reproducible")

    print("PASS: installed smoke (wheel -> venv -> init -> remember -> "
          "recall(mock) -> restart -> persistence)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
