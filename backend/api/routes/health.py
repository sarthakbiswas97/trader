"""
Health Check Routes.
"""

from datetime import datetime
from pathlib import Path

from fastapi import APIRouter

from backend.api.dependencies import get_app_state
from backend.api.schemas import HealthResponse
from backend.broker.session import load_access_token

router = APIRouter()

MODEL_PATH = Path(__file__).parent.parent.parent / "ml" / "models" / "model_latest.joblib"


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """
    Health check endpoint.

    Returns status of all system components.
    """
    state = get_app_state()

    # Check components
    components = {
        "api": True,
        "broker_authenticated": state.is_authenticated,
        "bot_running": state.is_running,
        "model_available": MODEL_PATH.exists(),
        "session_valid": load_access_token() is not None,
    }

    # Overall status
    critical_components = ["api", "model_available"]
    all_critical_healthy = all(components.get(c, False) for c in critical_components)

    return HealthResponse(
        status="healthy" if all_critical_healthy else "degraded",
        timestamp=datetime.now(),
        version="1.0.0",
        components=components,
    )


@router.get("/health/live")
async def liveness():
    """Kubernetes liveness probe."""
    return {"status": "ok"}


@router.get("/health/ready")
async def readiness():
    """Kubernetes readiness probe."""
    state = get_app_state()

    if not MODEL_PATH.exists():
        return {"status": "not_ready", "reason": "model_not_found"}

    return {"status": "ready"}
