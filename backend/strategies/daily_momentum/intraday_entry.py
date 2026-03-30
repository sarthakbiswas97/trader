"""
Intraday Entry Filter for Daily Reversal Picks.

Uses daily reversal signal for DIRECTION, intraday for TIMING.
Entry only when stock confirms buying pressure (MIS leverage).

Rules:
  1. Stock must be in today's reversal picks (daily signal)
  2. Wait for first 15 min (let opening noise settle)
  3. Enter when: price crosses above VWAP OR holds above 15-min low
  4. Exit: end of day (MIS auto square-off) or trailing stop

This is NOT an independent intraday strategy.
It's an execution optimizer for the proven daily signal.
"""

from dataclasses import dataclass
from datetime import datetime, time as dtime

import pandas as pd

from backend.core.logger import get_logger

logger = get_logger(__name__)


@dataclass
class IntradaySignal:
    """An intraday entry signal for a reversal pick."""
    symbol: str
    direction: str  # Always "LONG" for reversal picks
    entry_price: float
    trigger: str    # "vwap_cross" or "low_hold" or "reversal_candle"
    vwap: float
    day_low: float
    day_high: float
    opening_range_low: float
    timestamp: datetime


class IntradayEntryFilter:
    """
    Filters daily reversal picks for intraday entry timing.

    Monitors 5-min candles and triggers entry when confirmation appears.
    """

    EARLIEST_ENTRY = dtime(9, 30)   # After opening range forms
    LATEST_ENTRY = dtime(14, 30)    # Leave time for exit
    EXIT_TIME = dtime(15, 10)       # Exit before MIS cutoff (3:20)

    def __init__(self, reversal_picks: list[str]):
        """
        Args:
            reversal_picks: List of symbols from daily reversal (today's losers to buy)
        """
        self.picks = set(reversal_picks)
        self.opening_range: dict[str, dict] = {}  # symbol → {high, low}
        self.vwap_data: dict[str, dict] = {}       # symbol → {cum_tp_vol, cum_vol}
        self.triggered: dict[str, IntradaySignal] = {}  # symbol → signal
        self.candle_count: dict[str, int] = {}

        logger.info(f"IntradayEntryFilter: watching {len(self.picks)} stocks")

    def process_candle(self, symbol: str, candle: dict) -> IntradaySignal | None:
        """
        Process a 5-min candle for a reversal pick.

        Args:
            candle: dict with keys: timestamp, open, high, low, close, volume

        Returns:
            IntradaySignal if entry triggered, None otherwise
        """
        if symbol not in self.picks:
            return None

        if symbol in self.triggered:
            return None  # Already triggered today

        ts = candle.get("timestamp")
        if isinstance(ts, str):
            ts = pd.to_datetime(ts)

        candle_time = ts.time() if hasattr(ts, "time") else dtime(10, 0)

        # Track candle count
        self.candle_count[symbol] = self.candle_count.get(symbol, 0) + 1

        # Build opening range (first 3 candles = 15 min)
        if self.candle_count[symbol] <= 3:
            if symbol not in self.opening_range:
                self.opening_range[symbol] = {
                    "high": candle["high"],
                    "low": candle["low"],
                    "open": candle["open"],
                }
            else:
                self.opening_range[symbol]["high"] = max(
                    self.opening_range[symbol]["high"], candle["high"]
                )
                self.opening_range[symbol]["low"] = min(
                    self.opening_range[symbol]["low"], candle["low"]
                )
            return None  # Don't enter during opening range

        # Too late for entry
        if candle_time > self.LATEST_ENTRY:
            return None

        # Update VWAP
        typical_price = (candle["high"] + candle["low"] + candle["close"]) / 3
        vol = candle["volume"]

        if symbol not in self.vwap_data:
            self.vwap_data[symbol] = {"cum_tp_vol": 0, "cum_vol": 0}

        self.vwap_data[symbol]["cum_tp_vol"] += typical_price * vol
        self.vwap_data[symbol]["cum_vol"] += vol

        cum_vol = self.vwap_data[symbol]["cum_vol"]
        vwap = self.vwap_data[symbol]["cum_tp_vol"] / cum_vol if cum_vol > 0 else candle["close"]

        or_data = self.opening_range.get(symbol, {})
        or_low = or_data.get("low", candle["low"])

        close = candle["close"]
        open_p = candle["open"]

        # === ENTRY TRIGGERS ===

        # Trigger 1: VWAP Cross — price crosses above VWAP
        if close > vwap and open_p <= vwap:
            signal = IntradaySignal(
                symbol=symbol,
                direction="LONG",
                entry_price=close,
                trigger="vwap_cross",
                vwap=vwap,
                day_low=or_low,
                day_high=or_data.get("high", candle["high"]),
                opening_range_low=or_low,
                timestamp=ts,
            )
            self.triggered[symbol] = signal
            logger.info(f"ENTRY: {symbol} @ ₹{close:.2f} (VWAP cross, VWAP={vwap:.2f})")
            return signal

        # Trigger 2: Low Hold — price holds above opening range low + bullish candle
        if (close > or_low
                and close > open_p  # Bullish candle
                and candle["low"] > or_low * 0.998  # Didn't breach OR low
                and self.candle_count[symbol] >= 6):  # After 30 min

            signal = IntradaySignal(
                symbol=symbol,
                direction="LONG",
                entry_price=close,
                trigger="low_hold",
                vwap=vwap,
                day_low=or_low,
                day_high=or_data.get("high", candle["high"]),
                opening_range_low=or_low,
                timestamp=ts,
            )
            self.triggered[symbol] = signal
            logger.info(f"ENTRY: {symbol} @ ₹{close:.2f} (low hold, OR low={or_low:.2f})")
            return signal

        return None

    def get_status(self) -> dict:
        """Get current filter status."""
        return {
            "watching": list(self.picks),
            "triggered": {s: {
                "price": sig.entry_price,
                "trigger": sig.trigger,
                "time": str(sig.timestamp),
            } for s, sig in self.triggered.items()},
            "pending": [s for s in self.picks if s not in self.triggered],
            "opening_ranges": self.opening_range,
        }

    def print_status(self) -> None:
        """Print current status."""
        status = self.get_status()
        print(f"\n  Intraday Entry Filter:")
        print(f"    Watching: {len(status['watching'])} stocks")
        print(f"    Triggered: {len(status['triggered'])}")
        print(f"    Pending: {len(status['pending'])}")

        if status["triggered"]:
            print(f"\n    Entries:")
            for sym, info in status["triggered"].items():
                print(f"      {sym:>12} @ ₹{info['price']:,.2f} ({info['trigger']}) at {info['time']}")

        if status["pending"]:
            print(f"\n    Still waiting:")
            for sym in status["pending"][:5]:
                or_data = status["opening_ranges"].get(sym, {})
                if or_data:
                    print(f"      {sym:>12} OR: ₹{or_data.get('low', 0):,.2f} - ₹{or_data.get('high', 0):,.2f}")
