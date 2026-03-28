"""
Market Regime Detection — Determines if conditions are suitable for breakout trading.

Breakouts only work in trending markets. This module gates the strategy
to avoid trading during choppy/sideways periods.
"""

from datetime import time

import numpy as np
import pandas as pd

from backend.core.indicators import adx, ema
from backend.core.logger import get_logger

logger = get_logger(__name__)

# Time windows where breakout edge is strongest
# Skip 11:30-13:30 (midday chop in Indian markets)
CHOP_START = time(11, 30)
CHOP_END = time(13, 30)

# ADX threshold for "trending" market
ADX_TRENDING_THRESHOLD = 20

# EMA trend alignment: fast EMA vs slow EMA divergence
EMA_FAST = 10
EMA_SLOW = 30
TREND_STRENGTH_MIN = 0.001  # 0.1% divergence minimum


def is_trending(candles: pd.DataFrame) -> bool:
    """
    Check if the stock is in a trending regime.

    Uses ADX (trend strength) + EMA alignment (trend direction consistency).

    Args:
        candles: Recent OHLCV data (at least 30 rows)

    Returns:
        True if market is trending, False if choppy/sideways
    """
    if len(candles) < 30:
        return False

    close = candles["close"]
    high = candles["high"]
    low = candles["low"]

    # ADX check: is there a trend?
    adx_values = adx(high, low, close, period=14)
    current_adx = adx_values.iloc[-1]

    if np.isnan(current_adx) or current_adx < ADX_TRENDING_THRESHOLD:
        return False

    # EMA alignment: are fast and slow EMAs diverging?
    ema_fast = ema(close, EMA_FAST)
    ema_slow = ema(close, EMA_SLOW)

    if ema_fast.iloc[-1] is None or ema_slow.iloc[-1] is None:
        return False

    divergence = abs(ema_fast.iloc[-1] - ema_slow.iloc[-1]) / close.iloc[-1]

    if divergence < TREND_STRENGTH_MIN:
        return False

    return True


def get_trend_direction(candles: pd.DataFrame) -> str:
    """
    Get the current trend direction.

    Returns:
        "UP", "DOWN", or "NEUTRAL"
    """
    if len(candles) < 30:
        return "NEUTRAL"

    close = candles["close"]
    ema_fast = ema(close, EMA_FAST)
    ema_slow = ema(close, EMA_SLOW)

    fast_val = ema_fast.iloc[-1]
    slow_val = ema_slow.iloc[-1]

    if np.isnan(fast_val) or np.isnan(slow_val):
        return "NEUTRAL"

    if fast_val > slow_val:
        return "UP"
    elif fast_val < slow_val:
        return "DOWN"

    return "NEUTRAL"


def is_good_trading_time(candle_time: time) -> bool:
    """
    Check if current time is suitable for breakout entries.

    Skips midday chop (11:30 - 13:30 IST) where breakouts fail most.

    Args:
        candle_time: Time of the current candle

    Returns:
        True if good time to trade
    """
    # Skip midday chop
    if CHOP_START <= candle_time <= CHOP_END:
        return False

    return True


def should_trade_breakout(
    candles: pd.DataFrame,
    candle_time: time,
    setup_direction: str,
) -> tuple[bool, str]:
    """
    Full regime check: should we take this breakout?

    Args:
        candles: Recent OHLCV data
        candle_time: Time of the setup candle
        setup_direction: "LONG" or "SHORT"

    Returns:
        (should_trade, reason)
    """
    # Time filter
    if not is_good_trading_time(candle_time):
        return False, "midday_chop"

    # Regime filter
    if not is_trending(candles):
        return False, "not_trending"

    # Direction alignment: breakout direction should match trend
    trend = get_trend_direction(candles)

    if setup_direction == "LONG" and trend == "DOWN":
        return False, "against_trend"

    if setup_direction == "SHORT" and trend == "UP":
        return False, "against_trend"

    return True, "regime_ok"
