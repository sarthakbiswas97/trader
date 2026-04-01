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
    # Create DB tables (idempotent)
    try:
        from backend.db.database import create_tables
        create_tables()
    except Exception as e:
        logger.warning(f"DB table creation skipped: {e}")

    # Auto-start bot if broker is authenticated
    try:
        import asyncio
        from backend.api.dependencies import get_app_state
        from backend.services.execution_engine import create_engine
        from backend.broker.session import load_access_token

        state = get_app_state()
        access_token = load_access_token()

        if access_token and state.broker and state.is_authenticated:
            engine = create_engine(broker=state.broker)
            engine.running = True
            state.engine = engine

            async def run_engine():
                try:
                    await engine.run()
                except Exception as e:
                    logger.error(f"Auto-started engine error: {e}")
                    engine.running = False

            asyncio.get_event_loop().create_task(run_engine())
            logger.info("Bot auto-started on server boot")
        else:
            logger.info("Bot not auto-started — broker not authenticated")
    except Exception as e:
        logger.warning(f"Bot auto-start skipped: {e}")

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
        allow_origins=settings.cors_allowed_origins,
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
