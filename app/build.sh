#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."

PY=.venv/bin/python

echo "[1/5] installing deps"
$PY -m pip install --quiet --upgrade pip
$PY -m pip install --quiet pyside6 pyinstaller certifi

echo "[2/5] generating icon"
$PY -m app.make_icon >/dev/null 2>&1 || true

echo "[3/5] building .app (PyInstaller)"
$PY -m PyInstaller --noconfirm --clean --windowed \
  --name "Memory Machine" \
  --icon app/icons/MemoryMachine.icns \
  --osx-bundle-identifier com.memorymachine.app \
  --paths src \
  --add-data "personas:personas" \
  --hidden-import app.companion_backend \
  --hidden-import app.ui.companion_window \
  launcher.py

APP="dist/Memory Machine.app"

echo "[4/5] stamping package version into Info.plist"
VERSION="$($PY -c 'import sys; sys.path.insert(0, "src"); import memory_machine; print(memory_machine.__version__)')"
PLIST="$APP/Contents/Info.plist"
for KEY in CFBundleShortVersionString CFBundleVersion; do
  if /usr/libexec/PlistBuddy -c "Set :$KEY $VERSION" "$PLIST" 2>/dev/null; then
    :
  else
    /usr/libexec/PlistBuddy -c "Add :$KEY string $VERSION" "$PLIST"
  fi
done
echo "version: $VERSION"

echo "[5/5] ad-hoc code signing"
codesign --force --deep --sign - "$APP"

echo
echo "built: $(cd "$(dirname "$APP")" && pwd)/$(basename "$APP")"
echo "install: drag 'Memory Machine.app' into /Applications"
echo "first launch: right-click -> Open (Gatekeeper, non-notarized)"
