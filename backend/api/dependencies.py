"""
FastAPI Dependencies.

Provides dependency injection for services, broker, and state management.
"""

from functools import lru_cache
from typing import Annotated

from fastapi import Depends, HTTPException, status

from backend.broker.base import Broker
from backend.broker.paper import PaperBroker
from backend.broker.session import load_access_token
from backend.config import settings
from backend.core.logger import get_logger
from backend.ml.inference import PredictionService
from backend.services.execution_engine import ExecutionEngine, create_engine
from backend.services.historical_data import HistoricalDataService

logger = get_logger(__name__)


# =============================================================================
# Application State
# =============================================================================


class AppState:
    """
    Application state singleton.
    Holds shared state across requests.
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._broker: Broker | None = None
        self._engine: ExecutionEngine | None = None
        self._prediction_service: PredictionService | None = None
        self._data_service: HistoricalDataService | None = None
        self._initialized = True

        logger.info("AppState initialized")

    @property
    def broker(self) -> Broker | None:
        return self._broker

    @broker.setter
    def broker(self, value: Broker):
        self._broker = value

    @property
    def engine(self) -> ExecutionEngine | None:
        return self._engine

    @engine.setter
    def engine(self, value: ExecutionEngine):
        self._engine = value

    @property
    def prediction_service(self) -> PredictionService | None:
        return self._prediction_service

    @prediction_service.setter
    def prediction_service(self, value: PredictionService):
        self._prediction_service = value

    @property
    def is_authenticated(self) -> bool:
        return self._broker is not None and self._broker.is_authenticated()

    @property
    def is_running(self) -> bool:
        return self._engine is not None and self._engine.running

    def reset(self):
        """Reset all state."""
        if self._engine and self._engine.running:
            self._engine.stop()
        self._broker = None
        self._engine = None
        logger.info("AppState reset")


@lru_cache
def get_app_state() -> AppState:
    """Get application state singleton."""
    return AppState()


# =============================================================================
# Dependencies
# =============================================================================


def get_broker(
    state: Annotated[AppState, Depends(get_app_state)]
) -> Broker:
    """
    Get authenticated broker.
    Raises 401 if not authenticated.
    """
    if not state.broker or not state.is_authenticated:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated. Call /auth/connect first.",
        )
    return state.broker


def get_engine(
    state: Annotated[AppState, Depends(get_app_state)]
) -> ExecutionEngine:
    """
    Get execution engine.
    Raises 400 if bot not started.
    """
    if not state.engine:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Bot not started. Call /bot/start first.",
        )
    return state.engine


def get_prediction_service(
    state: Annotated[AppState, Depends(get_app_state)]
) -> PredictionService:
    """Get prediction service, initializing if needed."""
    if not state.prediction_service:
        try:
            state.prediction_service = PredictionService()
        except FileNotFoundError:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="ML model not found. Run training first.",
            )
    return state.prediction_service


def require_authentication(
    state: Annotated[AppState, Depends(get_app_state)]
) -> AppState:
    """Require authentication for protected routes."""
    if not state.is_authenticated:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
        )
    return state


def require_running_bot(
    state: Annotated[AppState, Depends(get_app_state)]
) -> AppState:
    """Require bot to be running."""
    if not state.is_running:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Bot is not running.",
        )
    return state


# Type aliases for cleaner route signatures
BrokerDep = Annotated[Broker, Depends(get_broker)]
EngineDep = Annotated[ExecutionEngine, Depends(get_engine)]
PredictionServiceDep = Annotated[PredictionService, Depends(get_prediction_service)]
AppStateDep = Annotated[AppState, Depends(get_app_state)]
AuthRequiredDep = Annotated[AppState, Depends(require_authentication)]
