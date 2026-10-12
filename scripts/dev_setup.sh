#!/usr/bin/env bash
# Reproducible development setup for Swarmbly App (macOS / Linux).
# Usage: bash scripts/dev_setup.sh   (PYTHON=python3.12 bash scripts/dev_setup.sh)
set -euo pipefail
cd "$(dirname "$0")/.."

PY="${PYTHON:-python3.11}"
if ! command -v "$PY" >/dev/null 2>&1; then
  echo "error: interpreter '$PY' not found (Python >= 3.10 required)" >&2
  exit 1
fi

echo "[1/4] creating virtualenv .venv"
"$PY" -m venv .venv

echo "[2/4] installing Swarmbly App (editable) + dependencies (PyPI + pinned GitHub)"
.venv/bin/pip install --quiet --upgrade pip
.venv/bin/pip install -e ".[dev]"

# macOS sharp edge: if the .venv tree carries the UF_HIDDEN flag (Finder,
# sync tools or housekeeping scripts can set it), Python 3.11's site.py
# SILENTLY skips the editable .pth files and `swarmbly-app` then fails with
#   ModuleNotFoundError: No module named 'swarmbly_app'
# even though `python -c "import swarmbly_app"` works from the repo root
# (the working directory shadows the broken path). Clear the flag here.
echo "[3/4] clearing macOS hidden flags on .venv (Python skips hidden .pth files)"
if [[ "$(uname -s)" == "Darwin" ]]; then
  chflags -R nohidden .venv 2>/dev/null || true
fi

echo "[4/4] verifying the installed entry point"
.venv/bin/python -c \
  "import swarmbly_app, swarmbly_v0, swarmbly_lce; print('OK — swarmbly_app', swarmbly_app.__version__)"

echo
echo "Setup complete. Next:"
echo "  source .venv/bin/activate"
echo "  swarmbly-app            # serves the UI on http://127.0.0.1:8765"
