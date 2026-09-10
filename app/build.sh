#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."

PY=.venv/bin/python

echo "[1/4] installing deps"
$PY -m pip install --quiet --upgrade pip
$PY -m pip install --quiet pyside6 pyinstaller certifi

echo "[2/4] generating icon"
$PY -m app.make_icon >/dev/null 2>&1 || true

echo "[3/4] building .app (PyInstaller)"
$PY -m PyInstaller --noconfirm --clean --windowed \
  --name "Memory Machine" \
  --icon app/icons/MemoryMachine.icns \
  --osx-bundle-identifier com.memorymachine.app \
  --paths src \
  launcher.py

APP="dist/Memory Machine.app"

echo "[4/4] ad-hoc code signing"
codesign --force --deep --sign - "$APP"

echo
echo "built: $(cd "$(dirname "$APP")" && pwd)/$(basename "$APP")"
echo "install: drag 'Memory Machine.app' into /Applications"
echo "first launch: right-click -> Open (Gatekeeper, non-notarized)"
