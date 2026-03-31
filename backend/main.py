"""
FastAPI Application Entry Point.

Run with:
    uvicorn backend.main:app --reload --port 8000
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.routes import router as api_router
from backend.config import settings
from backend.core.logger import get_logger

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events."""
    logger.info("Starting application...")
    yield
    logger.info("Shutting down application...")


def create_app() -> FastAPI:
    """Application factory."""
    app = FastAPI(
        title="Autonomous Trading Bot",
        description="ML-powered intraday trading system for Indian equity markets",
        version="1.0.0",
        docs_url="/docs" if settings.debug else None,
        redoc_url="/redoc" if settings.debug else None,
        lifespan=lifespan,
    )

    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Content-Type", "Authorization"],
    )

    # Include API routes
    app.include_router(api_router, prefix="/api/v1")

    return app


app = create_app()


@app.get("/", tags=["Root"])
async def root():
    """Root endpoint."""
    return {
        "name": "Autonomous Trading Bot",
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/api/v1/health",
    }
