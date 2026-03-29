"""
Mean Reversion Detector v2 — Extreme overextension + reversal confirmation.

v1 mistake: entered at peak extension (Phase 1)
v2 fix: wait for exhaustion + reversal candle (Phase 2→3 transition)

Entry requires ALL of:
  1. VWAP distance in top 5% of recent history (extreme overextension)
  2. RSI at extreme (< 25 or > 75)
  3. Reversal candle confirmed (opposite direction candle after extreme)
  4. Not in first 30 minutes (opening noise)
"""

from dataclasses import dataclass
from datetime import time as dtime
from typing import Literal

import numpy as np
import pandas as pd

from backend.core.logger import get_logger

logger = get_logger(__name__)


@dataclass
class MeanRevSetup:
    """A confirmed mean-reversion setup."""
    symbol: str
    direction: Literal["LONG", "SHORT"]
    entry_price: float          # Price at reversal candle close
    extension_price: float      # Price at peak extension (previous candle)
    vwap: float
    vwap_distance_pct: float
    vwap_distance_percentile: float  # Percentile vs recent history
    rsi: float
    atr: float
    reversal_strength: float    # How strong the reversal candle was
    timestamp: pd.Timestamp

    @property
    def quality_score(self) -> float:
        """Setup quality — higher = better opportunity."""
        score = 0.0

        # Extremity of overextension (main driver)
        score += min(self.vwap_distance_percentile, 1.0) * 40  # 0-40

        # RSI extremity
        if self.direction == "LONG":
            score += max(0, 25 - self.rsi) * 1.0  # RSI below 25 = bonus
        else:
            score += max(0, self.rsi - 75) * 1.0  # RSI above 75 = bonus

        # Reversal candle strength
        score += min(self.reversal_strength, 1.0) * 20  # 0-20

        return score


class MeanRevDetectorV2:
    """
    Detects extreme overextension + reversal confirmation.

    Two-candle pattern:
      Candle N:   Extreme move (far from VWAP, RSI extreme)
      Candle N+1: Reversal (opposite direction, confirms exhaustion)
      → Enter at Candle N+1 close

    Only triggers on top 5% most extreme VWAP distances.
    """

    # Time boundaries
    EARLIEST_ENTRY = dtime(9, 45)    # Skip first 30 min
    LATEST_ENTRY = dtime(14, 30)     # Leave room for holding

    # Overextension thresholds
    VWAP_PERCENTILE_MIN = 0.95       # Top 5% of VWAP distances
    RSI_OVERSOLD = 25                # Stricter than v1 (was 35)
    RSI_OVERBOUGHT = 75              # Stricter than v1 (was 65)
    VWAP_LOOKBACK = 100              # Candles to compute percentile over

    # Reversal confirmation
    MIN_REVERSAL_BODY_RATIO = 0.4    # Reversal candle body > 40% of range

    def scan(
        self,
        symbol: str,
        candles: pd.DataFrame,
    ) -> list[MeanRevSetup]:
        """
        Scan for mean-reversion setups.

        Requires at least 50 candles for indicator warmup + percentile computation.

        Returns:
            List of setups (0 or 1 per scan)
        """
        if len(candles) < 50:
            return []

        candles = candles.copy()
        close = candles["close"]
        high = candles["high"]
        low = candles["low"]
        volume = candles["volume"]
        open_price = candles["open"]

        # RSI
        delta = close.diff()
        gain = delta.where(delta > 0, 0).rolling(14, min_periods=5).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14, min_periods=5).mean()
        rs = gain / loss.replace(0, 1)
        candles["rsi"] = 100 - (100 / (1 + rs))

        # ATR
        tr = pd.concat([
            high - low,
            abs(high - close.shift(1)),
            abs(low - close.shift(1)),
        ], axis=1).max(axis=1)
        candles["atr"] = tr.rolling(14, min_periods=5).mean()

        # VWAP (rolling 20-period)
        typical = (high + low + close) / 3
        cum_tp_vol = (typical * volume).rolling(20, min_periods=5).sum()
        cum_vol = volume.rolling(20, min_periods=5).sum()
        candles["vwap"] = cum_tp_vol / cum_vol.replace(0, 1)
        candles["vwap_dist"] = (close - candles["vwap"]) / candles["vwap"]
        candles["vwap_dist_abs"] = candles["vwap_dist"].abs()

        # Rolling percentile of VWAP distance (how extreme is this vs recent history?)
        candles["vwap_pctile"] = candles["vwap_dist_abs"].rolling(
            self.VWAP_LOOKBACK, min_periods=30
        ).rank(pct=True)

        # Candle body ratio
        candle_range = (high - low).replace(0, 1)
        candles["body_ratio"] = abs(close - open_price) / candle_range

        # Check last TWO candles: N-1 = extension, N = reversal
        if len(candles) < 3:
            return []

        prev = candles.iloc[-2]  # Extension candle
        curr = candles.iloc[-1]  # Potential reversal candle

        ts = curr["timestamp"]
        if not hasattr(ts, "time"):
            return []

        candle_time = ts.time()

        # Time filter
        if candle_time < self.EARLIEST_ENTRY or candle_time > self.LATEST_ENTRY:
            return []

        # Check if previous candle was extremely overextended
        if pd.isna(prev["vwap_pctile"]) or prev["vwap_pctile"] < self.VWAP_PERCENTILE_MIN:
            return []

        prev_rsi = prev["rsi"]
        prev_vwap_dist = prev["vwap_dist"]

        if pd.isna(prev_rsi):
            return []

        setups = []

        # LONG setup: previous candle was extreme BELOW VWAP, current reverses UP
        if (prev_vwap_dist < 0
                and prev_rsi < self.RSI_OVERSOLD
                and curr["close"] > curr["open"]               # Bullish reversal candle
                and curr["body_ratio"] >= self.MIN_REVERSAL_BODY_RATIO
                and curr["close"] > prev["close"]):            # Actually reversed

            reversal_strength = (curr["close"] - prev["close"]) / candles["atr"].iloc[-1] if candles["atr"].iloc[-1] > 0 else 0

            setups.append(MeanRevSetup(
                symbol=symbol,
                direction="LONG",
                entry_price=curr["close"],
                extension_price=prev["close"],
                vwap=curr["vwap"],
                vwap_distance_pct=prev_vwap_dist,
                vwap_distance_percentile=prev["vwap_pctile"],
                rsi=prev_rsi,
                atr=candles["atr"].iloc[-1],
                reversal_strength=abs(reversal_strength),
                timestamp=ts,
            ))

        # SHORT setup: previous candle was extreme ABOVE VWAP, current reverses DOWN
        elif (prev_vwap_dist > 0
                and prev_rsi > self.RSI_OVERBOUGHT
                and curr["close"] < curr["open"]               # Bearish reversal candle
                and curr["body_ratio"] >= self.MIN_REVERSAL_BODY_RATIO
                and curr["close"] < prev["close"]):            # Actually reversed

            reversal_strength = (prev["close"] - curr["close"]) / candles["atr"].iloc[-1] if candles["atr"].iloc[-1] > 0 else 0

            setups.append(MeanRevSetup(
                symbol=symbol,
                direction="SHORT",
                entry_price=curr["close"],
                extension_price=prev["close"],
                vwap=curr["vwap"],
                vwap_distance_pct=prev_vwap_dist,
                vwap_distance_percentile=prev["vwap_pctile"],
                rsi=prev_rsi,
                atr=candles["atr"].iloc[-1],
                reversal_strength=abs(reversal_strength),
                timestamp=ts,
            ))

        return setups
