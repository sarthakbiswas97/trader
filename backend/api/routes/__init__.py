"""
API Routes Registration.
"""

from fastapi import APIRouter

from backend.api.routes.health import router as health_router
from backend.api.routes.auth import router as auth_router
from backend.api.routes.bot import router as bot_router
from backend.api.routes.portfolio import router as portfolio_router
from backend.api.routes.predictions import router as predictions_router

router = APIRouter()

# Register all route modules
router.include_router(health_router, tags=["Health"])
router.include_router(auth_router, prefix="/auth", tags=["Authentication"])
router.include_router(bot_router, prefix="/bot", tags=["Bot Control"])
router.include_router(portfolio_router, prefix="/portfolio", tags=["Portfolio"])
router.include_router(predictions_router, prefix="/predictions", tags=["Predictions"])
