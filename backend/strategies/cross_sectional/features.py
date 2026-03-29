"""
Feature Engine for Cross-Sectional Return Prediction.

Computes features for ALL stocks at each 5-min bar.
Designed for ranking stocks by predicted forward return.

Features (25 total):
  - Lagged returns (5): 1, 2, 3, 5, 10 candle returns
  - Cross-sectional rank (2): return rank + volume rank vs universe
  - Market context (4): NIFTY return, relative strength, market ADX, trend
  - Technical (7): RSI, MACD, ATR, volatility, volume spike, momentum, bollinger
  - Time (3): minute_of_day, day_of_week, is_first_hour
  - Price structure (4): VWAP distance, range position, EMA ratio, distance from day high/low
"""

import numpy as np
import pandas as pd

from backend.core.indicators import (
    rsi, macd, ema, bollinger_position, adx, atr,
    momentum, volatility, volume_spike,
)
from backend.core.logger import get_logger

logger = get_logger(__name__)

FEATURE_COLUMNS = [
    # Lagged returns
    "ret_1", "ret_2", "ret_3", "ret_5", "ret_10",
    # Cross-sectional
    "ret_5_rank", "volume_rank",
    # Market context
    "nifty_ret_5", "relative_strength", "market_adx", "market_trend",
    # Technical
    "rsi", "macd_norm", "atr_pct", "volatility_20", "vol_spike", "momentum_10", "boll_pos",
    # Time
    "minute_of_day", "day_of_week", "is_first_hour",
    # Price structure
    "vwap_distance", "range_pos_20", "ema_ratio", "dist_from_day_high",
]


def compute_stock_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute per-stock features from 5-min OHLCV data.
    These are features that don't need cross-sectional context.

    Args:
        df: DataFrame with columns [timestamp, open, high, low, close, volume]

    Returns:
        DataFrame with added feature columns
    """
    df = df.copy()
    close = df["close"]
    high = df["high"]
    low = df["low"]
    vol = df["volume"]

    # Lagged returns (percentage)
    df["ret_1"] = close.pct_change(1)
    df["ret_2"] = close.pct_change(2)
    df["ret_3"] = close.pct_change(3)
    df["ret_5"] = close.pct_change(5)
    df["ret_10"] = close.pct_change(10)

    # Technical indicators
    df["rsi"] = rsi(close, period=14)
    macd_line, signal, histogram = macd(close)
    df["macd_norm"] = macd_line / close  # Normalize
    df["atr_pct"] = atr(high, low, close, period=14) / close
    df["volatility_20"] = volatility(close, period=20)
    df["vol_spike"] = volume_spike(vol, period=20)
    df["momentum_10"] = momentum(close, period=10)
    df["boll_pos"] = bollinger_position(close, period=20)

    # Price structure
    typical_price = (high + low + close) / 3
    cumulative_tp_vol = (typical_price * vol).rolling(20, min_periods=5).sum()
    cumulative_vol = vol.rolling(20, min_periods=5).sum()
    vwap = cumulative_tp_vol / cumulative_vol.replace(0, 1)
    df["vwap_distance"] = (close - vwap) / vwap

    df["range_pos_20"] = (close - low.rolling(20, min_periods=5).min()) / (
        high.rolling(20, min_periods=5).max() - low.rolling(20, min_periods=5).min()
    ).replace(0, 1)

    df["ema_ratio"] = close / ema(close, 20)

    # Distance from today's high (intraday)
    df["date"] = df["timestamp"].dt.date
    day_high = df.groupby("date")["high"].transform("cummax")
    df["dist_from_day_high"] = (close - day_high) / day_high
    df.drop(columns=["date"], inplace=True)

    # Time features
    df["minute_of_day"] = df["timestamp"].dt.hour * 60 + df["timestamp"].dt.minute
    df["day_of_week"] = df["timestamp"].dt.dayofweek
    df["is_first_hour"] = (df["timestamp"].dt.hour == 9).astype(int)

    return df


def compute_cross_sectional_features(
    all_stock_features: dict[str, pd.DataFrame],
    nifty_df: pd.DataFrame,
    timestamp: pd.Timestamp,
) -> dict[str, dict]:
    """
    Compute cross-sectional features at a single timestamp.
    Ranks stocks relative to each other.

    Args:
        all_stock_features: Dict mapping symbol to its feature DataFrame
        nifty_df: NIFTY 50 index data with features
        timestamp: Current timestamp to compute features for

    Returns:
        Dict mapping symbol to complete feature dict
    """
    # Collect ret_5 and volume for all stocks at this timestamp
    stock_data = {}

    for symbol, df in all_stock_features.items():
        row = df[df["timestamp"] == timestamp]
        if row.empty:
            continue
        row = row.iloc[-1]

        # Skip if missing critical features
        if pd.isna(row.get("ret_5", np.nan)):
            continue

        stock_data[symbol] = row

    if len(stock_data) < 5:
        return {}

    # Cross-sectional ranking
    ret_5_values = {s: r["ret_5"] for s, r in stock_data.items()}
    vol_values = {s: r["vol_spike"] for s, r in stock_data.items()}

    ret_5_series = pd.Series(ret_5_values)
    vol_series = pd.Series(vol_values)

    ret_5_ranks = ret_5_series.rank(pct=True)  # 0 to 1
    vol_ranks = vol_series.rank(pct=True)

    # NIFTY context
    nifty_row = nifty_df[nifty_df["timestamp"] == timestamp]
    if nifty_row.empty:
        # Try nearest
        nifty_row = nifty_df[nifty_df["timestamp"] <= timestamp].tail(1)

    nifty_ret_5 = nifty_row.iloc[-1]["ret_5"] if not nifty_row.empty else 0
    nifty_adx = nifty_row.iloc[-1].get("adx_val", 0) if not nifty_row.empty else 0
    nifty_trend = nifty_row.iloc[-1].get("trend", 0) if not nifty_row.empty else 0

    # Build feature dicts
    result = {}
    for symbol, row in stock_data.items():
        features = {}

        # Lagged returns
        for col in ["ret_1", "ret_2", "ret_3", "ret_5", "ret_10"]:
            features[col] = float(row.get(col, 0))

        # Cross-sectional
        features["ret_5_rank"] = float(ret_5_ranks.get(symbol, 0.5))
        features["volume_rank"] = float(vol_ranks.get(symbol, 0.5))

        # Market context
        features["nifty_ret_5"] = float(nifty_ret_5)
        features["relative_strength"] = features["ret_5"] - float(nifty_ret_5)
        features["market_adx"] = float(nifty_adx)
        features["market_trend"] = float(nifty_trend)

        # Technical
        for col in ["rsi", "macd_norm", "atr_pct", "volatility_20", "vol_spike", "momentum_10", "boll_pos"]:
            features[col] = float(row.get(col, 0))

        # Time
        features["minute_of_day"] = int(row.get("minute_of_day", 600))
        features["day_of_week"] = int(row.get("day_of_week", 0))
        features["is_first_hour"] = int(row.get("is_first_hour", 0))

        # Price structure
        for col in ["vwap_distance", "range_pos_20", "ema_ratio", "dist_from_day_high"]:
            features[col] = float(row.get(col, 0))

        result[symbol] = features

    return result


def prepare_nifty_features(nifty_df: pd.DataFrame) -> pd.DataFrame:
    """Compute features on NIFTY index data."""
    df = nifty_df.copy()
    df["ret_5"] = df["close"].pct_change(5)

    high, low, close = df["high"], df["low"], df["close"]
    df["adx_val"] = adx(high, low, close, 14)

    ema20 = ema(close, 20)
    ema50 = ema(close, 50)
    df["trend"] = np.where(ema20 > ema50, 1, np.where(ema20 < ema50, -1, 0))

    return df
