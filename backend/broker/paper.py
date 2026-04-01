"""
Paper Trading Broker implementation.
Simulates trading with virtual money using real market data from Zerodha.
"""

import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import uuid4

from backend.broker.base import (
    Broker,
    Holding,
    MarginInfo,
    Order,
    OrderResponse,
    OrderSide,
    OrderStatus,
    OrderType,
    Position,
    ProductType,
    Quote,
)
from backend.core.exceptions import (
    BrokerAuthenticationError,
    OrderExecutionError,
)
from backend.core.logger import get_logger

logger = get_logger(__name__)


@dataclass
class PaperPosition:
    symbol: str
    quantity: int
    avg_price: float
    product: ProductType
    opened_at: datetime = field(default_factory=datetime.now)


@dataclass
class PaperTrade:
    trade_id: str
    order_id: str
    symbol: str
    side: OrderSide
    quantity: int
    price: float
    timestamp: datetime = field(default_factory=datetime.now)


class PaperBroker(Broker):
    """
    Paper trading broker using real market data from Zerodha.
    Same interface as ZerodhaBroker for easy swapping.
    """

    def __init__(
        self,
        initial_capital: float = 100000.0,
        kite_api_key: str | None = None,
        kite_api_secret: str | None = None,
    ):
        self.initial_capital = initial_capital
        self.capital = initial_capital
        self.kite_api_key = kite_api_key
        self.kite_api_secret = kite_api_secret

        self._positions: dict[str, PaperPosition] = {}
        self._orders: dict[str, OrderResponse] = {}
        self._trades: list[PaperTrade] = []
        self._authenticated = False
        self._kite = None
        self._access_token = None

        # LTP cache: symbol -> (price, timestamp)
        self._ltp_cache: dict[str, tuple[float, float]] = {}
        self._ltp_cache_ttl: float = 3.0  # seconds

        self.realized_pnl = 0.0
        self.total_trades = 0
        self.winning_trades = 0
        self.losing_trades = 0

        logger.info(
            "PaperBroker initialized",
            initial_capital=initial_capital,
            has_kite_creds=bool(kite_api_key),
        )

    def get_login_url(self) -> str:
        """Get Kite login URL for real market data."""
        if self.kite_api_key:
            return f"https://kite.zerodha.com/connect/login?v=3&api_key={self.kite_api_key}"
        return ""

    def authenticate(self, request_token: str = None, access_token: str = None) -> bool:
        """
        Authenticate paper broker.
        Optionally connect to Zerodha for real market data.
        """
        try:
            self._authenticated = True

            if self.kite_api_key and (request_token or access_token):
                try:
                    from kiteconnect import KiteConnect

                    self._kite = KiteConnect(api_key=self.kite_api_key)

                    if access_token:
                        self._kite.set_access_token(access_token)
                        self._access_token = access_token
                    elif request_token:
                        data = self._kite.generate_session(
                            request_token=request_token,
                            api_secret=self.kite_api_secret
                        )
                        self._access_token = data["access_token"]
                        self._kite.set_access_token(self._access_token)

                    logger.info("Connected to Zerodha for real market data")

                except Exception as e:
                    logger.warning(
                        "Failed to connect to Zerodha, using mock prices",
                        error=str(e)
                    )
                    self._kite = None

            logger.info(
                "Paper broker authenticated",
                capital=self.capital,
                real_market_data=self._kite is not None,
            )

            return True

        except Exception as e:
            logger.error("Paper broker authentication failed", error=str(e))
            raise BrokerAuthenticationError(f"Paper broker auth failed: {e}")

    def is_authenticated(self) -> bool:
        return self._authenticated

    @property
    def access_token(self) -> str:
        return self._access_token

    def _batch_ltp(self, symbols: list[str]) -> dict[str, float]:
        """Batch fetch LTP with caching and retry. Single API call for all symbols."""
        if not symbols:
            return {}

        now = time.time()
        result = {}
        stale_symbols = []

        # Check cache first
        for s in symbols:
            cached = self._ltp_cache.get(s)
            if cached and (now - cached[1]) < self._ltp_cache_ttl:
                result[s] = cached[0]
            else:
                stale_symbols.append(s)

        # Fetch stale symbols from Kite in one batch
        if stale_symbols and self._kite:
            instruments = [f"NSE:{s}" for s in stale_symbols]
            for attempt in range(2):
                try:
                    data = self._kite.ltp(instruments)
                    fetch_time = time.time()
                    for key, value in data.items():
                        sym = key.replace("NSE:", "")
                        price = value.get("last_price", 0)
                        if price > 0:
                            self._ltp_cache[sym] = (price, fetch_time)
                            result[sym] = price
                    break
                except Exception as e:
                    if attempt == 0:
                        logger.warning(f"LTP fetch retry after error: {e}")
                        time.sleep(1)
                    else:
                        logger.warning(f"LTP fetch failed after retry: {e}")

        # Fill missing symbols from stale cache or mock
        for s in symbols:
            if s not in result:
                cached = self._ltp_cache.get(s)
                if cached:
                    result[s] = cached[0]  # stale cache better than mock
                else:
                    result[s] = 1000.0
                    logger.warning(f"Using mock price for {s}")

        return result

    def _get_real_ltp(self, symbol: str) -> float:
        """Get real LTP for a single symbol (uses batch internally)."""
        return self._batch_ltp([symbol]).get(symbol, 1000.0)

    def _generate_order_id(self) -> str:
        return f"PAPER_{uuid4().hex[:16].upper()}"

    def place_order(self, order: Order) -> OrderResponse:
        if not self._authenticated:
            raise OrderExecutionError("Not authenticated")

        order_id = self._generate_order_id()

        logger.info(
            "Paper order received",
            order_id=order_id,
            symbol=order.symbol,
            side=order.side.value,
            quantity=order.quantity,
        )

        try:
            current_price = self._get_real_ltp(order.symbol)
            execution_price = current_price

            if order.order_type == OrderType.LIMIT and order.price:
                if order.side == OrderSide.BUY and order.price >= current_price:
                    execution_price = order.price
                elif order.side == OrderSide.SELL and order.price <= current_price:
                    execution_price = order.price
                else:
                    response = OrderResponse(
                        order_id=order_id,
                        status=OrderStatus.OPEN,
                        symbol=order.symbol,
                        quantity=order.quantity,
                        side=order.side,
                        message="Limit price not met",
                    )
                    self._orders[order_id] = response
                    return response

            if order.side == OrderSide.BUY:
                response = self._execute_buy(order, order_id, execution_price)
            else:
                response = self._execute_sell(order, order_id, execution_price)

            self._orders[order_id] = response

            if response.status == OrderStatus.EXECUTED:
                self._trades.append(PaperTrade(
                    trade_id=f"T_{uuid4().hex[:8].upper()}",
                    order_id=order_id,
                    symbol=order.symbol,
                    side=order.side,
                    quantity=order.quantity,
                    price=execution_price,
                ))
                self.total_trades += 1

            return response

        except Exception as e:
            logger.error("Paper order execution failed", error=str(e))
            raise OrderExecutionError(f"Paper order failed: {e}", symbol=order.symbol)

    def _execute_buy(self, order: Order, order_id: str, price: float) -> OrderResponse:
        cost = price * order.quantity

        if cost > self.capital:
            logger.warning("Insufficient funds", required=cost, available=self.capital)
            return OrderResponse(
                order_id=order_id,
                status=OrderStatus.REJECTED,
                symbol=order.symbol,
                quantity=order.quantity,
                side=order.side,
                message=f"Insufficient funds. Required: {cost:.2f}, Available: {self.capital:.2f}",
            )

        self.capital -= cost

        if order.symbol in self._positions:
            pos = self._positions[order.symbol]
            total_qty = pos.quantity + order.quantity
            total_cost = (pos.avg_price * pos.quantity) + (price * order.quantity)
            pos.avg_price = total_cost / total_qty
            pos.quantity = total_qty
        else:
            self._positions[order.symbol] = PaperPosition(
                symbol=order.symbol,
                quantity=order.quantity,
                avg_price=price,
                product=order.product,
            )

        logger.info(
            "Paper BUY executed",
            symbol=order.symbol,
            quantity=order.quantity,
            price=price,
            remaining_capital=self.capital,
        )

        return OrderResponse(
            order_id=order_id,
            status=OrderStatus.EXECUTED,
            symbol=order.symbol,
            quantity=order.quantity,
            side=order.side,
            executed_price=price,
            executed_quantity=order.quantity,
        )

    def _execute_sell(self, order: Order, order_id: str, price: float) -> OrderResponse:
        if order.symbol not in self._positions:
            return OrderResponse(
                order_id=order_id,
                status=OrderStatus.REJECTED,
                symbol=order.symbol,
                quantity=order.quantity,
                side=order.side,
                message="No position to sell",
            )

        pos = self._positions[order.symbol]

        if pos.quantity < order.quantity:
            return OrderResponse(
                order_id=order_id,
                status=OrderStatus.REJECTED,
                symbol=order.symbol,
                quantity=order.quantity,
                side=order.side,
                message=f"Insufficient quantity. Have: {pos.quantity}",
            )

        pnl = (price - pos.avg_price) * order.quantity
        self.realized_pnl += pnl

        if pnl > 0:
            self.winning_trades += 1
        else:
            self.losing_trades += 1

        self.capital += price * order.quantity

        pos.quantity -= order.quantity
        if pos.quantity == 0:
            del self._positions[order.symbol]

        logger.info(
            "Paper SELL executed",
            symbol=order.symbol,
            quantity=order.quantity,
            price=price,
            pnl=pnl,
        )

        return OrderResponse(
            order_id=order_id,
            status=OrderStatus.EXECUTED,
            symbol=order.symbol,
            quantity=order.quantity,
            side=order.side,
            executed_price=price,
            executed_quantity=order.quantity,
            message=f"P&L: {pnl:.2f}",
        )

    def cancel_order(self, order_id: str) -> bool:
        if order_id in self._orders:
            order = self._orders[order_id]
            if order.status == OrderStatus.OPEN:
                order.status = OrderStatus.CANCELLED
                return True
        return False

    def get_order_status(self, order_id: str) -> OrderResponse:
        if order_id in self._orders:
            return self._orders[order_id]

        return OrderResponse(
            order_id=order_id,
            status=OrderStatus.FAILED,
            symbol="",
            quantity=0,
            side=OrderSide.BUY,
            message="Order not found",
        )

    def get_orders(self) -> list[OrderResponse]:
        return list(self._orders.values())

    def get_positions(self) -> list[Position]:
        if not self._positions:
            return []
        # Single batch LTP call for all positions
        symbols = list(self._positions.keys())
        prices = self._batch_ltp(symbols)
        positions = []
        for symbol, pos in self._positions.items():
            positions.append(Position(
                symbol=symbol,
                quantity=pos.quantity,
                avg_price=pos.avg_price,
                current_price=prices.get(symbol, pos.avg_price),
                product=pos.product,
            ))
        return positions

    def get_holdings(self) -> list[Holding]:
        return []

    def get_margin(self) -> MarginInfo:
        positions = self.get_positions()  # single batch call
        unrealized_pnl = sum(p.pnl for p in positions)
        used_margin = sum(p.invested_value for p in positions)
        return MarginInfo(
            available_cash=self.capital,
            used_margin=used_margin,
            total_balance=self.capital + unrealized_pnl,
        )

    def get_ltp(self, symbols: list[str]) -> dict[str, float]:
        return self._batch_ltp(symbols)

    def get_quote(self, symbol: str) -> Quote:
        ltp = self._get_real_ltp(symbol)
        return Quote(
            symbol=symbol,
            ltp=ltp,
            open=ltp,
            high=ltp,
            low=ltp,
            close=ltp,
            volume=0,
        )

    def get_profile(self) -> dict[str, Any]:
        return {
            "mode": "paper",
            "initial_capital": self.initial_capital,
            "current_capital": self.capital,
            "realized_pnl": self.realized_pnl,
            "total_trades": self.total_trades,
            "win_rate": (
                self.winning_trades / self.total_trades * 100
                if self.total_trades > 0 else 0
            ),
        }

    def get_trades(self) -> list[PaperTrade]:
        return self._trades.copy()

    def reset(self) -> None:
        self.capital = self.initial_capital
        self._positions.clear()
        self._orders.clear()
        self._trades.clear()
        self.realized_pnl = 0.0
        self.total_trades = 0
        self.winning_trades = 0
        self.losing_trades = 0
        logger.info("Paper trading reset")

    def get_summary(self) -> dict[str, Any]:
        positions = self.get_positions()
        unrealized_pnl = sum(p.pnl for p in positions)

        return {
            "initial_capital": self.initial_capital,
            "current_capital": self.capital,
            "realized_pnl": self.realized_pnl,
            "unrealized_pnl": unrealized_pnl,
            "total_pnl": self.realized_pnl + unrealized_pnl,
            "total_trades": self.total_trades,
            "win_rate": (
                self.winning_trades / self.total_trades * 100
                if self.total_trades > 0 else 0
            ),
            "open_positions": len(positions),
        }
