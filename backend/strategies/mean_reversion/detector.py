"""
Mean Reversion Detector — Finds overextended stocks likely to revert.

Signals:
  LONG (buy dip): Stock dropped significantly, RSI oversold, far below VWAP
  SHORT (sell rip): Stock rallied significantly, RSI overbought, far above VWAP

Based on empirical IC analysis:
  - atr_pct IC = -0.046 (high volatility → negative forward return)
  - is_first_hour IC = -0.046 (first hour moves reverse)
  - vwap_distance IC = +0.010 (far from VWAP → reverts)
"""

from dataclasses import dataclass
from datetime import time as dtime
from typing import Literal

import numpy as np
import pandas as pd

from backend.core.logger import get_logger

logger = get_logger(__name__)


@dataclass
class MeanReversionSetup:
    """A detected mean-reversion opportunity."""
    symbol: str
    direction: Literal["LONG", "SHORT"]  # LONG = buy the dip, SHORT = sell the rip
    trigger_price: float
    vwap: float
    vwap_distance_pct: float  # How far from VWAP (%)
    rsi: float
    atr_pct: float
    recent_move_pct: float    # Move in last N candles that created the overextension
    volume_ratio: float
    timestamp: pd.Timestamp

    @property
    def overextension_score(self) -> float:
        """How overextended is the stock? Higher = more likely to revert."""
        score = 0.0
        # VWAP distance (most important)
        score += min(abs(self.vwap_distance_pct) * 100, 5) * 10  # 0-50

        # RSI extremity
        if self.direction == "LONG":
            score += max(0, 30 - self.rsi) * 0.5  # RSI below 30 = bonus
        else:
            score += max(0, self.rsi - 70) * 0.5  # RSI above 70 = bonus

        # ATR expansion (volatility)
        score += min(self.atr_pct * 1000, 3) * 5  # 0-15

        # Volume confirmation
        if self.volume_ratio > 1.5:
            score += 10

        return score


class MeanReversionDetector:
    """
    Detects overextended stocks likely to mean-revert.

    Logic:
      LONG (buy dip):
        - Price significantly below VWAP (> 0.3%)
        - RSI < 35 (oversold)
        - Recent move was sharp downward
        - NOT in first 10 minutes (opening noise)

      SHORT (sell rip):
        - Price significantly above VWAP (> 0.3%)
        - RSI > 65 (overbought)
        - Recent move was sharp upward
        - NOT in first 10 minutes
    """

    # Parameters
    VWAP_THRESHOLD = 0.003     # 0.3% from VWAP minimum
    RSI_OVERSOLD = 35
    RSI_OVERBOUGHT = 65
    MIN_MOVE_PCT = 0.003       # Recent move must be > 0.3%
    SKIP_FIRST_MINUTES = 15    # Skip first 15 min (9:15-9:30)
    LAST_ENTRY = dtime(14, 30) # No entries after 2:30 PM
    RSI_PERIOD = 14
    ATR_PERIOD = 14
    VWAP_PERIOD = 20

    def scan(
        self,
        symbol: str,
        candles: pd.DataFrame,
    ) -> list[MeanReversionSetup]:
        """
        Scan one stock's candles for mean-reversion setups.

        Args:
            symbol: Trading symbol
            candles: 5-min OHLCV data (needs at least 30 rows)

        Returns:
            List of detected setups (typically 0-1 per scan)
        """
        if len(candles) < 30:
            return []

        candles = candles.copy()
        close = candles["close"]
        high = candles["high"]
        low = candles["low"]
        volume = candles["volume"]

        # Compute indicators
        # RSI
        delta = close.diff()
        gain = delta.where(delta > 0, 0).rolling(self.RSI_PERIOD, min_periods=5).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(self.RSI_PERIOD, min_periods=5).mean()
        rs = gain / loss.replace(0, 1)
        candles["rsi"] = 100 - (100 / (1 + rs))

        # ATR
        tr = pd.concat([
            high - low,
            abs(high - close.shift(1)),
            abs(low - close.shift(1)),
        ], axis=1).max(axis=1)
        candles["atr"] = tr.rolling(self.ATR_PERIOD, min_periods=5).mean()
        candles["atr_pct"] = candles["atr"] / close

        # VWAP (rolling)
        typical = (high + low + close) / 3
        cum_tp_vol = (typical * volume).rolling(self.VWAP_PERIOD, min_periods=5).sum()
        cum_vol = volume.rolling(self.VWAP_PERIOD, min_periods=5).sum()
        candles["vwap"] = cum_tp_vol / cum_vol.replace(0, 1)
        candles["vwap_dist"] = (close - candles["vwap"]) / candles["vwap"]

        # Recent move (5-candle return)
        candles["recent_move"] = close.pct_change(5)

        # Volume ratio
        candles["vol_avg"] = volume.rolling(20, min_periods=5).mean().fillna(volume)
        candles["vol_ratio"] = volume / candles["vol_avg"].replace(0, 1)

        setups = []

        # Check only the last candle (most recent)
        row = candles.iloc[-1]
        ts = row["timestamp"]

        if not hasattr(ts, "time"):
            return []

        candle_time = ts.time()

        # Time filters
        if candle_time < dtime(9, 30):  # Skip opening noise
            return []
        if candle_time > self.LAST_ENTRY:
            return []

        rsi_val = row["rsi"]
        vwap_dist = row["vwap_dist"]
        recent_move = row["recent_move"]
        atr_pct = row["atr_pct"]
        vol_ratio = row["vol_ratio"]

        if pd.isna(rsi_val) or pd.isna(vwap_dist):
            return []

        # LONG setup: buy the dip
        if (vwap_dist < -self.VWAP_THRESHOLD
                and rsi_val < self.RSI_OVERSOLD
                and recent_move < -self.MIN_MOVE_PCT):

            setups.append(MeanReversionSetup(
                symbol=symbol,
                direction="LONG",
                trigger_price=row["close"],
                vwap=row["vwap"],
                vwap_distance_pct=vwap_dist,
                rsi=rsi_val,
                atr_pct=atr_pct,
                recent_move_pct=recent_move,
                volume_ratio=vol_ratio,
                timestamp=ts,
            ))

        # SHORT setup: sell the rip
        elif (vwap_dist > self.VWAP_THRESHOLD
                and rsi_val > self.RSI_OVERBOUGHT
                and recent_move > self.MIN_MOVE_PCT):

            setups.append(MeanReversionSetup(
                symbol=symbol,
                direction="SHORT",
                trigger_price=row["close"],
                vwap=row["vwap"],
                vwap_distance_pct=vwap_dist,
                rsi=rsi_val,
                atr_pct=atr_pct,
                recent_move_pct=recent_move,
                volume_ratio=vol_ratio,
                timestamp=ts,
            ))

        return setups
