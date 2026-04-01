"""
Trade Executor - Execute trading decisions based on ML signals.
Handles order placement, position sizing, and trade recording.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from backend.broker.base import (
    Broker,
    Order,
    OrderResponse,
    OrderSide,
    OrderStatus,
    OrderType,
    ProductType,
)
from backend.core.exceptions import OrderExecutionError
from backend.core.logger import get_logger
from backend.ml.inference import Prediction
from backend.services.position_manager import PositionManager
from backend.services.risk_guardian import RiskGuardian
from backend.services.stock_ranker import RankedStock
from backend.utils.time_utils import now_ist

logger = get_logger(__name__)


@dataclass
class TradeResult:
    """Result of a trade execution attempt."""
    success: bool
    symbol: str
    side: str
    quantity: int
    price: float
    order_id: str
    message: str
    timestamp: datetime

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "symbol": self.symbol,
            "side": self.side,
            "quantity": self.quantity,
            "price": self.price,
            "order_id": self.order_id,
            "message": self.message,
            "timestamp": self.timestamp.isoformat(),
        }


def _persist_trade(result: "TradeResult"):
    """Fire-and-forget DB persistence for a trade result."""
    try:
        from backend.db.database import get_session
        from backend.db.repository import IntraTradeRepository

        with get_session() as session:
            repo = IntraTradeRepository(session)
            repo.insert_trade(
                trade_id=result.order_id or f"T_{id(result)}",
                order_id=result.order_id,
                symbol=result.symbol,
                side=result.side,
                quantity=result.quantity,
                price=result.price,
                success=result.success,
                message=result.message[:200] if result.message else None,
                session_date=result.timestamp.date(),
                timestamp=result.timestamp,
            )
    except Exception as e:
        logger.warning(f"Failed to persist trade to DB: {e}")


class TradeExecutor:
    """
    Execute trading decisions based on ML signals.
    Coordinates with RiskGuardian, PositionManager, and Broker.
    """

    def __init__(
        self,
        broker: Broker,
        risk_guardian: RiskGuardian,
        position_manager: PositionManager,
        min_order_value: float = 1000.0,  # Minimum order value in INR
    ):
        self.broker = broker
        self.risk = risk_guardian
        self.positions = position_manager
        self.min_order_value = min_order_value

        self._trade_history: list[TradeResult] = []

        logger.info(
            "TradeExecutor initialized",
            min_order_value=min_order_value,
        )

    def execute_entries(
        self,
        ranked_stocks: list[RankedStock],
        available_capital: float,
    ) -> list[TradeResult]:
        """
        Execute entry orders for ranked stocks (both long and short).

        Args:
            ranked_stocks: Stocks ranked by signal quality
            available_capital: Capital available for trading

        Returns:
            List of TradeResult for each attempted trade
        """
        results = []

        for stock in ranked_stocks:
            # Skip if already holding
            if self.positions.has_position(stock.symbol):
                logger.debug(f"Already holding {stock.symbol}, skipping")
                continue

            # Determine direction
            is_short = stock.prediction.is_short_signal
            is_long = stock.prediction.is_long_signal

            if not is_short and not is_long:
                continue  # NEUTRAL — skip

            # Validate with risk guardian
            risk_check = self.risk.validate_entry(
                symbol=stock.symbol,
                prediction=stock.prediction,
                capital=available_capital,
                is_short=is_short,
            )

            if not risk_check.passed:
                logger.info(
                    f"Risk check failed for {stock.symbol}",
                    reason=risk_check.reason,
                )
                results.append(TradeResult(
                    success=False,
                    symbol=stock.symbol,
                    side="SHORT" if is_short else "BUY",
                    quantity=0,
                    price=0,
                    order_id="",
                    message=f"Risk check failed: {risk_check.reason}",
                    timestamp=now_ist(),
                ))
                continue

            # Calculate position size
            quantity, price = self._calculate_position_size(
                stock.symbol,
                risk_check.max_allocation,
            )

            if quantity == 0:
                logger.info(f"Position size too small for {stock.symbol}")
                continue

            # Execute order
            if is_short:
                result = self._execute_short_entry(
                    symbol=stock.symbol,
                    quantity=quantity,
                    prediction=stock.prediction,
                    entry_reason=f"SHORT signal (score: {stock.score:.1f})",
                )
            else:
                result = self._execute_buy(
                    symbol=stock.symbol,
                    quantity=quantity,
                    prediction=stock.prediction,
                    entry_reason=f"LONG signal (score: {stock.score:.1f})",
                )

            results.append(result)

            if result.success:
                available_capital -= result.price * result.quantity
                self.risk.record_trade()

        return results

    def _calculate_position_size(
        self,
        symbol: str,
        max_allocation: float,
    ) -> tuple[int, float]:
        """
        Calculate position size (shares) based on allocation and price.

        Args:
            symbol: Trading symbol
            max_allocation: Maximum capital to allocate

        Returns:
            Tuple of (quantity, current_price)
        """
        # Get current price
        ltp = self.broker.get_ltp([symbol])
        price = ltp.get(symbol, 0)

        if price <= 0:
            logger.warning(f"Could not get price for {symbol}")
            return 0, 0

        # Calculate max quantity
        max_quantity = int(max_allocation / price)

        # Check minimum order value
        if max_quantity * price < self.min_order_value:
            logger.debug(
                f"Order value too low for {symbol}",
                value=max_quantity * price,
                min_value=self.min_order_value,
            )
            return 0, price

        return max_quantity, price

    def _execute_buy(
        self,
        symbol: str,
        quantity: int,
        prediction: Prediction,
        entry_reason: str,
    ) -> TradeResult:
        """Execute a buy order."""
        order = Order(
            symbol=symbol,
            quantity=quantity,
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            product=ProductType.MIS,  # Intraday
        )

        try:
            response = self.broker.place_order(order)

            if response.status == OrderStatus.EXECUTED:
                # Record in position manager
                self.positions.open_position(
                    symbol=symbol,
                    quantity=quantity,
                    entry_price=response.executed_price or 0,
                    prediction=prediction,
                    entry_reason=entry_reason,
                )

                result = TradeResult(
                    success=True,
                    symbol=symbol,
                    side="BUY",
                    quantity=quantity,
                    price=response.executed_price or 0,
                    order_id=response.order_id,
                    message="Order executed",
                    timestamp=now_ist(),
                )

                logger.info(
                    "Buy order executed",
                    symbol=symbol,
                    quantity=quantity,
                    price=response.executed_price,
                    order_id=response.order_id,
                )

            else:
                result = TradeResult(
                    success=False,
                    symbol=symbol,
                    side="BUY",
                    quantity=quantity,
                    price=0,
                    order_id=response.order_id,
                    message=f"Order {response.status.value}: {response.message}",
                    timestamp=now_ist(),
                )

                logger.warning(
                    "Buy order not executed",
                    symbol=symbol,
                    status=response.status.value,
                    message=response.message,
                )

        except OrderExecutionError as e:
            result = TradeResult(
                success=False,
                symbol=symbol,
                side="BUY",
                quantity=quantity,
                price=0,
                order_id="",
                message=str(e),
                timestamp=now_ist(),
            )
            logger.error(f"Buy order failed for {symbol}: {e}")

        self._trade_history.append(result)
        if result.success:
            _persist_trade(result)
        return result

    def _execute_short_entry(
        self,
        symbol: str,
        quantity: int,
        prediction: Prediction,
        entry_reason: str,
    ) -> TradeResult:
        """Execute a short entry (SELL first)."""
        order = Order(
            symbol=symbol,
            quantity=quantity,
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            product=ProductType.MIS,
        )

        try:
            response = self.broker.place_order(order)

            if response.status == OrderStatus.EXECUTED:
                self.positions.open_position(
                    symbol=symbol,
                    quantity=quantity,
                    entry_price=response.executed_price or 0,
                    prediction=prediction,
                    is_short=True,
                    entry_reason=entry_reason,
                    stop_loss_pct=self.risk.config.short_stop_loss_pct,
                    target_pct=self.risk.config.short_take_profit_pct,
                )

                result = TradeResult(
                    success=True,
                    symbol=symbol,
                    side="SHORT",
                    quantity=quantity,
                    price=response.executed_price or 0,
                    order_id=response.order_id,
                    message="Short entry executed",
                    timestamp=now_ist(),
                )
                logger.info("Short entry executed", symbol=symbol, quantity=quantity, price=response.executed_price)
            else:
                result = TradeResult(
                    success=False,
                    symbol=symbol,
                    side="SHORT",
                    quantity=quantity,
                    price=0,
                    order_id=response.order_id,
                    message=f"Order {response.status.value}: {response.message}",
                    timestamp=now_ist(),
                )

        except OrderExecutionError as e:
            result = TradeResult(
                success=False, symbol=symbol, side="SHORT",
                quantity=quantity, price=0, order_id="",
                message=str(e), timestamp=now_ist(),
            )
            logger.error(f"Short entry failed for {symbol}: {e}")

        self._trade_history.append(result)
        if result.success:
            _persist_trade(result)
        return result

    def check_and_execute_exits(
        self,
        predictions: dict[str, Prediction] = None,
    ) -> list[TradeResult]:
        """
        Check exit conditions and execute exit orders.
        Handles both long exits (sell) and short covers (buy).
        """
        results = []
        predictions = predictions or {}

        for position in self.positions.get_positions_for_exit_check():
            # Build a broker-compatible Position for risk check
            broker_positions = {p.symbol: p for p in self.broker.get_positions()}
            broker_pos = broker_positions.get(position.symbol)

            if broker_pos:
                should_exit, reason = self.risk.check_exit_conditions(
                    broker_pos,
                    is_short=position.is_short,
                    holding_minutes=position.holding_time_minutes,
                )
            else:
                should_exit, reason = False, ""

            # Signal reversal check
            if not should_exit and position.symbol in predictions:
                pred = predictions[position.symbol]
                if position.is_short and pred.direction == "UP" and pred.confidence >= 0.2:
                    should_exit = True
                    reason = "signal_reversal"
                elif not position.is_short and pred.direction == "DOWN" and pred.confidence >= 0.2:
                    should_exit = True
                    reason = "signal_reversal"

            if should_exit:
                if position.is_short:
                    result = self._execute_short_cover(
                        symbol=position.symbol,
                        quantity=position.quantity,
                        exit_reason=reason,
                    )
                else:
                    result = self._execute_sell(
                        symbol=position.symbol,
                        quantity=position.quantity,
                        exit_reason=reason,
                    )
                results.append(result)

        return results

    def _execute_sell(
        self,
        symbol: str,
        quantity: int,
        exit_reason: str,
    ) -> TradeResult:
        """Execute a sell order."""
        order = Order(
            symbol=symbol,
            quantity=quantity,
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            product=ProductType.MIS,
        )

        try:
            response = self.broker.place_order(order)

            if response.status == OrderStatus.EXECUTED:
                # Close position and get trade summary
                trade_summary = self.positions.close_position(
                    symbol=symbol,
                    exit_price=response.executed_price or 0,
                    exit_reason=exit_reason,
                )

                # Record PnL with risk guardian
                if trade_summary:
                    self.risk.record_trade(pnl=trade_summary["pnl"])

                result = TradeResult(
                    success=True,
                    symbol=symbol,
                    side="SELL",
                    quantity=quantity,
                    price=response.executed_price or 0,
                    order_id=response.order_id,
                    message=f"Exit: {exit_reason}",
                    timestamp=now_ist(),
                )

                logger.info(
                    "Sell order executed",
                    symbol=symbol,
                    quantity=quantity,
                    price=response.executed_price,
                    reason=exit_reason,
                    pnl=trade_summary["pnl"] if trade_summary else 0,
                )

            else:
                result = TradeResult(
                    success=False,
                    symbol=symbol,
                    side="SELL",
                    quantity=quantity,
                    price=0,
                    order_id=response.order_id,
                    message=f"Order {response.status.value}: {response.message}",
                    timestamp=now_ist(),
                )

        except OrderExecutionError as e:
            result = TradeResult(
                success=False,
                symbol=symbol,
                side="SELL",
                quantity=quantity,
                price=0,
                order_id="",
                message=str(e),
                timestamp=now_ist(),
            )
            logger.error(f"Sell order failed for {symbol}: {e}")

        self._trade_history.append(result)
        if result.success:
            _persist_trade(result)
        return result

    def _execute_short_cover(
        self,
        symbol: str,
        quantity: int,
        exit_reason: str,
    ) -> TradeResult:
        """Cover a short position (BUY to close)."""
        order = Order(
            symbol=symbol,
            quantity=quantity,
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            product=ProductType.MIS,
        )

        try:
            response = self.broker.place_order(order)

            if response.status == OrderStatus.EXECUTED:
                trade_summary = self.positions.close_position(
                    symbol=symbol,
                    exit_price=response.executed_price or 0,
                    exit_reason=exit_reason,
                )

                if trade_summary:
                    self.risk.record_trade(pnl=trade_summary["pnl"])

                result = TradeResult(
                    success=True,
                    symbol=symbol,
                    side="COVER",
                    quantity=quantity,
                    price=response.executed_price or 0,
                    order_id=response.order_id,
                    message=f"Short covered: {exit_reason}",
                    timestamp=now_ist(),
                )
                logger.info(
                    "Short cover executed",
                    symbol=symbol, quantity=quantity,
                    price=response.executed_price, reason=exit_reason,
                    pnl=trade_summary["pnl"] if trade_summary else 0,
                )
            else:
                result = TradeResult(
                    success=False, symbol=symbol, side="COVER",
                    quantity=quantity, price=0, order_id=response.order_id,
                    message=f"Order {response.status.value}: {response.message}",
                    timestamp=now_ist(),
                )

        except OrderExecutionError as e:
            result = TradeResult(
                success=False, symbol=symbol, side="COVER",
                quantity=quantity, price=0, order_id="",
                message=str(e), timestamp=now_ist(),
            )
            logger.error(f"Short cover failed for {symbol}: {e}")

        self._trade_history.append(result)
        if result.success:
            _persist_trade(result)
        return result

    def square_off_all(self) -> list[TradeResult]:
        """
        Square off all open positions (both long and short).
        Used at end of day or when circuit breaker triggers.

        Returns:
            List of TradeResult for all exit trades
        """
        results = []

        for position in self.positions.get_all_positions():
            if position.is_short:
                result = self._execute_short_cover(
                    symbol=position.symbol,
                    quantity=position.quantity,
                    exit_reason="manual_square_off",
                )
            else:
                result = self._execute_sell(
                    symbol=position.symbol,
                    quantity=position.quantity,
                    exit_reason="manual_square_off",
                )
            results.append(result)

        return results

    def get_trade_history(self) -> list[dict[str, Any]]:
        """Get trade history for the session."""
        return [t.to_dict() for t in self._trade_history]

    def get_summary(self) -> dict[str, Any]:
        """Get executor summary."""
        successful = [t for t in self._trade_history if t.success]
        buys = [t for t in successful if t.side == "BUY"]
        sells = [t for t in successful if t.side == "SELL"]

        return {
            "total_trades": len(successful),
            "buy_trades": len(buys),
            "sell_trades": len(sells),
            "total_buy_value": sum(t.price * t.quantity for t in buys),
            "total_sell_value": sum(t.price * t.quantity for t in sells),
        }
