#!/usr/bin/env bash
# LiaraPilot - one-command local launcher (Linux / macOS)
# Usage: bash scripts/run.sh [--skip-tests] [--host 0.0.0.0] [--port 8000]
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

SKIP_TESTS=0
HOST_OVERRIDE=""
PORT_OVERRIDE=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-tests) SKIP_TESTS=1; shift ;;
    --host) HOST_OVERRIDE="$2"; shift 2 ;;
    --port) PORT_OVERRIDE="$2"; shift 2 ;;
    *) echo "[LiaraPilot] unknown option: $1" >&2; exit 2 ;;
  esac
done

step() { printf '\033[36m[LiaraPilot] %s\033[0m\n' "$1"; }
fail() { printf '\033[31m[LiaraPilot] %s\033[0m\n' "$1" >&2; exit 1; }

step "Checking Python..."
PYTHON=""
for candidate in python3.12 python3.13 python3.11 python3 python; do
  if command -v "$candidate" >/dev/null 2>&1; then
    if "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
      PYTHON="$candidate"; break
    fi
  fi
done
[[ -n "$PYTHON" ]] || fail "Python 3.11+ not found. Install Python 3.12 first."
step "Using $PYTHON ($($PYTHON --version 2>&1))"

if [[ ! -f .env ]]; then
  [[ -f .env.example ]] || fail ".env.example not found - run from the repository root."
  step "Creating .env from .env.example..."
  "$PYTHON" scripts/setup_env.py
else
  step ".env found."
  "$PYTHON" scripts/setup_env.py >/dev/null
fi

step "Preparing data directories..."
mkdir -p data data/workspaces data/artifacts

if [[ ! -x .venv/bin/python ]]; then
  step "Creating virtual environment (.venv)..."
  "$PYTHON" -m venv .venv
fi
VENV_PY=".venv/bin/python"

if command -v uv >/dev/null 2>&1; then
  step "Syncing dependencies with uv..."
  uv sync --extra dev || { step "uv sync failed, falling back to pip"; "$VENV_PY" -m pip install -q -e ".[dev]"; }
else
  step "uv not found - using pip (install uv for faster setup)."
  "$VENV_PY" -m pip install -q --upgrade pip
  "$VENV_PY" -m pip install -q -e ".[dev]"
fi

step "Validating configuration..."
"$VENV_PY" scripts/validate_config.py || fail "Configuration is invalid (see above)."

if [[ "$SKIP_TESTS" -eq 0 ]]; then
  step "Running the offline test suite..."
  "$VENV_PY" -m pytest -q || fail "Tests failed. Fix them or rerun with --skip-tests."
fi

[[ -n "$HOST_OVERRIDE" ]] && export APP_HOST="$HOST_OVERRIDE"
[[ -n "$PORT_OVERRIDE" ]] && export APP_PORT="$PORT_OVERRIDE"

step "Starting LiaraPilot..."
echo
echo "  UI:       http://${APP_HOST:-127.0.0.1}:${APP_PORT:-8000}/"
echo "  API docs: http://${APP_HOST:-127.0.0.1}:${APP_PORT:-8000}/docs"
echo "  MCP:      $VENV_PY -m app.mcp.server"
echo "  Stop with Ctrl+C"
echo

exec "$VENV_PY" -m uvicorn app.main:app --host "${APP_HOST:-127.0.0.1}" --port "${APP_PORT:-8000}"
