#!/usr/bin/env bash
# Launch the orchestration harness dashboard (backend + frontend) as detached,
# persistent processes that survive shell/session exit.
#
#   Backend  (FastAPI/uvicorn): http://0.0.0.0:5174   -> API /api/* + /ws
#   Frontend (Vite dev server) : http://0.0.0.0:5175   -> proxies /api + /ws to :5174
#
# Frontend runs on 5175 (NOT 5173) to avoid conflicting with Ganglion on 5173.
#
# Usage:   ./start-dashboard.sh
# Logs:    .logs/backend.log  .logs/frontend.log
# Stop:    lsof -nP -iTCP:5174 -sTCP:LISTEN | awk 'NR>1{print $2}' | xargs kill
#          lsof -nP -iTCP:5175 -sTCP:LISTEN | awk 'NR>1{print $2}' | xargs kill

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
mkdir -p .logs

# --- Backend: FastAPI dashboard server on 5174 ---
if lsof -nP -iTCP:5174 -sTCP:LISTEN >/dev/null 2>&1; then
  echo "Backend already listening on 5174 — skipping."
else
  echo "Starting backend on 0.0.0.0:5174 ..."
  nohup .venv/bin/python -m harness.cli --dashboard --host 0.0.0.0 --port 5174 \
    > .logs/backend.log 2>&1 < /dev/null &
  disown 2>/dev/null || true
  echo "  backend pid=$!"
fi

# --- Frontend: Vite dev server on 5175 (avoids Ganglion on 5173) ---
if lsof -nP -iTCP:5175 -sTCP:LISTEN >/dev/null 2>&1; then
  echo "Frontend already listening on 5175 — skipping."
else
  echo "Starting frontend on 0.0.0.0:5175 ..."
  (cd dashboard && nohup npm run dev -- --host 0.0.0.0 --port 5175 \
    > "$ROOT/.logs/frontend.log" 2>&1 < /dev/null &)
  disown 2>/dev/null || true
  echo "  frontend launched"
fi

echo "Done. Give Vite a few seconds to bind."
