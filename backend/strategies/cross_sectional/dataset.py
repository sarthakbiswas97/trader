"""
Dataset Builder for Cross-Sectional Return Prediction.

Builds training data: for each stock at each 5-min bar,
compute features and the 30-minute forward relative return.

Label: (stock_return_30m - nifty_return_30m)
Entry: next candle open (realistic execution)
Exit: t+6 close
"""

from datetime import date, time as dtime
from pathlib import Path

import numpy as np
import pandas as pd

from backend.core.logger import get_logger
from backend.core.symbols import NIFTY_100
from backend.services.historical_data import HistoricalDataService
from backend.strategies.cross_sectional.features import (
    compute_stock_features,
    prepare_nifty_features,
    FEATURE_COLUMNS,
)

logger = get_logger(__name__)

_BACKEND_DIR = Path(__file__).parent.parent.parent
DATASET_PATH = _BACKEND_DIR / "data" / "training" / "cross_sectional_dataset.csv"

# Only generate features during trading hours (skip pre-market noise)
TRADING_START = dtime(9, 25)  # After opening noise
TRADING_END = dtime(14, 45)    # Leave room for 30-min holding
LOOKAHEAD = 6  # 6 candles = 30 minutes


def build_dataset(
    symbols: list[str] = None,
    save: bool = True,
) -> pd.DataFrame:
    """
    Build cross-sectional dataset from all stocks.

    For each stock at each 5-min bar:
      - Compute features (lagged returns, technicals, time)
      - Compute 30-min forward return (next open → t+6 close)
      - Compute NIFTY forward return for relative target

    Returns:
        DataFrame with features + target
    """
    symbols = symbols or NIFTY_100
    ds = HistoricalDataService()

    # Load and prepare NIFTY index
    nifty_path = _BACKEND_DIR / "data" / "index" / "NIFTY50_5m.csv"
    nifty_df = pd.read_csv(nifty_path)
    nifty_df["timestamp"] = pd.to_datetime(nifty_df["timestamp"])
    nifty_df = prepare_nifty_features(nifty_df)

    # Compute NIFTY forward returns
    nifty_df["nifty_fwd_ret"] = nifty_df["close"].shift(-LOOKAHEAD) / nifty_df["close"] - 1
    nifty_fwd = nifty_df.set_index("timestamp")["nifty_fwd_ret"].to_dict()

    print("Building cross-sectional dataset...")
    print(f"  Symbols: {len(symbols)}")
    print(f"  Lookahead: {LOOKAHEAD} candles (30 min)")

    all_rows = []

    for sym_idx, symbol in enumerate(symbols):
        df = ds.load_candles(symbol, "5m")
        if df.empty or len(df) < 100:
            continue

        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df = df.sort_values("timestamp").reset_index(drop=True)

        # Compute stock features
        df = compute_stock_features(df)

        # Compute forward return: entry at NEXT candle open, exit at t+6 close
        df["next_open"] = df["open"].shift(-1)
        df["future_close"] = df["close"].shift(-LOOKAHEAD)
        df["stock_fwd_ret"] = (df["future_close"] - df["next_open"]) / df["next_open"]

        # Filter to trading hours only
        df["time"] = df["timestamp"].dt.time
        mask = (df["time"] >= TRADING_START) & (df["time"] <= TRADING_END)
        df = df[mask]

        # Per-stock features (computed above)
        per_stock_cols = [
            "ret_1", "ret_2", "ret_3", "ret_5", "ret_10",
            "rsi", "macd_norm", "atr_pct", "volatility_20", "vol_spike",
            "momentum_10", "boll_pos", "vwap_distance", "range_pos_20",
            "ema_ratio", "dist_from_day_high", "minute_of_day", "day_of_week",
        ]

        # Drop NaN rows (from indicator warmup + forward return)
        df = df.dropna(subset=[c for c in per_stock_cols if c in df.columns] + ["stock_fwd_ret"])

        # Compute relative return (target)
        df["nifty_fwd"] = df["timestamp"].map(nifty_fwd)
        df["target"] = df["stock_fwd_ret"] - df["nifty_fwd"].fillna(0)

        # Compute relative strength vs NIFTY
        nifty_ret5 = nifty_df.set_index("timestamp")["ret_5"].to_dict()
        df["nifty_ret_5"] = df["timestamp"].map(nifty_ret5).fillna(0)
        df["relative_strength"] = df["ret_5"] - df["nifty_ret_5"]

        # Market context from NIFTY
        nifty_adx_map = nifty_df.set_index("timestamp")["adx_val"].to_dict()
        nifty_trend_map = nifty_df.set_index("timestamp")["trend"].to_dict()
        df["market_adx"] = df["timestamp"].map(nifty_adx_map).fillna(0)
        df["market_trend"] = df["timestamp"].map(nifty_trend_map).fillna(0)

        # Placeholder for cross-sectional ranks (filled after all stocks processed)
        df["ret_5_rank"] = 0.5
        df["volume_rank"] = 0.5

        # Build rows
        for _, row in df.iterrows():
            r = {"symbol": symbol, "timestamp": row["timestamp"]}
            for col in FEATURE_COLUMNS:
                r[col] = float(row.get(col, 0))
            r["target"] = float(row["target"])
            r["stock_fwd_ret"] = float(row["stock_fwd_ret"])
            all_rows.append(r)

        if (sym_idx + 1) % 20 == 0:
            print(f"  [{sym_idx + 1}/{len(symbols)}] {len(all_rows):,} rows so far")

    if not all_rows:
        print("  No data generated!")
        return pd.DataFrame()

    dataset = pd.DataFrame(all_rows)

    # Replace inf/nan
    dataset = dataset.replace([np.inf, -np.inf], np.nan)
    for col in FEATURE_COLUMNS:
        dataset[col] = dataset[col].fillna(0)

    dataset = dataset.dropna(subset=["target"])

    # Cross-sectional ranking: rank each stock vs others at same timestamp
    print("  Computing cross-sectional ranks...")
    dataset["ret_5_rank"] = dataset.groupby("timestamp")["ret_5"].rank(pct=True)
    dataset["volume_rank"] = dataset.groupby("timestamp")["vol_spike"].rank(pct=True)

    # Sort by timestamp
    dataset = dataset.sort_values("timestamp").reset_index(drop=True)

    # Summary
    total = len(dataset)
    print(f"\n  Dataset built: {total:,} rows")
    print(f"  Symbols: {dataset['symbol'].nunique()}")
    print(f"  Date range: {dataset['timestamp'].min()} to {dataset['timestamp'].max()}")
    print(f"  Target mean: {dataset['target'].mean():.6f}")
    print(f"  Target std: {dataset['target'].std():.4f}")
    print(f"  Positive targets: {(dataset['target'] > 0).mean()*100:.1f}%")

    if save:
        DATASET_PATH.parent.mkdir(parents=True, exist_ok=True)
        dataset.to_csv(DATASET_PATH, index=False)
        print(f"  Saved to: {DATASET_PATH}")

    return dataset
