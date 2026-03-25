"""
Technical indicator calculations.
All functions take pandas Series/DataFrame and return computed values.
"""

import numpy as np
import pandas as pd


def sma(series: pd.Series, period: int) -> pd.Series:
    """Simple Moving Average."""
    return series.rolling(window=period).mean()


def ema(series: pd.Series, period: int) -> pd.Series:
    """Exponential Moving Average."""
    return series.ewm(span=period, adjust=False).mean()


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """
    Relative Strength Index.
    Returns values 0-100. >70 = overbought, <30 = oversold.
    """
    delta = close.diff()
    gain = delta.where(delta > 0, 0)
    loss = (-delta).where(delta < 0, 0)

    avg_gain = gain.ewm(span=period, adjust=False).mean()
    avg_loss = loss.ewm(span=period, adjust=False).mean()

    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> tuple[pd.Series, pd.Series, pd.Series]:
    """
    MACD (Moving Average Convergence Divergence).
    Returns: (macd_line, signal_line, histogram)
    """
    ema_fast = ema(close, fast)
    ema_slow = ema(close, slow)
    macd_line = ema_fast - ema_slow
    signal_line = ema(macd_line, signal)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def bollinger_bands(close: pd.Series, period: int = 20, std_dev: float = 2.0) -> tuple[pd.Series, pd.Series, pd.Series]:
    """
    Bollinger Bands.
    Returns: (upper_band, middle_band, lower_band)
    """
    middle = sma(close, period)
    std = close.rolling(window=period).std()
    upper = middle + (std * std_dev)
    lower = middle - (std * std_dev)
    return upper, middle, lower


def bollinger_position(close: pd.Series, period: int = 20, std_dev: float = 2.0) -> pd.Series:
    """
    Position within Bollinger Bands.
    Returns -1 (at lower) to +1 (at upper), 0 = at middle.
    """
    upper, middle, lower = bollinger_bands(close, period, std_dev)
    position = (close - lower) / (upper - lower) * 2 - 1
    return position.clip(-1, 1)


def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """
    Average True Range - measures volatility.
    """
    tr1 = high - low
    tr2 = (high - close.shift()).abs()
    tr3 = (low - close.shift()).abs()
    true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return true_range.ewm(span=period, adjust=False).mean()


def adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """
    Average Directional Index - measures trend strength.
    >25 = trending, <20 = ranging.
    """
    plus_dm = high.diff()
    minus_dm = -low.diff()

    plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0)

    atr_val = atr(high, low, close, period)

    plus_di = 100 * ema(plus_dm, period) / atr_val
    minus_di = 100 * ema(minus_dm, period) / atr_val

    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di)
    return ema(dx, period)


def momentum(close: pd.Series, period: int = 10) -> pd.Series:
    """
    Price momentum - percentage change over period.
    """
    return (close - close.shift(period)) / close.shift(period)


def volatility(close: pd.Series, period: int = 20) -> pd.Series:
    """
    Volatility - standard deviation of returns.
    """
    returns = close.pct_change()
    return returns.rolling(window=period).std()


def volume_spike(volume: pd.Series, period: int = 20) -> pd.Series:
    """
    Volume spike - current volume vs average volume.
    >1 = above average, <1 = below average.
    """
    avg_volume = sma(volume, period)
    return volume / avg_volume


def price_acceleration(close: pd.Series, period: int = 5) -> pd.Series:
    """
    Price acceleration - second derivative of price (rate of change of momentum).
    """
    momentum_val = momentum(close, period)
    return momentum_val.diff()


def range_position(close: pd.Series, period: int = 50) -> pd.Series:
    """
    Position within the high-low range over period.
    Returns 0 (at low) to 1 (at high).
    """
    highest = close.rolling(window=period).max()
    lowest = close.rolling(window=period).min()
    position = (close - lowest) / (highest - lowest)
    return position.clip(0, 1)


def volatility_regime(close: pd.Series, period: int = 20, lookback: int = 100) -> pd.Series:
    """
    Volatility regime - percentile of current volatility vs historical.
    Returns 0-1 (0 = low vol, 1 = high vol).
    """
    vol = volatility(close, period)
    return vol.rolling(window=lookback).apply(
        lambda x: pd.Series(x).rank(pct=True).iloc[-1] if len(x) == lookback else np.nan
    )


def trend_direction(close: pd.Series, fast: int = 10, slow: int = 30) -> pd.Series:
    """
    Trend direction based on EMA crossover.
    Returns: 1 (bullish), -1 (bearish), 0 (neutral)
    """
    ema_fast = ema(close, fast)
    ema_slow = ema(close, slow)
    diff_pct = (ema_fast - ema_slow) / ema_slow

    direction = pd.Series(0, index=close.index)
    direction = direction.where(diff_pct.abs() < 0.001, np.sign(diff_pct))
    return direction.astype(int)
