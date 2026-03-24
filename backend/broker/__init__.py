"""
Broker module - provides abstraction over trading brokers.

Supports:
- ZerodhaBroker: Real trading with Kite Connect API
- PaperBroker: Simulated trading with real market data
"""

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
from backend.broker.zerodha import ZerodhaBroker
from backend.broker.paper import PaperBroker
from backend.broker.session import load_access_token, save_access_token, clear_session
from backend.config import settings


def get_broker(auto_auth: bool = True) -> Broker:
    """
    Factory function to get the appropriate broker based on configuration.

    Args:
        auto_auth: If True, auto-authenticate using saved session (if available)

    Returns:
        ZerodhaBroker if TRADING_MODE=live
        PaperBroker if TRADING_MODE=paper
    """
    if settings.is_paper_mode:
        broker = PaperBroker(
            initial_capital=settings.paper_trading_capital,
            kite_api_key=settings.kite_api_key,
            kite_api_secret=settings.kite_api_secret,
        )
    else:
        broker = ZerodhaBroker(
            api_key=settings.kite_api_key,
            api_secret=settings.kite_api_secret,
        )

    # Auto-authenticate if session exists
    if auto_auth:
        access_token = load_access_token()
        if access_token:
            try:
                broker.authenticate(access_token=access_token)
            except Exception:
                pass  # Session expired, user will need to re-auth

    return broker


__all__ = [
    "get_broker",
    "load_access_token",
    "save_access_token",
    "clear_session",
    "Broker",
    "Order",
    "OrderResponse",
    "OrderSide",
    "OrderStatus",
    "OrderType",
    "Position",
    "Holding",
    "MarginInfo",
    "ProductType",
    "Quote",
    "ZerodhaBroker",
    "PaperBroker",
]
