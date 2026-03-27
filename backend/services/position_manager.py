"""
Position Manager - Track open positions with entry reasons and signals.
Provides position-level analytics and exit management.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from backend.broker.base import Broker, Position, OrderSide
from backend.core.logger import get_logger
from backend.ml.inference import Prediction
from backend.utils.time_utils import now_ist

logger = get_logger(__name__)


@dataclass
class ManagedPosition:
    """Position with trading metadata."""
    symbol: str
    quantity: int
    entry_price: float
    entry_time: datetime
    prediction: Prediction
    entry_reason: str
    is_short: bool = False
    target_price: float | None = None
    stop_loss_price: float | None = None
    current_price: float = 0.0
    peak_price: float = 0.0

    @property
    def pnl(self) -> float:
        if self.is_short:
            # Short: profit when price goes DOWN
            return (self.entry_price - self.current_price) * self.quantity
        return (self.current_price - self.entry_price) * self.quantity

    @property
    def pnl_percent(self) -> float:
        if self.entry_price == 0:
            return 0.0
        if self.is_short:
            return ((self.entry_price - self.current_price) / self.entry_price) * 100
        return ((self.current_price - self.entry_price) / self.entry_price) * 100

    @property
    def holding_time_seconds(self) -> float:
        return (now_ist() - self.entry_time).total_seconds()

    @property
    def holding_time_minutes(self) -> float:
        return self.holding_time_seconds / 60

    @property
    def side(self) -> str:
        return "SHORT" if self.is_short else "LONG"

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "quantity": self.quantity,
            "side": self.side,
            "is_short": self.is_short,
            "entry_price": self.entry_price,
            "entry_time": self.entry_time.isoformat(),
            "current_price": self.current_price,
            "pnl": self.pnl,
            "pnl_percent": self.pnl_percent,
            "holding_minutes": self.holding_time_minutes,
            "prediction_direction": self.prediction.direction,
            "prediction_confidence": self.prediction.confidence,
            "entry_reason": self.entry_reason,
            "target_price": self.target_price,
            "stop_loss_price": self.stop_loss_price,
        }


class PositionManager:
    """
    Track open positions with trading context.
    Syncs with broker positions and maintains trading metadata.
    """

    def __init__(self, broker: Broker):
        self.broker = broker
        self._managed_positions: dict[str, ManagedPosition] = {}
        logger.info("PositionManager initialized")

    def sync_with_broker(self) -> None:
        """
        Sync managed positions with broker's actual positions.
        Removes positions that no longer exist at broker.
        """
        broker_positions = {p.symbol: p for p in self.broker.get_positions()}

        # Remove positions that are no longer at broker
        to_remove = []
        for symbol in self._managed_positions:
            if symbol not in broker_positions:
                to_remove.append(symbol)

        for symbol in to_remove:
            logger.info(f"Position closed externally: {symbol}")
            del self._managed_positions[symbol]

        # Update current prices for existing positions
        for symbol, broker_pos in broker_positions.items():
            if symbol in self._managed_positions:
                managed = self._managed_positions[symbol]
                managed.current_price = broker_pos.current_price
                managed.peak_price = max(managed.peak_price, broker_pos.current_price)

    def has_position(self, symbol: str) -> bool:
        """Check if we have a position in a symbol."""
        self.sync_with_broker()
        return symbol in self._managed_positions

    def get_position(self, symbol: str) -> ManagedPosition | None:
        """Get managed position for a symbol."""
        self.sync_with_broker()
        return self._managed_positions.get(symbol)

    def get_all_positions(self) -> list[ManagedPosition]:
        """Get all managed positions."""
        self.sync_with_broker()
        return list(self._managed_positions.values())

    def open_position(
        self,
        symbol: str,
        quantity: int,
        entry_price: float,
        prediction: Prediction,
        is_short: bool = False,
        entry_reason: str = "ML signal",
        stop_loss_pct: float = 0.02,
        target_pct: float = 0.02,
    ) -> ManagedPosition:
        """
        Record a new position.

        Args:
            symbol: Trading symbol
            quantity: Number of shares
            entry_price: Entry price
            prediction: ML prediction that triggered entry
            is_short: True for short position
            entry_reason: Human-readable reason
            stop_loss_pct: Stop loss as fraction
            target_pct: Target profit as fraction
        """
        if is_short:
            # Short: stop-loss is ABOVE entry, target is BELOW
            stop_loss_price = entry_price * (1 + stop_loss_pct)
            target_price = entry_price * (1 - target_pct)
        else:
            stop_loss_price = entry_price * (1 - stop_loss_pct)
            target_price = entry_price * (1 + target_pct)

        side = "SHORT" if is_short else "LONG"

        position = ManagedPosition(
            symbol=symbol,
            quantity=quantity,
            entry_price=entry_price,
            entry_time=now_ist(),
            prediction=prediction,
            is_short=is_short,
            entry_reason=entry_reason,
            target_price=target_price,
            stop_loss_price=stop_loss_price,
            current_price=entry_price,
            peak_price=entry_price,
        )

        self._managed_positions[symbol] = position

        logger.info(
            "Position opened",
            symbol=symbol,
            side=side,
            quantity=quantity,
            entry_price=entry_price,
            stop_loss=stop_loss_price,
            target=target_price,
        )

        return position

    def close_position(self, symbol: str, exit_price: float, exit_reason: str) -> dict[str, Any] | None:
        """
        Close a position and return trade summary.

        Args:
            symbol: Trading symbol
            exit_price: Exit price
            exit_reason: Reason for exit

        Returns:
            Trade summary dict or None if position not found
        """
        if symbol not in self._managed_positions:
            logger.warning(f"No managed position found for {symbol}")
            return None

        position = self._managed_positions[symbol]

        pnl = (exit_price - position.entry_price) * position.quantity
        pnl_percent = ((exit_price - position.entry_price) / position.entry_price) * 100
        holding_time = position.holding_time_minutes

        trade_summary = {
            "symbol": symbol,
            "quantity": position.quantity,
            "entry_price": position.entry_price,
            "exit_price": exit_price,
            "entry_time": position.entry_time.isoformat(),
            "exit_time": now_ist().isoformat(),
            "pnl": pnl,
            "pnl_percent": pnl_percent,
            "holding_minutes": holding_time,
            "exit_reason": exit_reason,
            "prediction_direction": position.prediction.direction,
            "prediction_confidence": position.prediction.confidence,
            "prediction_correct": (
                (pnl > 0 and position.prediction.direction == "UP") or
                (pnl < 0 and position.prediction.direction == "DOWN")
            ),
        }

        del self._managed_positions[symbol]

        logger.info(
            "Position closed",
            symbol=symbol,
            pnl=pnl,
            pnl_percent=pnl_percent,
            holding_minutes=holding_time,
            exit_reason=exit_reason,
        )

        return trade_summary

    def get_positions_for_exit_check(self) -> list[ManagedPosition]:
        """Get positions that need exit condition checking."""
        self.sync_with_broker()
        return list(self._managed_positions.values())

    def get_total_invested(self) -> float:
        """Get total invested value across all positions."""
        self.sync_with_broker()
        return sum(p.entry_price * p.quantity for p in self._managed_positions.values())

    def get_total_current_value(self) -> float:
        """Get total current value across all positions."""
        self.sync_with_broker()
        return sum(p.current_price * p.quantity for p in self._managed_positions.values())

    def get_unrealized_pnl(self) -> float:
        """Get total unrealized P&L."""
        self.sync_with_broker()
        return sum(p.pnl for p in self._managed_positions.values())

    def get_summary(self) -> dict[str, Any]:
        """Get portfolio summary."""
        self.sync_with_broker()
        positions = list(self._managed_positions.values())

        return {
            "open_positions": len(positions),
            "total_invested": self.get_total_invested(),
            "total_current_value": self.get_total_current_value(),
            "unrealized_pnl": self.get_unrealized_pnl(),
            "positions": [p.to_dict() for p in positions],
        }
