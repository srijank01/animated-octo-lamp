#!/usr/bin/env bash
set -e

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Ensure Node.js v24 (LTS/compatible) is prioritized in PATH for Next.js
if [ -d "$HOME/.nvm/versions/node/v24.14.0/bin" ]; then
    export PATH="$HOME/.nvm/versions/node/v24.14.0/bin:$PATH"
fi
export NEXT_TELEMETRY_DISABLED=1
export BROWSERSLIST_IGNORE_OLD_DATA=1

echo "======================================================================"
echo "  Starting AutoClip AI Studio (FastAPI Backend + Next.js Dashboard)"
echo "======================================================================"

# Clean up child processes on Ctrl+C / EXIT
cleanup() {
    echo ""
    echo "Stopping AutoClip AI Studio servers..."
    kill $(jobs -p) 2>/dev/null || true
    wait 2>/dev/null || true
    echo "Done."
}
trap cleanup SIGINT SIGTERM EXIT

# Free ports 8000 and 3000 if occupied
lsof -ti:8000 | xargs kill -9 2>/dev/null || true
lsof -ti:3000 | xargs kill -9 2>/dev/null || true

# 1. Start FastAPI Backend
echo "[1/2] Starting FastAPI backend on http://localhost:8000..."
cd "$PROJECT_DIR"
backend/venv/bin/uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload --reload-dir backend --reload-exclude "backend/venv" --reload-exclude "backend/output" --reload-exclude "*venv*" --reload-exclude "*output*" &
BACKEND_PID=$!

# Wait for backend to be responsive
echo "Waiting for backend to initialize..."
for i in {1..30}; do
    if curl -s http://127.0.0.1:8000/api/health > /dev/null 2>&1; then
        echo "✓ Backend is ready!"
        break
    fi
    sleep 0.5
done

# 2. Start Next.js Frontend
echo "[2/2] Starting Next.js Studio frontend on http://localhost:3000..."
cd "$PROJECT_DIR/frontend"

echo "Building Next.js frontend..."
npm run build

npm run start &
FRONTEND_PID=$!

# Wait for frontend to be responsive
echo "Waiting for frontend to initialize..."
for i in {1..30}; do
    if curl -s http://127.0.0.1:3000 > /dev/null 2>&1; then
        echo "✓ Frontend is ready!"
        break
    fi
    sleep 0.5
done

echo ""
echo "======================================================================"
echo "  🚀 Studio UI:      http://localhost:3000"
echo "  ⚡ FastAPI Docs:   http://localhost:8000/docs"
echo "  📁 Media Mount:    http://localhost:8000/media/"
echo "======================================================================"
echo "Press Ctrl+C to stop both servers."
echo ""

wait
