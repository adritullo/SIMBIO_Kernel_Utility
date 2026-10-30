#!/usr/bin/env bash
# ------------------------------------------------------------------
#  Builds SIMBIO Kernel Utility on macOS or Linux (run it on the OS you want to build for).
#    ./build_app.sh            macOS -> dist/SimbioKernelUtility.app      Linux -> dist/SimbioKernelUtility (single file)
#    ./build_app.sh onedir     Linux only: folder dist/SimbioKernelUtility/ (starts faster)
#  Also writes a ready-to-share archive in dist/ (zip on macOS, tar.gz on Linux).
#  Needs Python 3.10-3.14 (python3). A private .venv is created next to this file.
#  Linux: Qt needs a few system libraries at run time, e.g.  sudo apt install libxcb-cursor0 libegl1 libxkbcommon-x11-0
# ------------------------------------------------------------------
set -euo pipefail
cd "$(dirname "$0")"

MODE="${1:-onefile}"
PY="${PYTHON:-python3}"

# One private venv per OS/CPU: this folder may be shared (Syncthing, OneDrive...) with a Windows machine that builds with
# build_exe.bat into .venv-win. A broken venv (e.g. created elsewhere) is recreated.
VENV=".venv-$(uname -s | tr '[:upper:]' '[:lower:]')-$(uname -m)"
if [ -e "$VENV/bin/python" ] && ! "$VENV/bin/python" -c "import sys" >/dev/null 2>&1; then rm -rf "$VENV"; fi
[ -x "$VENV/bin/python" ] || "$PY" -m venv "$VENV"
# shellcheck disable=SC1091
source "$VENV/bin/activate"
python -m pip install --upgrade pip
pip install -r requirements-dev.txt

echo "Running tests..."
QT_QPA_PLATFORM=offscreen python -m pytest -q tests || echo "WARNING: some tests failed - continuing with the build anyway"

export SKU_MODE="$MODE"
pyinstaller --noconfirm --clean SimbioKernelUtility.spec

echo "Smoke-testing the built app..."
python scripts/smoke_test.py

VERSION="$(python -c 'import simbio_utility; print(simbio_utility.__version__)')"
ARCH="$(uname -m)"
cd dist
case "$(uname -s)" in
  Darwin)
    OUT="SimbioKernelUtility-${VERSION}-macos-${ARCH}.zip"
    rm -f "$OUT"
    ditto -c -k --keepParent SimbioKernelUtility.app "$OUT"   # keeps the bundle's symlinks/permissions intact
    ;;
  *)
    OUT="SimbioKernelUtility-${VERSION}-linux-${ARCH}.tar.gz"
    rm -f "$OUT"
    tar -czf "$OUT" SimbioKernelUtility
    ;;
esac
echo
echo "Done.  dist/$OUT"
