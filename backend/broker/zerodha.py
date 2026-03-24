"""
Zerodha Kite Connect Broker implementation.
Wraps the kiteconnect SDK to implement our Broker interface.
"""

from datetime import datetime
from typing import Any

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
    BrokerConnectionError,
    InsufficientFundsError,
    OrderExecutionError,
    OrderRejectedError,
)
from backend.core.logger import get_logger

logger = get_logger(__name__)


class ZerodhaBroker(Broker):
    """
    Zerodha Kite Connect broker implementation.

    Authentication Flow:
    1. User visits login URL and authenticates
    2. Zerodha redirects to callback with request_token
    3. Exchange request_token for access_token
    4. Use access_token for all API calls

    Access token expires at 6 AM next day.
    """

    ORDER_TYPE_MAP = {
        OrderType.MARKET: "MARKET",
        OrderType.LIMIT: "LIMIT",
        OrderType.STOP_LOSS: "SL",
        OrderType.STOP_LOSS_MARKET: "SL-M",
    }

    PRODUCT_TYPE_MAP = {
        ProductType.CNC: "CNC",
        ProductType.MIS: "MIS",
        ProductType.NRML: "NRML",
    }

    STATUS_MAP = {
        "PUT ORDER REQ RECEIVED": OrderStatus.PENDING,
        "VALIDATION PENDING": OrderStatus.PENDING,
        "OPEN PENDING": OrderStatus.PENDING,
        "OPEN": OrderStatus.OPEN,
        "TRIGGER PENDING": OrderStatus.OPEN,
        "COMPLETE": OrderStatus.EXECUTED,
        "REJECTED": OrderStatus.REJECTED,
        "CANCELLED": OrderStatus.CANCELLED,
    }

    def __init__(self, api_key: str, api_secret: str):
        self.api_key = api_key
        self.api_secret = api_secret
        self._kite = None
        self._authenticated = False
        self._access_token = None

        logger.info("ZerodhaBroker initialized", api_key=api_key)

    def get_login_url(self) -> str:
        """Get Kite login URL for user authentication."""
        return f"https://kite.zerodha.com/connect/login?v=3&api_key={self.api_key}"

    def authenticate(self, request_token: str = None, access_token: str = None) -> bool:
        """
        Authenticate with Kite Connect.

        Args:
            request_token: Token from login callback (first time auth)
            access_token: Existing access token (session restore)
        """
        try:
            from kiteconnect import KiteConnect

            self._kite = KiteConnect(api_key=self.api_key)

            if access_token:
                self._kite.set_access_token(access_token)
                self._access_token = access_token
            elif request_token:
                data = self._kite.generate_session(
                    request_token=request_token,
                    api_secret=self.api_secret
                )
                self._access_token = data["access_token"]
                self._kite.set_access_token(self._access_token)
                logger.info("Generated new session", user_id=data.get("user_id"))
            else:
                raise BrokerAuthenticationError(
                    "Either request_token or access_token required"
                )

            profile = self._kite.profile()
            self._authenticated = True

            logger.info(
                "Authenticated successfully",
                user_id=profile.get("user_id"),
                email=profile.get("email"),
            )

            return True

        except Exception as e:
            self._authenticated = False
            logger.error("Authentication failed", error=str(e))
            raise BrokerAuthenticationError(f"Kite authentication failed: {e}")

    def is_authenticated(self) -> bool:
        return self._authenticated and self._kite is not None

    def _ensure_authenticated(self) -> None:
        if not self.is_authenticated():
            raise BrokerConnectionError("Not authenticated. Call authenticate() first.")

    @property
    def access_token(self) -> str:
        return self._access_token

    # =========================================================================
    # Order Management
    # =========================================================================

    def place_order(self, order: Order) -> OrderResponse:
        self._ensure_authenticated()

        try:
            logger.info(
                "Placing order",
                symbol=order.symbol,
                side=order.side.value,
                quantity=order.quantity,
                order_type=order.order_type.value,
            )

            order_params = {
                "tradingsymbol": order.symbol,
                "exchange": "NSE",
                "transaction_type": order.side.value,
                "quantity": order.quantity,
                "order_type": self.ORDER_TYPE_MAP[order.order_type],
                "product": self.PRODUCT_TYPE_MAP[order.product],
                "variety": "regular",
            }

            if order.order_type == OrderType.LIMIT and order.price:
                order_params["price"] = order.price

            if order.order_type in (OrderType.STOP_LOSS, OrderType.STOP_LOSS_MARKET):
                if order.trigger_price:
                    order_params["trigger_price"] = order.trigger_price

            if order.reference_id:
                order_params["tag"] = order.reference_id[:20]

            order_id = self._kite.place_order(**order_params)

            result = OrderResponse(
                order_id=str(order_id),
                status=OrderStatus.PENDING,
                symbol=order.symbol,
                quantity=order.quantity,
                side=order.side,
            )

            logger.info("Order placed", order_id=order_id)
            return result

        except Exception as e:
            error_msg = str(e)
            logger.error("Order placement failed", error=error_msg, symbol=order.symbol)

            if "insufficient" in error_msg.lower() or "margin" in error_msg.lower():
                raise InsufficientFundsError(
                    f"Insufficient funds: {error_msg}",
                    symbol=order.symbol,
                )

            if "rejected" in error_msg.lower():
                raise OrderRejectedError(
                    f"Order rejected: {error_msg}",
                    symbol=order.symbol,
                )

            raise OrderExecutionError(
                f"Order execution failed: {error_msg}",
                symbol=order.symbol,
            )

    def cancel_order(self, order_id: str) -> bool:
        self._ensure_authenticated()

        try:
            logger.info("Cancelling order", order_id=order_id)
            self._kite.cancel_order(variety="regular", order_id=order_id)
            logger.info("Order cancelled", order_id=order_id)
            return True
        except Exception as e:
            logger.error("Order cancellation failed", order_id=order_id, error=str(e))
            return False

    def get_order_status(self, order_id: str) -> OrderResponse:
        self._ensure_authenticated()

        try:
            orders = self._kite.order_history(order_id=order_id)
            if not orders:
                raise BrokerConnectionError(f"Order {order_id} not found")

            latest = orders[-1]
            status = self.STATUS_MAP.get(latest.get("status", ""), OrderStatus.PENDING)

            return OrderResponse(
                order_id=order_id,
                status=status,
                symbol=latest.get("tradingsymbol", ""),
                quantity=latest.get("quantity", 0),
                side=OrderSide(latest.get("transaction_type", "BUY")),
                executed_price=latest.get("average_price"),
                executed_quantity=latest.get("filled_quantity"),
            )

        except Exception as e:
            logger.error("Failed to get order status", order_id=order_id, error=str(e))
            raise BrokerConnectionError(f"Failed to get order status: {e}")

    def get_orders(self) -> list[OrderResponse]:
        self._ensure_authenticated()

        try:
            orders = self._kite.orders()
            result = []

            for order_data in orders:
                status = self.STATUS_MAP.get(
                    order_data.get("status", ""),
                    OrderStatus.PENDING
                )

                result.append(OrderResponse(
                    order_id=str(order_data.get("order_id", "")),
                    status=status,
                    symbol=order_data.get("tradingsymbol", ""),
                    quantity=order_data.get("quantity", 0),
                    side=OrderSide(order_data.get("transaction_type", "BUY")),
                    executed_price=order_data.get("average_price"),
                    executed_quantity=order_data.get("filled_quantity"),
                ))

            return result

        except Exception as e:
            logger.error("Failed to get orders", error=str(e))
            return []

    # =========================================================================
    # Portfolio
    # =========================================================================

    def get_positions(self) -> list[Position]:
        self._ensure_authenticated()

        try:
            data = self._kite.positions()
            positions = []

            for pos in data.get("net", []):
                quantity = pos.get("quantity", 0)
                if quantity == 0:
                    continue

                positions.append(Position(
                    symbol=pos.get("tradingsymbol", ""),
                    quantity=quantity,
                    avg_price=pos.get("average_price", 0),
                    current_price=pos.get("last_price", 0),
                    product=ProductType(pos.get("product", "MIS")),
                    exchange=pos.get("exchange", "NSE"),
                ))

            return positions

        except Exception as e:
            logger.error("Failed to get positions", error=str(e))
            return []

    def get_holdings(self) -> list[Holding]:
        self._ensure_authenticated()

        try:
            holdings_data = self._kite.holdings()
            holdings = []

            for h in holdings_data:
                quantity = h.get("quantity", 0)
                if quantity == 0:
                    continue

                holdings.append(Holding(
                    symbol=h.get("tradingsymbol", ""),
                    quantity=int(quantity),
                    avg_price=h.get("average_price", 0),
                    current_price=h.get("last_price", 0),
                    isin=h.get("isin", ""),
                ))

            return holdings

        except Exception as e:
            logger.error("Failed to get holdings", error=str(e))
            return []

    def get_margin(self) -> MarginInfo:
        self._ensure_authenticated()

        try:
            margins = self._kite.margins(segment="equity")

            return MarginInfo(
                available_cash=margins.get("available", {}).get("cash", 0),
                used_margin=margins.get("utilised", {}).get("debits", 0),
                total_balance=margins.get("net", 0),
            )

        except Exception as e:
            logger.error("Failed to get margin", error=str(e))
            return MarginInfo(available_cash=0, used_margin=0, total_balance=0)

    # =========================================================================
    # Market Data
    # =========================================================================

    def get_ltp(self, symbols: list[str]) -> dict[str, float]:
        self._ensure_authenticated()

        if not symbols:
            return {}

        try:
            instruments = [f"NSE:{symbol}" for symbol in symbols]
            data = self._kite.ltp(instruments)

            result = {}
            for key, value in data.items():
                symbol = key.replace("NSE:", "")
                result[symbol] = value.get("last_price", 0)

            return result

        except Exception as e:
            logger.error("Failed to get LTP", symbols=symbols, error=str(e))
            return {}

    def get_quote(self, symbol: str) -> Quote:
        self._ensure_authenticated()

        try:
            data = self._kite.quote([f"NSE:{symbol}"])
            quote_data = data.get(f"NSE:{symbol}", {})

            ohlc = quote_data.get("ohlc", {})

            return Quote(
                symbol=symbol,
                ltp=quote_data.get("last_price", 0),
                open=ohlc.get("open", 0),
                high=ohlc.get("high", 0),
                low=ohlc.get("low", 0),
                close=ohlc.get("close", 0),
                volume=quote_data.get("volume", 0),
            )

        except Exception as e:
            logger.error("Failed to get quote", symbol=symbol, error=str(e))
            raise BrokerConnectionError(f"Failed to get quote for {symbol}: {e}")

    # =========================================================================
    # User Info
    # =========================================================================

    def get_profile(self) -> dict[str, Any]:
        self._ensure_authenticated()

        try:
            return self._kite.profile()
        except Exception as e:
            logger.error("Failed to get profile", error=str(e))
            return {}

    # =========================================================================
    # Instruments
    # =========================================================================

    def get_instruments(self, exchange: str = "NSE") -> list[dict]:
        """Get all instruments for an exchange."""
        self._ensure_authenticated()

        try:
            return self._kite.instruments(exchange=exchange)
        except Exception as e:
            logger.error("Failed to get instruments", error=str(e))
            return []

    def get_instrument_token(self, symbol: str, exchange: str = "NSE") -> int:
        """Get instrument token for a symbol."""
        self._ensure_authenticated()

        try:
            instruments = self._kite.instruments(exchange=exchange)
            for inst in instruments:
                if inst.get("tradingsymbol") == symbol:
                    return inst.get("instrument_token")
            return 0
        except Exception as e:
            logger.error("Failed to get instrument token", symbol=symbol, error=str(e))
            return 0
