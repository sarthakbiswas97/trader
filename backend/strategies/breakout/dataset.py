"""
Setup Dataset Builder — Logs all detected setups with features and outcomes.

Scans historical data, detects every breakout/breakdown setup,
computes features available AT THAT TIME, and labels each with
whether TP hit before SL (binary classification).

No future leakage: features use only past data, label uses only
the forward window after the setup candle.
"""

from datetime import date, time as dtime
from pathlib import Path

import numpy as np
import pandas as pd

from backend.core.logger import get_logger
from backend.core.symbols import NIFTY_50
from backend.services.historical_data import HistoricalDataService
from backend.strategies.breakout.detector import BreakoutDetector
from backend.strategies.breakout.market_regime import MarketRegime

logger = get_logger(__name__)

_BACKEND_DIR = Path(__file__).parent.parent.parent
DATASET_PATH = _BACKEND_DIR / "data" / "training" / "setup_dataset.csv"


def build_dataset(
    symbols: list[str] = None,
    sl_atr_mult: float = 1.5,
    tp_atr_mult: float = 2.5,
    max_hold_candles: int = 24,
) -> pd.DataFrame:
    """
    Build ML training dataset from all detected setups.

    For each setup, computes:
      - Features available at detection time
      - Outcome: did TP hit before SL within max_hold candles?

    Args:
        symbols: Stocks to scan
        sl_atr_mult: Stop-loss in ATR multiples
        tp_atr_mult: Take-profit in ATR multiples
        max_hold_candles: Max forward window for outcome

    Returns:
        DataFrame with features + label
    """
    symbols = symbols or NIFTY_50
    ds = HistoricalDataService()
    detector = BreakoutDetector()
    regime = MarketRegime()
    regime.load()

    rows = []

    print("Building setup dataset...")
    print(f"  Symbols: {len(symbols)}")

    for sym_idx, symbol in enumerate(symbols):
        df = ds.load_candles(symbol, "5m")
        if df.empty or len(df) < 50:
            continue

        # Get unique trading days
        df["date"] = df["timestamp"].dt.date
        days = sorted(df["date"].unique())

        if len(days) < 2:
            continue

        for day_idx in range(1, len(days)):
            today = days[day_idx]
            yesterday = days[day_idx - 1]

            # Previous day high/low
            prev = df[df["date"] == yesterday]
            if prev.empty:
                continue
            pdh = prev["high"].max()
            pdl = prev["low"].min()

            # Today's candles
            today_df = df[df["date"] == today].copy()
            if len(today_df) < 15:
                continue

            # Get regime info for today
            regime_info = regime.get_info(today)

            # Scan with LOOSE detection for dataset building
            # Use relaxed detector to capture more setups — model will learn quality
            loose_detector = BreakoutDetector()
            loose_detector.VOLUME_SPIKE_MIN = 1.0      # Any volume above average
            loose_detector.CANDLE_STRENGTH_MIN = 0.3    # Looser candle requirement
            loose_detector.CONSOLIDATION_MAX_RANGE = 0.01  # 1% range

            # Scan at multiple points in the day
            all_setups = []
            for scan_end in [15, 30, 50]:
                if scan_end > len(today_df):
                    break
                scan_df = today_df.iloc[:scan_end]
                found = loose_detector.scan(symbol, scan_df, pdh, pdl)
                # Deduplicate by setup type
                seen = {(s.setup_type, s.direction) for s in all_setups}
                for s in found:
                    if (s.setup_type, s.direction) not in seen:
                        all_setups.append(s)
                        seen.add((s.setup_type, s.direction))

            setups = all_setups

            for setup in setups:
                # Find the candle index of the setup in today's full data
                setup_time = setup.timestamp
                future_candles = today_df[today_df["timestamp"] > setup_time]

                if len(future_candles) < 3:
                    continue

                # Compute outcome: does TP hit before SL?
                entry_price = setup.trigger_price
                atr = setup.atr if setup.atr > 0 else entry_price * 0.005
                is_short = setup.direction == "SHORT"

                if is_short:
                    sl_price = entry_price + atr * sl_atr_mult
                    tp_price = entry_price - atr * tp_atr_mult
                else:
                    sl_price = entry_price - atr * sl_atr_mult
                    tp_price = entry_price + atr * tp_atr_mult

                outcome = _compute_outcome(
                    future_candles, entry_price, sl_price, tp_price,
                    is_short, max_hold_candles,
                )

                # Compute features (ONLY from data available at setup time)
                candle_time = setup.timestamp.time() if hasattr(setup.timestamp, "time") else dtime(10, 0)

                # Direction alignment: does setup match market?
                aligned = (
                    (setup.direction == "LONG" and regime_info.get("direction") == "UP") or
                    (setup.direction == "SHORT" and regime_info.get("direction") == "DOWN")
                )

                row = {
                    # Identifiers (not features)
                    "symbol": symbol,
                    "date": today,
                    "timestamp": str(setup.timestamp),
                    "setup_type": setup.setup_type,
                    "direction": setup.direction,

                    # Features
                    "breakout_strength": abs(entry_price - setup.reference_level) / setup.reference_level if setup.reference_level > 0 else 0,
                    "volume_ratio": setup.volume_ratio if not np.isnan(setup.volume_ratio) else 1.0,
                    "candle_strength": setup.candle_strength,
                    "consolidation_tightness": setup.consolidation_tightness,
                    "atr_pct": atr / entry_price if entry_price > 0 else 0,
                    "regime": regime_info.get("regime", "UNCLEAR"),
                    "market_direction": regime_info.get("direction", "NEUTRAL"),
                    "market_adx": regime_info.get("adx", 0),
                    "market_trend_strength": regime_info.get("trend_strength", 0),
                    "direction_aligned": 1 if aligned else 0,
                    "hour": candle_time.hour,
                    "minute": candle_time.minute,
                    "is_opening": 1 if setup.setup_type == "opening" else 0,
                    "is_short": 1 if is_short else 0,
                    "score": setup.score,

                    # Label
                    "outcome": outcome,  # 1 = TP hit first, 0 = SL hit or expired
                }

                rows.append(row)

        if (sym_idx + 1) % 10 == 0:
            print(f"  [{sym_idx + 1}/{len(symbols)}] {len(rows)} setups so far")

    if not rows:
        print("  No setups found!")
        return pd.DataFrame()

    dataset = pd.DataFrame(rows)

    # Save
    DATASET_PATH.parent.mkdir(parents=True, exist_ok=True)
    dataset.to_csv(DATASET_PATH, index=False)

    # Summary
    total = len(dataset)
    wins = (dataset["outcome"] == 1).sum()
    print(f"\n  Dataset built: {total} setups")
    print(f"  Wins (TP hit): {wins} ({wins/total*100:.1f}%)")
    print(f"  Losses: {total - wins} ({(total-wins)/total*100:.1f}%)")
    print(f"  Longs: {(dataset['is_short'] == 0).sum()}")
    print(f"  Shorts: {(dataset['is_short'] == 1).sum()}")
    print(f"  Aligned with market: {(dataset['direction_aligned'] == 1).sum()}")
    print(f"  Saved to: {DATASET_PATH}")

    return dataset


def _compute_outcome(
    future: pd.DataFrame,
    entry: float,
    sl: float,
    tp: float,
    is_short: bool,
    max_candles: int,
) -> int:
    """
    Simulate forward: does TP hit before SL?

    Returns:
        1 if take-profit hit first
        0 if stop-loss hit first or expired without hitting either
    """
    for i, (_, row) in enumerate(future.iterrows()):
        if i >= max_candles:
            break

        if is_short:
            # Short: SL is above entry, TP is below
            if row["high"] >= sl:
                return 0  # SL hit
            if row["low"] <= tp:
                return 1  # TP hit
        else:
            # Long: SL is below entry, TP is above
            if row["low"] <= sl:
                return 0  # SL hit
            if row["high"] >= tp:
                return 1  # TP hit

    return 0  # Expired without hitting either


# Feature columns for ML training
SETUP_FEATURE_COLS = [
    "breakout_strength",
    "volume_ratio",
    "candle_strength",
    "consolidation_tightness",
    "atr_pct",
    "market_adx",
    "market_trend_strength",
    "direction_aligned",
    "hour",
    "is_opening",
    "is_short",
    "score",
]
