"""
Abstract Broker interface.
All broker implementations (Groww, Paper, etc.) must implement this interface.
This enables easy swapping between brokers and testing.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class OrderSide(str, Enum):
    """Order side (direction)."""

    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    """Order type."""

    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP_LOSS = "SL"
    STOP_LOSS_MARKET = "SL_M"


class OrderStatus(str, Enum):
    """Order status."""

    PENDING = "PENDING"
    OPEN = "OPEN"
    EXECUTED = "EXECUTED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


class ProductType(str, Enum):
    """Product type for orders."""

    CNC = "CNC"  # Cash & Carry (delivery)
    MIS = "MIS"  # Margin Intraday Square-off
    NRML = "NRML"  # Normal (F&O)


@dataclass
class Order:
    """Order request data."""

    symbol: str
    quantity: int
    side: OrderSide
    order_type: OrderType = OrderType.MARKET
    product: ProductType = ProductType.MIS  # Default to intraday
    price: float | None = None  # Required for LIMIT orders
    trigger_price: float | None = None  # Required for SL orders
    reference_id: str | None = None  # Optional client reference


@dataclass
class OrderResponse:
    """Order execution response."""

    order_id: str
    status: OrderStatus
    symbol: str
    quantity: int
    side: OrderSide
    message: str = ""
    executed_price: float | None = None
    executed_quantity: int | None = None
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class Position:
    """Current position in a symbol."""

    symbol: str
    quantity: int
    avg_price: float
    current_price: float
    product: ProductType
    exchange: str = "NSE"

    @property
    def pnl(self) -> float:
        """Calculate absolute P&L."""
        return (self.current_price - self.avg_price) * self.quantity

    @property
    def pnl_percent(self) -> float:
        """Calculate P&L percentage."""
        if self.avg_price == 0:
            return 0.0
        return ((self.current_price - self.avg_price) / self.avg_price) * 100

    @property
    def market_value(self) -> float:
        """Calculate current market value."""
        return self.current_price * self.quantity

    @property
    def invested_value(self) -> float:
        """Calculate invested value."""
        return self.avg_price * self.quantity


@dataclass
class Holding:
    """Long-term holding (CNC positions)."""

    symbol: str
    quantity: int
    avg_price: float
    current_price: float
    isin: str = ""

    @property
    def pnl(self) -> float:
        return (self.current_price - self.avg_price) * self.quantity

    @property
    def pnl_percent(self) -> float:
        if self.avg_price == 0:
            return 0.0
        return ((self.current_price - self.avg_price) / self.avg_price) * 100


@dataclass
class MarginInfo:
    """Account margin information."""

    available_cash: float
    used_margin: float
    total_balance: float

    @property
    def available_margin(self) -> float:
        """Available margin for trading."""
        return self.available_cash


@dataclass
class Quote:
    """Real-time quote for a symbol."""

    symbol: str
    ltp: float  # Last traded price
    open: float
    high: float
    low: float
    close: float  # Previous close
    volume: int
    timestamp: datetime = field(default_factory=datetime.now)

    @property
    def change(self) -> float:
        """Price change from previous close."""
        return self.ltp - self.close

    @property
    def change_percent(self) -> float:
        """Percentage change from previous close."""
        if self.close == 0:
            return 0.0
        return ((self.ltp - self.close) / self.close) * 100


class Broker(ABC):
    """
    Abstract base class for all broker implementations.

    All methods that interact with the broker must be implemented.
    This allows swapping between real brokers (Groww) and paper trading.
    """

    @abstractmethod
    def authenticate(self) -> bool:
        """
        Authenticate with the broker.

        Returns:
            True if authentication successful, False otherwise.

        Raises:
            BrokerAuthenticationError: If authentication fails.
        """
        pass

    @abstractmethod
    def is_authenticated(self) -> bool:
        """Check if currently authenticated."""
        pass

    # =========================================================================
    # Order Management
    # =========================================================================

    @abstractmethod
    def place_order(self, order: Order) -> OrderResponse:
        """
        Place an order with the broker.

        Args:
            order: Order details.

        Returns:
            OrderResponse with execution details.

        Raises:
            OrderExecutionError: If order placement fails.
            InsufficientFundsError: If not enough funds.
        """
        pass

    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        """
        Cancel an open order.

        Args:
            order_id: The broker's order ID.

        Returns:
            True if cancellation successful.
        """
        pass

    @abstractmethod
    def get_order_status(self, order_id: str) -> OrderResponse:
        """
        Get the current status of an order.

        Args:
            order_id: The broker's order ID.

        Returns:
            OrderResponse with current status.
        """
        pass

    @abstractmethod
    def get_orders(self) -> list[OrderResponse]:
        """
        Get all orders for the day.

        Returns:
            List of all orders.
        """
        pass

    # =========================================================================
    # Portfolio
    # =========================================================================

    @abstractmethod
    def get_positions(self) -> list[Position]:
        """
        Get all open positions.

        Returns:
            List of current positions.
        """
        pass

    @abstractmethod
    def get_holdings(self) -> list[Holding]:
        """
        Get all holdings (delivery positions).

        Returns:
            List of holdings.
        """
        pass

    @abstractmethod
    def get_margin(self) -> MarginInfo:
        """
        Get account margin information.

        Returns:
            MarginInfo with available funds.
        """
        pass

    # =========================================================================
    # Market Data
    # =========================================================================

    @abstractmethod
    def get_ltp(self, symbols: list[str]) -> dict[str, float]:
        """
        Get last traded price for symbols.

        Args:
            symbols: List of trading symbols.

        Returns:
            Dict mapping symbol to LTP.
        """
        pass

    @abstractmethod
    def get_quote(self, symbol: str) -> Quote:
        """
        Get detailed quote for a symbol.

        Args:
            symbol: Trading symbol.

        Returns:
            Quote with OHLC and volume.
        """
        pass

    # =========================================================================
    # User Info
    # =========================================================================

    @abstractmethod
    def get_profile(self) -> dict[str, Any]:
        """
        Get user profile information.

        Returns:
            Dict with user details.
        """
        pass
