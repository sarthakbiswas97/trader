# Multi-stage build: frontend + backend in one container
# Stage 1: Build frontend
FROM node:20-slim AS frontend-builder

WORKDIR /app/frontend
COPY frontend/package.json frontend/bun.lock ./
RUN npm install
COPY frontend/ ./
RUN npm run build

# Stage 2: Python backend + built frontend
FROM python:3.13-slim

WORKDIR /app

# Install system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl && rm -rf /var/lib/apt/lists/*

# Install Node.js for serving Next.js
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y nodejs && rm -rf /var/lib/apt/lists/*

# Install Python deps
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

# Copy backend
COPY backend/ backend/
COPY .env.example .env.example
COPY Makefile Makefile

# Copy built frontend
COPY --from=frontend-builder /app/frontend/.next frontend/.next
COPY --from=frontend-builder /app/frontend/node_modules frontend/node_modules
COPY --from=frontend-builder /app/frontend/package.json frontend/package.json
COPY --from=frontend-builder /app/frontend/public frontend/public

# Create data directories
RUN mkdir -p backend/data/historical backend/data/index backend/data/pseudo_trading backend/data/training

# Expose ports
EXPOSE 8000 3000

# Start script
COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

CMD ["/docker-entrypoint.sh"]
