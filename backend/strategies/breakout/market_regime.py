"""
Market Regime Detector — Uses NIFTY 50 index to determine market state.

Answers two questions:
  1. Is the market trending or sideways? (regime)
  2. Which direction is the trend? (direction)

Uses real NIFTY 50 index data, not synthetic approximations.
"""

from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from backend.core.indicators import adx, ema
from backend.core.logger import get_logger

logger = get_logger(__name__)

_INDEX_PATH = Path(__file__).parent.parent.parent / "data" / "index" / "NIFTY50_5m.csv"

# Regime thresholds
ADX_TRENDING = 20       # ADX above this = trending
ADX_SIDEWAYS = 15       # ADX below this = sideways
TREND_DIVERGENCE = 0.002  # EMA20 vs EMA50 must diverge by 0.2%


class MarketRegime:
    """
    Determines market regime from NIFTY 50 index data.

    Usage:
        regime = MarketRegime()
        regime.load()

        state = regime.get_regime(some_date)
        # Returns: "TRENDING", "SIDEWAYS", or "UNCLEAR"

        direction = regime.get_direction(some_date)
        # Returns: "UP", "DOWN", or "NEUTRAL"
    """

    def __init__(self):
        self._data: pd.DataFrame | None = None
        self._daily_cache: dict[date, dict] = {}

    def load(self, path: str = None) -> None:
        """Load NIFTY 50 index data."""
        path = Path(path) if path else _INDEX_PATH

        if not path.exists():
            raise FileNotFoundError(
                f"NIFTY 50 index data not found at {path}. "
                "Download it first with the data pipeline."
            )

        df = pd.read_csv(path)
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df = df.sort_values("timestamp").reset_index(drop=True)

        # Precompute indicators on the full series
        close = df["close"]
        high = df["high"]
        low = df["low"]

        df["ema20"] = ema(close, 20)
        df["ema50"] = ema(close, 50)
        df["adx"] = adx(high, low, close, 14)
        df["date"] = df["timestamp"].dt.date

        self._data = df

        # Build daily cache: for each day, compute regime at market open (~10:00 AM)
        # Use data up to 10:00 of that day (enough candles for indicators)
        for day, group in df.groupby("date"):
            # Use the last row of the morning session (up to ~10:30)
            morning = group[group["timestamp"].dt.hour <= 10]
            if morning.empty:
                morning = group.head(10)

            if len(morning) < 5:
                continue

            last = morning.iloc[-1]
            ema20_val = last["ema20"]
            ema50_val = last["ema50"]
            adx_val = last["adx"]
            price = last["close"]

            if np.isnan(ema20_val) or np.isnan(ema50_val) or np.isnan(adx_val):
                continue

            # Regime
            trend_strength = abs(ema20_val - ema50_val) / price
            if adx_val > ADX_TRENDING and trend_strength > TREND_DIVERGENCE:
                regime = "TRENDING"
            elif adx_val < ADX_SIDEWAYS:
                regime = "SIDEWAYS"
            else:
                regime = "UNCLEAR"

            # Direction
            if ema20_val > ema50_val:
                direction = "UP"
            elif ema20_val < ema50_val:
                direction = "DOWN"
            else:
                direction = "NEUTRAL"

            self._daily_cache[day] = {
                "regime": regime,
                "direction": direction,
                "adx": round(adx_val, 1),
                "ema20": round(ema20_val, 2),
                "ema50": round(ema50_val, 2),
                "trend_strength": round(trend_strength * 100, 2),
            }

        logger.info(
            "MarketRegime loaded",
            candles=len(df),
            days_cached=len(self._daily_cache),
        )

    def get_regime(self, day: date) -> str:
        """Get market regime for a day: TRENDING, SIDEWAYS, or UNCLEAR."""
        entry = self._daily_cache.get(day)
        if entry is None:
            return "UNCLEAR"
        return entry["regime"]

    def get_direction(self, day: date) -> str:
        """Get market direction for a day: UP, DOWN, or NEUTRAL."""
        entry = self._daily_cache.get(day)
        if entry is None:
            return "NEUTRAL"
        return entry["direction"]

    def should_trade(self, day: date) -> bool:
        """Should we trade today? Only if market is trending."""
        return self.get_regime(day) == "TRENDING"

    def allow_longs(self, day: date) -> bool:
        """Are long entries allowed today?"""
        return self.should_trade(day) and self.get_direction(day) == "UP"

    def allow_shorts(self, day: date) -> bool:
        """Are short entries allowed today?"""
        return self.should_trade(day) and self.get_direction(day) == "DOWN"

    def get_info(self, day: date) -> dict:
        """Get full regime info for a day."""
        return self._daily_cache.get(day, {
            "regime": "UNCLEAR",
            "direction": "NEUTRAL",
            "adx": 0,
            "ema20": 0,
            "ema50": 0,
            "trend_strength": 0,
        })

    def print_summary(self) -> None:
        """Print regime summary for all cached days."""
        if not self._daily_cache:
            print("No data loaded")
            return

        print(f"\n{'Date':<14} {'Regime':<10} {'Dir':<6} {'ADX':<6} {'Trend%':<8}")
        print("-" * 48)

        for day in sorted(self._daily_cache.keys()):
            info = self._daily_cache[day]
            marker = "✓" if info["regime"] == "TRENDING" else " "
            print(
                f"{marker} {day}  {info['regime']:<10} "
                f"{info['direction']:<6} {info['adx']:<6} "
                f"{info['trend_strength']:<8}"
            )

        trending_days = sum(1 for v in self._daily_cache.values() if v["regime"] == "TRENDING")
        total = len(self._daily_cache)
        print(f"\nTrending: {trending_days}/{total} days ({trending_days/total*100:.0f}%)")
