"""
Unit tests for the reversal scoring function.

The function takes a HistoricalDataService for loading candles. We pass a stub
that returns deterministic dataframes so the test is hermetic (no disk reads).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backend.core.scoring import compute_reversal_scores


class _StubHistoricalDataService:
    """Returns synthetic OHLC frames for given symbols."""

    def __init__(self, frames: dict[str, pd.DataFrame]):
        self._frames = frames

    def load_candles(self, symbol: str, interval: str) -> pd.DataFrame:
        return self._frames.get(symbol, pd.DataFrame())


def _make_falling_frame(start: float, drop_pct_per_day: float, n: int = 30) -> pd.DataFrame:
    closes = [start * (1 + drop_pct_per_day) ** i for i in range(n)]
    return pd.DataFrame({"close": closes})


def test_returns_empty_when_too_few_symbols_have_data():
    ds = _StubHistoricalDataService(
        {"RELIANCE": _make_falling_frame(100, -0.01)}
    )
    df = compute_reversal_scores(["RELIANCE"], prices={"RELIANCE": 100.0}, ds=ds)
    assert df.empty  # need at least 5 symbols with data


def test_biggest_loser_gets_highest_score():
    frames = {
        "BIG_LOSER":  _make_falling_frame(200, -0.02),  # falling fast
        "MEDIUM":     _make_falling_frame(150, -0.005),
        "FLAT":       _make_falling_frame(100, 0.0),
        "GAINER":     _make_falling_frame(80, 0.005),
        "BIG_GAINER": _make_falling_frame(50, 0.01),
    }
    prices = {sym: f["close"].iloc[-1] for sym, f in frames.items()}
    ds = _StubHistoricalDataService(frames)

    df = compute_reversal_scores(list(frames.keys()), prices=prices, ds=ds)

    assert not df.empty
    assert df.index[0] == "BIG_LOSER"   # highest score → most oversold
    assert df.index[-1] == "BIG_GAINER"


def test_score_is_normalized_between_zero_and_one():
    frames = {
        f"S{i}": _make_falling_frame(100, (i - 2) * 0.01)
        for i in range(6)
    }
    prices = {sym: f["close"].iloc[-1] for sym, f in frames.items()}
    ds = _StubHistoricalDataService(frames)

    df = compute_reversal_scores(list(frames.keys()), prices=prices, ds=ds)

    assert df["score"].between(0, 1).all()


def test_skips_symbols_with_insufficient_history():
    frames = {
        "OK1": _make_falling_frame(100, -0.01),
        "OK2": _make_falling_frame(100, -0.005),
        "OK3": _make_falling_frame(100, 0.0),
        "OK4": _make_falling_frame(100, 0.005),
        "OK5": _make_falling_frame(100, 0.01),
        "TOO_SHORT": pd.DataFrame({"close": np.linspace(100, 95, 5)}),
    }
    prices = {sym: f["close"].iloc[-1] for sym, f in frames.items()}
    ds = _StubHistoricalDataService(frames)

    df = compute_reversal_scores(list(frames.keys()), prices=prices, ds=ds)

    assert "TOO_SHORT" not in df.index
    assert len(df) == 5
