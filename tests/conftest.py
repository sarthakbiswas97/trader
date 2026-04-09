"""
Shared pytest fixtures.

Provides:
  - fake_broker: minimal Broker implementation backed by an in-memory state.
  - sample_prediction: a Prediction-like object for risk tests.

The goal is to keep tests fast and isolated — no DB, no HTTP, no Kite.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from backend.broker.base import Broker, MarginInfo, Position, ProductType


@dataclass
class _PredictionStub:
    """Stub matching the fields of backend.ml.inference.Prediction used by RiskGuardian."""

    symbol: str
    confidence: float = 0.8
    probability: float = 0.7
    direction: str = "UP"
    timestamp: Any = None
    top_features: list = None


class FakeBroker(Broker):
    """Minimal in-memory broker for tests. Only implements what RiskGuardian touches."""

    def __init__(self, cash: float = 100_000.0):
        self._cash = cash
        self._positions: list[Position] = []

    # ----- Broker interface (only the methods we need) -----

    def get_margin(self) -> MarginInfo:
        invested = sum(abs(p.invested_value) for p in self._positions)
        return MarginInfo(
            available_cash=self._cash,
            used_margin=invested,
            total_balance=self._cash + invested,
        )

    def get_positions(self) -> list[Position]:
        return list(self._positions)

    # ----- Test helpers -----

    def add_position(self, symbol: str, quantity: int, avg_price: float, current_price: float | None = None) -> None:
        self._positions.append(
            Position(
                symbol=symbol,
                quantity=quantity,
                avg_price=avg_price,
                current_price=current_price if current_price is not None else avg_price,
                product=ProductType.MIS,
            )
        )

    # ----- Stubs for unused abstract methods -----

    def authenticate(self) -> bool:  # pragma: no cover
        return True

    def is_authenticated(self) -> bool:  # pragma: no cover
        return True

    def place_order(self, order):  # pragma: no cover
        raise NotImplementedError

    def cancel_order(self, order_id: str) -> bool:  # pragma: no cover
        raise NotImplementedError

    def get_order_status(self, order_id: str):  # pragma: no cover
        raise NotImplementedError

    def get_orders(self):  # pragma: no cover
        return []

    def get_holdings(self):  # pragma: no cover
        return []

    def get_ltp(self, symbols: list[str]) -> dict[str, float]:  # pragma: no cover
        return {}

    def get_quote(self, symbol: str):  # pragma: no cover
        return None

    def get_profile(self) -> dict[str, Any]:  # pragma: no cover
        return {}


@pytest.fixture
def fake_broker() -> FakeBroker:
    return FakeBroker(cash=100_000.0)


@pytest.fixture
def sample_prediction() -> _PredictionStub:
    return _PredictionStub(symbol="RELIANCE", confidence=0.8, probability=0.7)
