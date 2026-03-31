"""
Market Regime Classifier — 3-state regime detection.

States:
  BULL:    Uptrend confirmed — both engines active
  NEUTRAL: Mixed signals — reversal only, reduced size
  WEAK:    Downtrend — cash, no trading

Uses 3 signals:
  1. Trend: NIFTY vs 50-DMA
  2. Momentum: 5-day return
  3. Breadth: % of stocks above their 20-DMA

Plus daily override for intraday protection.
Requires 2-day persistence before switching state.
"""

from datetime import date
from enum import Enum
from pathlib import Path

import numpy as np
import pandas as pd

from backend.core.logger import get_logger

logger = get_logger(__name__)

# Regime classification thresholds
DAILY_OVERRIDE_THRESHOLD = -0.005   # Force WEAK if NIFTY down > 0.5% today
MOMENTUM_WEAK_THRESHOLD = -0.01     # 5-day return considered bearish
BREADTH_STRONG_THRESHOLD = 0.55     # % of stocks above 20-DMA for bullish breadth
BREADTH_WEAK_THRESHOLD = 0.35       # % below this = bearish breadth
REGIME_BULL_SCORE = 2               # Score >= this = BULL
REGIME_WEAK_SCORE = -2              # Score <= this = WEAK


class Regime(str, Enum):
    BULL = "BULL"
    NEUTRAL = "NEUTRAL"
    WEAK = "WEAK"


class RegimeClassifier:
    """
    3-state market regime classifier.

    Combines trend + momentum + breadth for robust regime detection.
    Requires 2-day persistence before changing state (anti-whipsaw).
    """

    def __init__(self):
        self._current_regime: Regime = Regime.NEUTRAL
        self._pending_regime: Regime | None = None
        self._pending_days: int = 0
        self._persistence_required: int = 2  # Days before regime switch

    def classify(
        self,
        nifty_close: float,
        nifty_dma_50: float,
        nifty_ret_5d: float,
        nifty_ret_1d: float,
        breadth_pct: float,  # % of stocks above their 20-DMA (0-1)
    ) -> Regime:
        """
        Classify current market regime.

        Args:
            nifty_close: Current NIFTY close
            nifty_dma_50: NIFTY 50-day moving average
            nifty_ret_5d: NIFTY 5-day return (decimal)
            nifty_ret_1d: NIFTY 1-day return (decimal, for daily override)
            breadth_pct: Fraction of stocks above 20-DMA (0-1)

        Returns:
            Regime enum (BULL, NEUTRAL, WEAK)
        """
        # Daily override: force WEAK if market crashing today
        if nifty_ret_1d < DAILY_OVERRIDE_THRESHOLD:
            self._current_regime = Regime.WEAK
            self._pending_regime = None
            self._pending_days = 0
            return Regime.WEAK

        # Compute raw regime from 3 signals
        trend_bullish = nifty_close > nifty_dma_50
        momentum_positive = nifty_ret_5d > 0
        momentum_weak = nifty_ret_5d < MOMENTUM_WEAK_THRESHOLD
        breadth_strong = breadth_pct > BREADTH_STRONG_THRESHOLD
        breadth_weak = breadth_pct < BREADTH_WEAK_THRESHOLD

        # Score: +1 for bullish signals, -1 for bearish
        score = 0
        if trend_bullish:
            score += 1
        else:
            score -= 1

        if momentum_positive:
            score += 1
        elif momentum_weak:
            score -= 1

        if breadth_strong:
            score += 1
        elif breadth_weak:
            score -= 1

        # Map score to regime
        if score >= REGIME_BULL_SCORE:
            raw_regime = Regime.BULL
        elif score <= REGIME_WEAK_SCORE:
            raw_regime = Regime.WEAK
        else:
            raw_regime = Regime.NEUTRAL

        # Persistence filter: require 2 days of same signal before switching
        if raw_regime != self._current_regime:
            if raw_regime == self._pending_regime:
                self._pending_days += 1
            else:
                self._pending_regime = raw_regime
                self._pending_days = 1

            if self._pending_days >= self._persistence_required:
                old = self._current_regime
                self._current_regime = raw_regime
                self._pending_regime = None
                self._pending_days = 0
                logger.info(f"Regime changed: {old} → {raw_regime}")

                # Persist regime change to database
                try:
                    from backend.db.persist import persist_regime_change
                    persist_regime_change(
                        today=date.today(),
                        old_regime=old.value,
                        new_regime=raw_regime.value,
                        nifty_close=nifty_close,
                        nifty_ret_5d=nifty_ret_5d,
                        nifty_ret_1d=nifty_ret_1d,
                        breadth_pct=breadth_pct,
                        score=score,
                        trigger="persistence",
                    )
                except Exception:
                    pass  # Non-critical
        else:
            self._pending_regime = None
            self._pending_days = 0

        return self._current_regime

    def classify_from_data(
        self,
        nifty_df: pd.DataFrame,
        stock_prices: pd.DataFrame,
        target_date: date,
    ) -> Regime:
        """
        Classify regime using historical DataFrames.

        Args:
            nifty_df: NIFTY daily data with 'close' column, date-indexed
            stock_prices: Price panel (date × symbol), for breadth
            target_date: Date to classify
        """
        if target_date not in nifty_df.index:
            return self._current_regime

        row = nifty_df.loc[target_date]
        close = row["close"]

        # 50-DMA
        nifty_close_series = nifty_df.loc[:target_date, "close"]
        dma_50 = nifty_close_series.rolling(50, min_periods=30).mean().iloc[-1]

        # Returns
        if len(nifty_close_series) >= 5:
            ret_5d = (close - nifty_close_series.iloc[-5]) / nifty_close_series.iloc[-5]
        else:
            ret_5d = 0

        if len(nifty_close_series) >= 2:
            ret_1d = (close - nifty_close_series.iloc[-2]) / nifty_close_series.iloc[-2]
        else:
            ret_1d = 0

        # Breadth: % of stocks above their 20-DMA
        breadth = 0.5  # Default
        if target_date in stock_prices.index:
            above_20dma = 0
            total = 0
            for sym in stock_prices.columns:
                prices = stock_prices.loc[:target_date, sym].dropna()
                if len(prices) >= 20:
                    dma20 = prices.rolling(20).mean().iloc[-1]
                    total += 1
                    if prices.iloc[-1] > dma20:
                        above_20dma += 1

            if total > 10:
                breadth = above_20dma / total

        return self.classify(close, dma_50, ret_5d, ret_1d, breadth)

    @property
    def current_regime(self) -> Regime:
        return self._current_regime

    def reset(self):
        self._current_regime = Regime.NEUTRAL
        self._pending_regime = None
        self._pending_days = 0

    def get_status(self) -> dict:
        return {
            "regime": self._current_regime.value,
            "pending": self._pending_regime.value if self._pending_regime else None,
            "pending_days": self._pending_days,
        }
