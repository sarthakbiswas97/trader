"""
Breakout Detector — Identifies breakout and breakdown setups.

Two setup types:
  1. Opening Breakout (9:20-9:45): Price breaks previous day high/low
  2. Intraday Breakout (after 9:45): Price breaks consolidation range

Both require volume confirmation and candle quality checks.
"""

from dataclasses import dataclass
from datetime import date, time
from math import isnan
from typing import Literal

import numpy as np
import pandas as pd

from backend.core.logger import get_logger

logger = get_logger(__name__)


@dataclass
class Setup:
    """A detected breakout/breakdown setup."""
    symbol: str
    setup_type: Literal["opening", "intraday"]
    direction: Literal["LONG", "SHORT"]
    trigger_price: float       # Price at breakout
    reference_level: float     # PDH/PDL or range high/low that was broken
    volume_ratio: float        # Current volume vs average
    candle_strength: float     # Body-to-range ratio (0-1)
    consolidation_tightness: float  # Range % before breakout (intraday only)
    timestamp: pd.Timestamp
    atr: float                 # For position sizing / stop placement

    @property
    def score(self) -> float:
        """Raw quality score (higher = better setup)."""
        score = 0.0
        vol = self.volume_ratio if not np.isnan(self.volume_ratio) else 1.0
        score += min(vol, 3.0) * 10                     # Volume: 0-30
        score += self.candle_strength * 20               # Candle quality: 0-20
        if self.setup_type == "intraday":
            score += max(0, (0.5 - self.consolidation_tightness) * 100)
        else:
            if self.reference_level > 0:
                gap_pct = abs(self.trigger_price - self.reference_level) / self.reference_level
                score += min(gap_pct * 1000, 30)
        return score


class BreakoutDetector:
    """
    Scans price data for breakout setups.

    Usage:
        detector = BreakoutDetector()
        setups = detector.scan(symbol, today_candles, prev_day_candles)
    """

    # Time boundaries
    OPENING_START = time(9, 20)   # Skip first 5 min noise
    OPENING_END = time(9, 45)     # Opening window
    INTRADAY_START = time(9, 45)  # After opening settle
    LAST_ENTRY = time(14, 45)     # No entries after 2:45 PM

    # Detection parameters
    VOLUME_SPIKE_MIN = 1.8        # Min volume vs 20-period average
    CANDLE_STRENGTH_MIN = 0.6     # Body must be >= 60% of candle range
    CONSOLIDATION_LOOKBACK = 12   # 12 candles = 1 hour for intraday range
    CONSOLIDATION_MAX_RANGE = 0.004  # Max 0.4% range for "consolidation"

    def scan(
        self,
        symbol: str,
        candles: pd.DataFrame,
        prev_day_high: float,
        prev_day_low: float,
    ) -> list[Setup]:
        """
        Scan one stock's candles for breakout setups.

        Args:
            symbol: Trading symbol
            candles: Today's 5-min OHLCV data (sorted by time)
            prev_day_high: Previous day's high price
            prev_day_low: Previous day's low price

        Returns:
            List of detected setups (typically 0-2 per stock per day)
        """
        if len(candles) < 5:
            return []

        setups = []

        # Compute rolling volume average for the whole day
        candles = candles.copy()
        candles["vol_avg"] = candles["volume"].rolling(20, min_periods=3).mean().fillna(candles["volume"])
        candles["vol_ratio"] = (candles["volume"] / candles["vol_avg"].replace(0, 1)).fillna(1.0)

        # Compute candle body strength
        candle_range = candles["high"] - candles["low"]
        candle_body = abs(candles["close"] - candles["open"])
        candles["body_strength"] = (candle_body / candle_range.replace(0, 1)).clip(0, 1)

        # Compute ATR (14-period)
        tr = pd.concat([
            candles["high"] - candles["low"],
            abs(candles["high"] - candles["close"].shift(1)),
            abs(candles["low"] - candles["close"].shift(1)),
        ], axis=1).max(axis=1)
        candles["atr"] = tr.rolling(14, min_periods=5).mean()

        found_opening = False

        for i in range(3, len(candles)):
            row = candles.iloc[i]
            ts = row["timestamp"]

            # Extract time
            if hasattr(ts, "time"):
                candle_time = ts.time()
            else:
                continue

            # Skip if too early or too late
            if candle_time < self.OPENING_START or candle_time > self.LAST_ENTRY:
                continue

            # ===== OPENING BREAKOUT (9:20 - 9:45) =====
            if candle_time <= self.OPENING_END and not found_opening:
                setup = self._check_opening_breakout(
                    symbol, row, candles.iloc[:i+1], prev_day_high, prev_day_low
                )
                if setup:
                    setups.append(setup)
                    found_opening = True  # Only one opening setup per stock

            # ===== INTRADAY BREAKOUT (after 9:45) =====
            elif candle_time >= self.INTRADAY_START:
                setup = self._check_intraday_breakout(
                    symbol, row, candles.iloc[max(0, i - self.CONSOLIDATION_LOOKBACK):i+1]
                )
                if setup:
                    setups.append(setup)
                    break  # One intraday breakout per stock is enough

        return setups

    def _check_opening_breakout(
        self,
        symbol: str,
        row: pd.Series,
        recent: pd.DataFrame,
        pdh: float,
        pdl: float,
    ) -> Setup | None:
        """Check for opening breakout above PDH or below PDL."""
        close = row["close"]
        vol_ratio = row.get("vol_ratio", 1.0)
        body_strength = row.get("body_strength", 0.5)
        atr = row.get("atr", close * 0.01)

        # Volume check
        if vol_ratio < self.VOLUME_SPIKE_MIN:
            return None

        # Candle quality
        if body_strength < self.CANDLE_STRENGTH_MIN:
            return None

        # LONG: Close clearly above previous day high (> 0.1% above)
        if close > pdh * 1.001 and row["close"] > row["open"]:
            return Setup(
                symbol=symbol,
                setup_type="opening",
                direction="LONG",
                trigger_price=close,
                reference_level=pdh,
                volume_ratio=vol_ratio,
                candle_strength=body_strength,
                consolidation_tightness=0,
                timestamp=row["timestamp"],
                atr=atr,
            )

        # SHORT: Close clearly below previous day low (> 0.1% below)
        if close < pdl * 0.999 and row["close"] < row["open"]:
            return Setup(
                symbol=symbol,
                setup_type="opening",
                direction="SHORT",
                trigger_price=close,
                reference_level=pdl,
                volume_ratio=vol_ratio,
                candle_strength=body_strength,
                consolidation_tightness=0,
                timestamp=row["timestamp"],
                atr=atr,
            )

        return None

    def _check_intraday_breakout(
        self,
        symbol: str,
        row: pd.Series,
        recent: pd.DataFrame,
    ) -> Setup | None:
        """Check for breakout from consolidation range."""
        if len(recent) < 6:
            return None

        close = row["close"]
        vol_ratio = row.get("vol_ratio", 1.0)
        body_strength = row.get("body_strength", 0.5)
        atr = row.get("atr", close * 0.01)

        # Volume check
        if vol_ratio < self.VOLUME_SPIKE_MIN:
            return None

        # Candle quality
        if body_strength < self.CANDLE_STRENGTH_MIN:
            return None

        # Calculate consolidation range (excluding current candle)
        lookback = recent.iloc[:-1]
        range_high = lookback["high"].max()
        range_low = lookback["low"].min()
        range_pct = (range_high - range_low) / close if close > 0 else 1.0

        # Must have been consolidating (tight range)
        if range_pct > self.CONSOLIDATION_MAX_RANGE:
            return None

        # LONG: Break above consolidation high
        if close > range_high and row["close"] > row["open"]:
            return Setup(
                symbol=symbol,
                setup_type="intraday",
                direction="LONG",
                trigger_price=close,
                reference_level=range_high,
                volume_ratio=vol_ratio,
                candle_strength=body_strength,
                consolidation_tightness=range_pct,
                timestamp=row["timestamp"],
                atr=atr,
            )

        # SHORT: Break below consolidation low
        if close < range_low and row["close"] < row["open"]:
            return Setup(
                symbol=symbol,
                setup_type="intraday",
                direction="SHORT",
                trigger_price=close,
                reference_level=range_low,
                volume_ratio=vol_ratio,
                candle_strength=body_strength,
                consolidation_tightness=range_pct,
                timestamp=row["timestamp"],
                atr=atr,
            )

        return None
