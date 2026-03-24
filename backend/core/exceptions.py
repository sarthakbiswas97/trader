"""
Custom exceptions for the trading application.
Provides clear error handling across all modules.
"""

from typing import Any


class TradingBaseException(Exception):
    """Base exception for all trading-related errors."""

    def __init__(self, message: str, details: dict[str, Any] | None = None):
        self.message = message
        self.details = details or {}
        super().__init__(self.message)

    def __str__(self) -> str:
        if self.details:
            return f"{self.message} | Details: {self.details}"
        return self.message


# =============================================================================
# Broker Exceptions
# =============================================================================


class BrokerException(TradingBaseException):
    """Base exception for broker-related errors."""

    pass


class BrokerAuthenticationError(BrokerException):
    """Raised when broker authentication fails."""

    pass


class BrokerConnectionError(BrokerException):
    """Raised when connection to broker fails."""

    pass


class OrderExecutionError(BrokerException):
    """Raised when order execution fails."""

    def __init__(
        self,
        message: str,
        symbol: str | None = None,
        order_id: str | None = None,
        details: dict[str, Any] | None = None,
    ):
        self.symbol = symbol
        self.order_id = order_id
        super().__init__(message, details)


class OrderRejectedError(OrderExecutionError):
    """Raised when order is rejected by broker."""

    pass


class InsufficientFundsError(OrderExecutionError):
    """Raised when there are insufficient funds for order."""

    pass


# =============================================================================
# Risk Management Exceptions
# =============================================================================


class RiskException(TradingBaseException):
    """Base exception for risk-related errors."""

    pass


class RiskLimitExceededError(RiskException):
    """Raised when a risk limit is exceeded."""

    def __init__(
        self,
        message: str,
        limit_type: str,
        current_value: float,
        limit_value: float,
        details: dict[str, Any] | None = None,
    ):
        self.limit_type = limit_type
        self.current_value = current_value
        self.limit_value = limit_value
        details = details or {}
        details.update({
            "limit_type": limit_type,
            "current_value": current_value,
            "limit_value": limit_value,
        })
        super().__init__(message, details)


class CircuitBreakerTriggeredError(RiskException):
    """Raised when circuit breaker is triggered."""

    pass


class TradingHaltedError(RiskException):
    """Raised when trading is halted (e.g., max daily loss reached)."""

    pass


# =============================================================================
# Data Exceptions
# =============================================================================


class DataException(TradingBaseException):
    """Base exception for data-related errors."""

    pass


class DataFetchError(DataException):
    """Raised when fetching data fails."""

    pass


class InsufficientDataError(DataException):
    """Raised when there's insufficient data for calculations."""

    pass


class InvalidDataError(DataException):
    """Raised when data is invalid or corrupted."""

    pass


# =============================================================================
# Model Exceptions
# =============================================================================


class ModelException(TradingBaseException):
    """Base exception for ML model errors."""

    pass


class ModelNotFoundError(ModelException):
    """Raised when model file is not found."""

    pass


class PredictionError(ModelException):
    """Raised when prediction fails."""

    pass


class FeatureComputationError(ModelException):
    """Raised when feature computation fails."""

    pass


# =============================================================================
# Market Exceptions
# =============================================================================


class MarketException(TradingBaseException):
    """Base exception for market-related errors."""

    pass


class MarketClosedError(MarketException):
    """Raised when trying to trade outside market hours."""

    pass


class SymbolNotFoundError(MarketException):
    """Raised when trading symbol is not found."""

    pass
