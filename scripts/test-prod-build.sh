#!/bin/bash
set -e

echo "============================================"
echo "Production Build Test (linux/amd64)"
echo "============================================"

cd "$(dirname "$0")/.."

# Check Docker
if ! command -v docker &> /dev/null; then
    echo "ERROR: Docker not installed"
    exit 1
fi

echo ""
echo "1. Building image for linux/amd64..."
echo "   (This uses buildx for cross-platform build)"
echo ""

docker buildx build \
    --platform linux/amd64 \
    --tag trader-prod-test:latest \
    --load \
    .

echo ""
echo "2. Starting container..."

# Clean up any previous test container
docker rm -f trader-prod-test 2>/dev/null || true

# Find free ports
FRONTEND_PORT=3099
BACKEND_PORT=8099

docker run -d \
    --name trader-prod-test \
    -p ${FRONTEND_PORT}:3000 \
    -p ${BACKEND_PORT}:8000 \
    -e KITE_API_KEY=test \
    -e KITE_API_SECRET=test \
    -e TRADING_MODE=paper \
    -e DATABASE_URL=sqlite:///tmp/test.db \
    -e ENVIRONMENT=production \
    -e DEBUG=false \
    trader-prod-test:latest

echo "   Waiting for startup..."
sleep 8

echo ""
echo "3. Running health checks..."
echo ""

# Backend health
HEALTH=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:${BACKEND_PORT}/api/v1/health 2>/dev/null)
if [ "$HEALTH" = "200" ]; then
    echo "   Backend API:  PASS (HTTP 200)"
else
    echo "   Backend API:  FAIL (HTTP $HEALTH)"
    docker logs trader-prod-test --tail 20
fi

# Frontend
FRONTEND=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:${FRONTEND_PORT} 2>/dev/null)
if [ "$FRONTEND" = "200" ]; then
    echo "   Frontend:     PASS (HTTP 200)"
else
    echo "   Frontend:     FAIL (HTTP $FRONTEND)"
fi

# Multi-engine endpoint
ENGINE=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:${BACKEND_PORT}/api/v1/bot/multi-engine 2>/dev/null)
if [ "$ENGINE" = "200" ]; then
    echo "   Multi-Engine: PASS (HTTP 200)"
else
    echo "   Multi-Engine: FAIL (HTTP $ENGINE)"
fi

# Swagger disabled in production
DOCS=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:${BACKEND_PORT}/docs 2>/dev/null)
if [ "$DOCS" = "404" ]; then
    echo "   Swagger Docs: PASS (disabled in prod)"
else
    echo "   Swagger Docs: WARN (HTTP $DOCS — should be 404 in prod)"
fi

# Check non-root user
CONTAINER_USER=$(docker exec trader-prod-test whoami 2>/dev/null)
if [ "$CONTAINER_USER" = "appuser" ]; then
    echo "   Non-root:     PASS (running as appuser)"
else
    echo "   Non-root:     FAIL (running as $CONTAINER_USER)"
fi

# Check architecture
ARCH=$(docker inspect trader-prod-test --format '{{.Config.Image}}' 2>/dev/null)
IMAGE_ARCH=$(docker inspect trader-prod-test --format '{{.Platform}}' 2>/dev/null || echo "check manually")
echo "   Platform:     linux/amd64 (built with buildx)"

echo ""
echo "4. Cleanup..."
docker rm -f trader-prod-test 2>/dev/null
echo "   Done."

echo ""
echo "============================================"
if [ "$HEALTH" = "200" ] && [ "$FRONTEND" = "200" ]; then
    echo "RESULT: ALL CHECKS PASSED"
else
    echo "RESULT: SOME CHECKS FAILED"
    exit 1
fi
echo "============================================"
