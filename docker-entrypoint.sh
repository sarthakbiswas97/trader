#!/bin/bash
set -e

echo "Starting Trading System..."

# Start backend (FastAPI)
cd /app
uvicorn backend.main:app --host 0.0.0.0 --port 8000 &
BACKEND_PID=$!

# Start frontend (Next.js)
cd /app/frontend
npx next start --port 3000 --hostname 0.0.0.0 &
FRONTEND_PID=$!

echo "Backend running on :8000"
echo "Frontend running on :3000"

# Wait for either to exit
wait $BACKEND_PID $FRONTEND_PID
