#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"
APP_URL="http://localhost:5173"

find_python() {
  for candidate in python3 python py; do
    if command -v "$candidate" >/dev/null 2>&1; then
      if "$candidate" -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" >/dev/null 2>&1; then
        echo "$candidate"
        return 0
      fi
    fi
  done
  return 1
}

require_node() {
  if ! command -v node >/dev/null 2>&1; then
    echo "Node.js 18+ is required. Install Node and run ./start.sh again." >&2
    exit 1
  fi
  node -e "const major=Number(process.versions.node.split('.')[0]); process.exit(major >= 18 ? 0 : 1)" || {
    echo "Node.js 18+ is required. Current version: $(node -v)" >&2
    exit 1
  }
}

open_browser() {
  if command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$APP_URL" >/dev/null 2>&1 || true
  elif command -v open >/dev/null 2>&1; then
    open "$APP_URL" >/dev/null 2>&1 || true
  elif command -v powershell.exe >/dev/null 2>&1; then
    powershell.exe -NoProfile -Command "Start-Process '$APP_URL'" >/dev/null 2>&1 || true
  fi
}

PYTHON_BIN="$(find_python || true)"
if [[ -z "$PYTHON_BIN" ]]; then
  echo "Python 3.10+ is required. Install Python and run ./start.sh again." >&2
  exit 1
fi
require_node

cd "$BACKEND_DIR"
if [[ ! -d .venv ]]; then
  "$PYTHON_BIN" -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

cd "$FRONTEND_DIR"
npm install

cd "$BACKEND_DIR"
if [[ ! -f .env ]]; then
  cp .env.example .env
  cat <<MSG
Created backend/.env.

Fill in GROQ_API_KEY, JWT_SECRET, and AWS credentials if you are not using an
existing AWS profile or IAM role, then run ./start.sh again.
MSG
  exit 0
fi

if grep -Eq '^GROQ_API_KEY=$' .env || grep -Eq '^JWT_SECRET=change-me' .env; then
  cat <<MSG
backend/.env still has placeholder values.

Set GROQ_API_KEY and replace JWT_SECRET with a long random string. Add AWS
credentials here or use the standard AWS credential chain (~/.aws/credentials,
environment variables, or an IAM role), then run ./start.sh again.
MSG
  exit 1
fi

cleanup() {
  [[ -n "${BACKEND_PID:-}" ]] && kill "$BACKEND_PID" 2>/dev/null || true
  [[ -n "${FRONTEND_PID:-}" ]] && kill "$FRONTEND_PID" 2>/dev/null || true
}
trap cleanup INT TERM EXIT

cd "$BACKEND_DIR"
source .venv/bin/activate
uvicorn main:app --reload --host 0.0.0.0 --port 8000 &
BACKEND_PID=$!

cd "$FRONTEND_DIR"
npm run dev -- --host 0.0.0.0 &
FRONTEND_PID=$!

sleep 2
open_browser
wait "$BACKEND_PID" "$FRONTEND_PID"