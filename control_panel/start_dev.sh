#!/bin/bash
#
# Development script for Graph-Code RAG Control Panel
# Backend (FastAPI) on :8008, Frontend (Vite React) on :3003
#
# The backend runs inside the project's uv environment (fastapi + uvicorn are
# declared in the root pyproject.toml). Start Memgraph first:
#   docker-compose up -d

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
FRONTEND_PORT=${FRONTEND_PORT:-3003}
BACKEND_PORT=${BACKEND_PORT:-8008}

echo "Starting Graph-Code Control Panel"
echo "  Frontend : http://localhost:$FRONTEND_PORT"
echo "  Backend  : http://localhost:$BACKEND_PORT/docs"

cleanup() {
  echo ""
  echo "Stopping dev servers..."
  kill $BACKEND_PID $FRONTEND_PID 2>/dev/null || true
}
trap cleanup EXIT INT TERM

# Backend (runs with the project's uv environment)
(
  cd "$SCRIPT_DIR/backend"
  exec uv run --project "$PROJECT_ROOT" uvicorn main:app --host 0.0.0.0 --port $BACKEND_PORT --reload
) &
BACKEND_PID=$!

# Frontend
(
  cd "$SCRIPT_DIR/frontend"
  if [ ! -d node_modules ]; then
    echo "Installing frontend deps..."
    npm install
  fi
  exec npm run dev -- --port $FRONTEND_PORT
) &
FRONTEND_PID=$!

wait
