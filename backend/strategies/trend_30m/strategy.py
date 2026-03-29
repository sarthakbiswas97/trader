"""
30-Min Trend Following with Pullback Entries.

How it works:
  1. Identify trend: EMA(5) > EMA(15) = uptrend, EMA(5) < EMA(15) = downtrend
  2. Confirm trend strength: ADX > 20
  3. Wait for pullback: price touches or crosses EMA(5) from the trend side
  4. Enter when pullback reverses (next candle confirms trend resumes)
  5. Exit: trailing stop (1.5x ATR) or take-profit (3x ATR) or end of day

Why 30-min works:
  - Moves are 0.5-1.5% (vs 0.1-0.3% on 5-min)
  - Costs (₹5/trade) become negligible vs move size
  - Trends are cleaner, less noise
"""

from dataclasses import dataclass
from datetime import time as dtime
from typing import Literal

import numpy as np
import pandas as pd

from backend.core.logger import get_logger

logger = get_logger(__name__)


@dataclass
class TrendSetup:
    """A pullback entry in an established trend."""
    symbol: str
    direction: Literal["LONG", "SHORT"]
    entry_price: float
    ema_fast: float              # EMA(5) at entry
    ema_slow: float              # EMA(15) at entry
    trend_strength: float        # ADX value
    pullback_depth: float        # How far price pulled back (% from trend extreme)
    atr: float                   # For stop/target calculation
    timestamp: pd.Timestamp

    @property
    def quality_score(self) -> float:
        """Score the setup quality."""
        score = 0.0

        # Trend strength (ADX) — main driver
        score += min(self.trend_strength, 50) * 0.8  # 0-40

        # Pullback depth — too shallow (noise) or too deep (trend breaking) is bad
        # Sweet spot: 0.3-0.7% pullback
        if 0.002 <= self.pullback_depth <= 0.008:
            score += 20
        elif self.pullback_depth < 0.002:
            score += 5   # Too shallow, might be noise
        else:
            score += 10  # Deep but still valid

        # EMA gap (wider = stronger trend)
        ema_gap = abs(self.ema_fast - self.ema_slow) / self.entry_price
        score += min(ema_gap * 5000, 20)  # 0-20

        return score


def resample_to_30min(df_5m: pd.DataFrame) -> pd.DataFrame:
    """
    Resample 5-min candles to 30-min candles.

    Args:
        df_5m: DataFrame with columns [timestamp, open, high, low, close, volume]

    Returns:
        30-min OHLCV DataFrame
    """
    df = df_5m.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df.set_index("timestamp")

    resampled = df.resample("30min").agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    }).dropna()

    resampled = resampled.reset_index()
    return resampled


def compute_trend_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute trend indicators on 30-min candles.

    Adds: ema_5, ema_15, adx, atr, trend_direction
    """
    df = df.copy()
    close = df["close"]
    high = df["high"]
    low = df["low"]

    # EMAs
    df["ema_5"] = close.ewm(span=5, adjust=False).mean()
    df["ema_15"] = close.ewm(span=15, adjust=False).mean()

    # ADX (simplified)
    plus_dm = high.diff()
    minus_dm = -low.diff()
    plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0)

    tr = pd.concat([
        high - low,
        abs(high - close.shift(1)),
        abs(low - close.shift(1)),
    ], axis=1).max(axis=1)

    atr_14 = tr.rolling(14, min_periods=5).mean()
    df["atr"] = atr_14

    plus_di = 100 * (plus_dm.rolling(14, min_periods=5).mean() / atr_14.replace(0, 1))
    minus_di = 100 * (minus_dm.rolling(14, min_periods=5).mean() / atr_14.replace(0, 1))

    dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di).replace(0, 1)
    df["adx"] = dx.rolling(14, min_periods=5).mean()

    # Trend direction
    df["trend"] = np.where(
        (df["ema_5"] > df["ema_15"]) & (df["adx"] > 20), 1,   # Uptrend
        np.where(
            (df["ema_5"] < df["ema_15"]) & (df["adx"] > 20), -1,  # Downtrend
            0  # No trend
        )
    )

    return df


def detect_pullback(
    df: pd.DataFrame,
    nifty_trend: int = 0,
) -> TrendSetup | None:
    """
    Detect a pullback entry in an established 30-min trend.

    Two-candle pattern:
      Candle N-1: Price pulls back toward EMA(5) during established trend
      Candle N:   Price bounces off EMA and resumes trend direction

    Args:
        df: 30-min candles with trend features (at least 20 rows)
        nifty_trend: NIFTY market direction (1=up, -1=down, 0=neutral)

    Returns:
        TrendSetup if pullback detected, None otherwise
    """
    if len(df) < 5:
        return None

    curr = df.iloc[-1]  # Current candle (confirmation)
    prev = df.iloc[-2]  # Previous candle (pullback)

    ts = curr["timestamp"]
    if hasattr(ts, "time"):
        candle_time = ts.time()
        # No entries before 10:15 (first 30-min candle is noisy)
        if candle_time < dtime(10, 15):
            return None
        # No entries after 13:30 (need room for 2-4 hour hold)
        if candle_time > dtime(13, 30):
            return None

    trend = int(curr["trend"])

    # Must have established trend
    if trend == 0:
        return None

    # Market alignment: don't trade against NIFTY trend
    if nifty_trend != 0 and trend != nifty_trend:
        return None

    ema_5 = curr["ema_5"]
    ema_15 = curr["ema_15"]
    close = curr["close"]
    atr = curr["atr"]
    adx = curr["adx"]

    if pd.isna(ema_5) or pd.isna(atr) or atr <= 0:
        return None

    symbol = df.attrs.get("symbol", "UNKNOWN")

    # UPTREND pullback: price dipped to/below EMA(5), now bouncing
    if trend == 1:
        pullback_happened = prev["low"] <= prev["ema_5"] * 1.001  # Touched or crossed EMA
        resumed = curr["close"] > curr["open"] and curr["close"] > ema_5  # Bullish bounce

        if pullback_happened and resumed:
            pullback_depth = (prev["ema_5"] - prev["low"]) / prev["ema_5"]

            return TrendSetup(
                symbol=symbol,
                direction="LONG",
                entry_price=close,
                ema_fast=ema_5,
                ema_slow=ema_15,
                trend_strength=adx,
                pullback_depth=pullback_depth,
                atr=atr,
                timestamp=ts,
            )

    # DOWNTREND pullback: price rose to/above EMA(5), now dropping
    elif trend == -1:
        pullback_happened = prev["high"] >= prev["ema_5"] * 0.999  # Touched or crossed EMA
        resumed = curr["close"] < curr["open"] and curr["close"] < ema_5  # Bearish drop

        if pullback_happened and resumed:
            pullback_depth = (prev["high"] - prev["ema_5"]) / prev["ema_5"]

            return TrendSetup(
                symbol=symbol,
                direction="SHORT",
                entry_price=close,
                ema_fast=ema_5,
                ema_slow=ema_15,
                trend_strength=adx,
                pullback_depth=pullback_depth,
                atr=atr,
                timestamp=ts,
            )

    return None
