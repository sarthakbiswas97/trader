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
        self._load_persisted_positions()
        logger.info("PositionManager initialized")

    def _load_persisted_positions(self):
        """Load open positions from DB (survive container restarts)."""
        try:
            from backend.db.database import get_session
            from backend.db.repository import OpenPositionRepository

            with get_session() as session:
                repo = OpenPositionRepository(session)
                saved = repo.get_all()
                for pos in saved:
                    # Create a minimal Prediction for the managed position
                    from backend.ml.inference import Prediction
                    pred = Prediction(
                        symbol=pos.symbol,
                        timestamp=pos.entry_time,
                        direction=pos.prediction_direction or "NEUTRAL",
                        probability=pos.prediction_confidence or 0.5,
                        confidence=pos.prediction_confidence or 0,
                        prob_up=0.5, prob_down=0.5, prob_neutral=0,
                        top_features=[],
                    )
                    self._managed_positions[pos.symbol] = ManagedPosition(
                        symbol=pos.symbol,
                        quantity=pos.quantity,
                        entry_price=pos.entry_price,
                        entry_time=pos.entry_time,
                        prediction=pred,
                        is_short=pos.is_short,
                        entry_reason=pos.entry_reason or "restored",
                        target_price=pos.target_price,
                        stop_loss_price=pos.stop_loss_price,
                        current_price=pos.entry_price,
                        peak_price=pos.entry_price,
                    )
                if saved:
                    logger.info(f"Restored {len(saved)} positions from DB")
        except Exception as e:
            logger.warning(f"Failed to load persisted positions: {e}")

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
        stop_loss_pct: float = 0.05,
        target_pct: float = 0.04,
        atr: float | None = None,
        sl_atr_mult: float = 2.0,
        tp_atr_mult: float = 1.5,
    ) -> ManagedPosition:
        """
        Record a new position with ATR-based dynamic SL/TP.

        Args:
            symbol: Trading symbol
            quantity: Number of shares
            entry_price: Entry price
            prediction: ML prediction that triggered entry
            is_short: True for short position
            entry_reason: Human-readable reason
            stop_loss_pct: Fallback stop loss as fraction (if ATR unavailable)
            target_pct: Fallback target profit as fraction
            atr: Average True Range value for dynamic SL/TP
            sl_atr_mult: Stop-loss ATR multiplier (SL = entry ± ATR × mult)
            tp_atr_mult: Take-profit ATR multiplier (TP = entry ± ATR × mult)
        """
        if atr and atr > 0:
            # Dynamic ATR-based SL/TP
            if is_short:
                stop_loss_price = entry_price + (atr * sl_atr_mult)
                target_price = entry_price - (atr * tp_atr_mult)
            else:
                stop_loss_price = entry_price - (atr * sl_atr_mult)
                target_price = entry_price + (atr * tp_atr_mult)
            logger.info(
                f"ATR-based SL/TP for {symbol}",
                atr=round(atr, 2),
                sl=round(stop_loss_price, 2),
                tp=round(target_price, 2),
            )
        else:
            # Fallback to fixed %
            if is_short:
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

        # Persist to DB for multi-day survival
        self._persist_position(position)

        return position

    def _persist_position(self, pos: ManagedPosition):
        """Fire-and-forget: save open position to DB."""
        try:
            from backend.db.database import get_session
            from backend.db.repository import OpenPositionRepository

            with get_session() as session:
                repo = OpenPositionRepository(session)
                repo.save_position(
                    symbol=pos.symbol,
                    quantity=pos.quantity,
                    entry_price=pos.entry_price,
                    is_short=pos.is_short,
                    entry_reason=pos.entry_reason,
                    stop_loss_price=pos.stop_loss_price,
                    target_price=pos.target_price,
                    prediction_direction=pos.prediction.direction,
                    prediction_confidence=pos.prediction.confidence,
                    entry_time=pos.entry_time,
                )
        except Exception as e:
            logger.warning(f"Failed to persist position {pos.symbol}: {e}")

    def _remove_persisted_position(self, symbol: str):
        """Fire-and-forget: remove closed position from DB."""
        try:
            from backend.db.database import get_session
            from backend.db.repository import OpenPositionRepository

            with get_session() as session:
                repo = OpenPositionRepository(session)
                repo.remove_position(symbol)
        except Exception as e:
            logger.warning(f"Failed to remove persisted position {symbol}: {e}")

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
        self._remove_persisted_position(symbol)

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
