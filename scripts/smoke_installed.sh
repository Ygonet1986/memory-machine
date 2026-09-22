#!/usr/bin/env bash
# L1 smoke test: prove the product works *installed* (no PYTHONPATH).
#
# Builds a wheel, installs it into a clean venv, then runs init/remember/
# recall(mock)/restart/persistence. Fails loudly on the first error.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/mm-smoke-XXXXXX")"
VENV="$WORK/venv"
MEM="$WORK/memory"
echo "smoke workdir: $WORK"

python3 -m venv "$VENV"
PY="$VENV/bin/python"
PIP="$VENV/bin/pip"

"$PIP" install --quiet --upgrade pip setuptools wheel
echo "== building wheel =="
"$PIP" wheel --quiet --no-deps -w "$WORK/wheel" "$ROOT"
WHEEL_FILE="$(ls "$WORK"/wheel/memory_machine-*.whl | head -1)"
echo "wheel: $WHEEL_FILE"

echo "== installing wheel into clean venv =="
"$PIP" install --quiet --no-deps "$WHEEL_FILE"

CLI="$VENV/bin/memory-cli"
test -x "$CLI" || { echo "FAIL: memory-cli entry point missing"; exit 1; }

echo "== memory-cli --help =="
"$CLI" --help >/dev/null

echo "== init (python -m memory_machine) =="
"$PY" -m memory_machine -C "$MEM" init >/dev/null
test -f "$MEM/manifest.json" && test -f "$MEM/whiteboard.json" \
  || { echo "FAIL: init did not create the project files"; exit 1; }

echo "== remember =="
export MEMORY_MACHINE_MOCK=1
unset DEEPSEEK_API_KEY || true
"$CLI" -C "$MEM" remember --type decision \
  --summary "Use Postgres for the primary datastore" --why "ACID + JSONB" >/dev/null
test -f "$MEM/tape.jsonl" || { echo "FAIL: remember did not create the tape"; exit 1; }

echo "== recall (offline mock) =="
OUT="$("$CLI" -C "$MEM" recall "which database did we choose?")"
echo "$OUT" | tail -3
echo "$OUT" | grep -q "M0001" || { echo "FAIL: recall did not return the memory"; exit 1; }
echo "$OUT" | grep -q "mock note" || { echo "FAIL: mock annotations missing"; exit 1; }

echo "== restart process, then verify persistence =="
"$CLI" -C "$MEM" list | grep -q "Use Postgres" \
  || { echo "FAIL: memory did not survive the process restart"; exit 1; }
"$CLI" -C "$MEM" whiteboard >/dev/null

echo "PASS: installed smoke test (wheel -> venv -> init -> remember -> recall(mock) -> restart -> persistence)"
