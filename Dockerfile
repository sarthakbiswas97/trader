FROM python:3.13-slim

WORKDIR /app

# Install system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl && rm -rf /var/lib/apt/lists/*

# Install Python deps
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

# Copy backend
COPY backend/ backend/
COPY .env.example .env.example
COPY Makefile Makefile

# Create non-root user
RUN useradd -m -s /bin/bash appuser

# Create data directories
RUN mkdir -p backend/data/historical backend/data/index backend/data/pseudo_trading backend/data/training \
    backend/data/multi_engine backend/ml/models \
    && chown -R appuser:appuser /app

# Expose port
EXPOSE 8000

# Start script
COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

# Run as non-root
USER appuser

CMD ["/docker-entrypoint.sh"]
