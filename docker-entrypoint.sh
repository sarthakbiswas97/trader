#!/bin/bash
set -e

echo "Starting Trading System..."

# Start backend (FastAPI)
cd /app
uvicorn backend.main:app --host 0.0.0.0 --port 8000

echo "Backend running on :8000"
