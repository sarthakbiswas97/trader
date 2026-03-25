"""
Pydantic schemas for API request/response models.
"""

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# =============================================================================
# Enums
# =============================================================================


class BotStatus(str, Enum):
    """Bot operational status."""
    STOPPED = "stopped"
    RUNNING = "running"
    PAUSED = "paused"
    ERROR = "error"


class TradeSide(str, Enum):
    """Trade side."""
    BUY = "BUY"
    SELL = "SELL"


class TradeStatus(str, Enum):
    """Trade status."""
    OPEN = "open"
    CLOSED = "closed"


# =============================================================================
# Health
# =============================================================================


class HealthResponse(BaseModel):
    """Health check response."""
    status: str = "healthy"
    timestamp: datetime
    version: str = "1.0.0"
    components: dict[str, bool] = Field(default_factory=dict)


# =============================================================================
# Authentication
# =============================================================================


class AuthStatus(BaseModel):
    """Authentication status."""
    authenticated: bool
    user_id: str | None = None
    user_name: str | None = None
    session_valid: bool = False
    expires_at: str | None = None


class LoginUrlResponse(BaseModel):
    """Login URL for OAuth."""
    login_url: str
    callback_url: str


# =============================================================================
# Bot Control
# =============================================================================


class BotStatusResponse(BaseModel):
    """Bot status response."""
    status: BotStatus
    running_since: datetime | None = None
    cycle_count: int = 0
    last_cycle: datetime | None = None
    symbols_count: int = 0
    error_message: str | None = None


class BotStartRequest(BaseModel):
    """Request to start the bot."""
    symbols: list[str] | None = None
    paper_mode: bool = True
    capital: float = 100000.0


class BotStartResponse(BaseModel):
    """Response after starting bot."""
    success: bool
    message: str
    status: BotStatus


class BotStopResponse(BaseModel):
    """Response after stopping bot."""
    success: bool
    message: str
    positions_closed: int = 0


# =============================================================================
# Portfolio
# =============================================================================


class PositionSchema(BaseModel):
    """Single position."""
    symbol: str
    quantity: int
    avg_price: float
    current_price: float
    pnl: float
    pnl_percent: float
    entry_time: datetime | None = None
    entry_reason: str | None = None


class PortfolioSummary(BaseModel):
    """Portfolio summary."""
    total_capital: float
    available_cash: float
    invested_value: float
    current_value: float
    unrealized_pnl: float
    realized_pnl: float
    total_pnl: float
    total_pnl_percent: float
    open_positions: int


class PositionsResponse(BaseModel):
    """All positions response."""
    positions: list[PositionSchema]
    summary: PortfolioSummary


# =============================================================================
# Trades
# =============================================================================


class TradeSchema(BaseModel):
    """Single trade record."""
    id: str
    symbol: str
    side: TradeSide
    quantity: int
    entry_price: float
    exit_price: float | None = None
    entry_time: datetime
    exit_time: datetime | None = None
    pnl: float | None = None
    pnl_percent: float | None = None
    status: TradeStatus
    exit_reason: str | None = None


class TradesResponse(BaseModel):
    """Trades list response."""
    trades: list[TradeSchema]
    total_count: int
    winning_trades: int
    losing_trades: int
    win_rate: float


# =============================================================================
# Predictions
# =============================================================================


class PredictionSchema(BaseModel):
    """Single prediction."""
    symbol: str
    direction: str
    probability: float
    confidence: float
    should_trade: bool
    timestamp: datetime
    top_features: list[tuple[str, float]] = Field(default_factory=list)


class PredictionsResponse(BaseModel):
    """Predictions response."""
    predictions: list[PredictionSchema]
    generated_at: datetime
    symbols_analyzed: int
    up_signals: int
    down_signals: int


class PredictionRequest(BaseModel):
    """Request for predictions."""
    symbols: list[str] | None = None
    limit: int = Field(default=10, ge=1, le=50)


# =============================================================================
# Risk
# =============================================================================


class RiskStatus(BaseModel):
    """Risk management status."""
    circuit_breaker_triggered: bool
    circuit_breaker_reason: str | None = None
    trades_today: int
    max_trades: int
    daily_pnl: float
    daily_loss_limit: float
    current_exposure: float
    max_exposure: float
    risk_score: float


# =============================================================================
# Generic
# =============================================================================


class ErrorResponse(BaseModel):
    """Error response."""
    error: str
    detail: str | None = None
    timestamp: datetime = Field(default_factory=datetime.now)


class SuccessResponse(BaseModel):
    """Generic success response."""
    success: bool = True
    message: str
