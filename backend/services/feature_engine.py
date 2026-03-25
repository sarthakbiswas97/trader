"""
Feature engineering service.
Generates 17 technical features from OHLCV data for ML model input.
"""

from dataclasses import dataclass
from datetime import datetime

import numpy as np
import pandas as pd

from backend.core.indicators import (
    rsi,
    macd,
    ema,
    bollinger_position,
    adx,
    atr,
    momentum,
    volatility,
    volume_spike,
    price_acceleration,
    range_position,
    volatility_regime,
    trend_direction,
)
from backend.core.logger import get_logger
from backend.services.historical_data import HistoricalDataService

logger = get_logger(__name__)


@dataclass
class FeatureVector:
    """Complete feature set for a single prediction."""
    symbol: str
    timestamp: datetime

    # Base features (9)
    rsi: float
    macd: float
    macd_signal: float
    macd_histogram: float
    ema_ratio: float
    volatility: float
    volume_spike: float
    momentum: float
    bollinger_position: float

    # Regime features (5)
    adx: float
    atr: float
    volatility_regime: float
    price_acceleration: float
    range_position: float

    # Multi-timeframe context (3)
    hourly_trend: int
    daily_trend: int
    daily_range_position: float

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "timestamp": self.timestamp,
            "rsi": self.rsi,
            "macd": self.macd,
            "macd_signal": self.macd_signal,
            "macd_histogram": self.macd_histogram,
            "ema_ratio": self.ema_ratio,
            "volatility": self.volatility,
            "volume_spike": self.volume_spike,
            "momentum": self.momentum,
            "bollinger_position": self.bollinger_position,
            "adx": self.adx,
            "atr": self.atr,
            "volatility_regime": self.volatility_regime,
            "price_acceleration": self.price_acceleration,
            "range_position": self.range_position,
            "hourly_trend": self.hourly_trend,
            "daily_trend": self.daily_trend,
            "daily_range_position": self.daily_range_position,
        }

    def to_array(self) -> np.ndarray:
        """Convert to numpy array for ML model input."""
        return np.array([
            self.rsi,
            self.macd,
            self.macd_signal,
            self.macd_histogram,
            self.ema_ratio,
            self.volatility,
            self.volume_spike,
            self.momentum,
            self.bollinger_position,
            self.adx,
            self.atr,
            self.volatility_regime,
            self.price_acceleration,
            self.range_position,
            self.hourly_trend,
            self.daily_trend,
            self.daily_range_position,
        ])


FEATURE_COLUMNS = [
    "rsi",
    "macd",
    "macd_signal",
    "macd_histogram",
    "ema_ratio",
    "volatility",
    "volume_spike",
    "momentum",
    "bollinger_position",
    "adx",
    "atr",
    "volatility_regime",
    "price_acceleration",
    "range_position",
    "hourly_trend",
    "daily_trend",
    "daily_range_position",
]


class FeatureEngine:
    """
    Generates features from OHLCV data for ML model training and inference.
    """

    def __init__(self, data_service: HistoricalDataService = None):
        self.data_service = data_service
        logger.info("FeatureEngine initialized")

    def compute_base_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Compute base technical features from OHLCV data.

        Args:
            df: DataFrame with columns [timestamp, open, high, low, close, volume]

        Returns:
            DataFrame with added feature columns
        """
        df = df.copy()
        close = df["close"]
        high = df["high"]
        low = df["low"]
        volume = df["volume"]

        # RSI
        df["rsi"] = rsi(close, period=14)

        # MACD (normalized by price)
        macd_line, signal_line, histogram = macd(close)
        df["macd"] = macd_line / close
        df["macd_signal"] = signal_line / close
        df["macd_histogram"] = histogram / close

        # EMA ratio
        df["ema_ratio"] = close / ema(close, 20)

        # Volatility
        df["volatility"] = volatility(close, period=20)

        # Volume spike
        df["volume_spike"] = volume_spike(volume, period=20)

        # Momentum
        df["momentum"] = momentum(close, period=10)

        # Bollinger position
        df["bollinger_position"] = bollinger_position(close, period=20)

        return df

    def compute_regime_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Compute regime/context features."""
        df = df.copy()
        close = df["close"]
        high = df["high"]
        low = df["low"]

        # ADX
        df["adx"] = adx(high, low, close, period=14)

        # ATR (normalized by price)
        df["atr"] = atr(high, low, close, period=14) / close

        # Volatility regime
        df["volatility_regime"] = volatility_regime(close, period=20, lookback=100)

        # Price acceleration
        df["price_acceleration"] = price_acceleration(close, period=5)

        # Range position
        df["range_position"] = range_position(close, period=50)

        return df

    def compute_all_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Compute all features for a single timeframe."""
        df = self.compute_base_features(df)
        df = self.compute_regime_features(df)
        return df

    def add_multi_timeframe_context(
        self,
        df_5m: pd.DataFrame,
        df_1h: pd.DataFrame,
        df_1d: pd.DataFrame
    ) -> pd.DataFrame:
        """
        Add multi-timeframe context to 5-minute data.
        Merges hourly and daily trend info into 5-min dataframe.
        """
        df = df_5m.copy()

        # Compute trends for higher timeframes
        df_1h = df_1h.copy()
        df_1h["hourly_trend"] = trend_direction(df_1h["close"], fast=10, slow=30)
        df_1h["hour"] = df_1h["timestamp"].dt.floor("h")

        df_1d = df_1d.copy()
        df_1d["daily_trend"] = trend_direction(df_1d["close"], fast=5, slow=20)
        df_1d["daily_range_position"] = range_position(df_1d["close"], period=20)
        df_1d["date"] = df_1d["timestamp"].dt.date

        # Merge hourly trend
        df["hour"] = df["timestamp"].dt.floor("h")
        hourly_map = df_1h.set_index("hour")["hourly_trend"].to_dict()
        df["hourly_trend"] = df["hour"].map(hourly_map).fillna(0).astype(int)

        # Merge daily trend and range
        df["date"] = df["timestamp"].dt.date
        daily_trend_map = df_1d.set_index("date")["daily_trend"].to_dict()
        daily_range_map = df_1d.set_index("date")["daily_range_position"].to_dict()
        df["daily_trend"] = df["date"].map(daily_trend_map).fillna(0).astype(int)
        df["daily_range_position"] = df["date"].map(daily_range_map).fillna(0.5)

        # Clean up temp columns
        df = df.drop(columns=["hour", "date"])

        return df

    def generate_features_for_symbol(
        self,
        symbol: str,
        df_5m: pd.DataFrame = None,
        df_1h: pd.DataFrame = None,
        df_1d: pd.DataFrame = None,
    ) -> pd.DataFrame:
        """
        Generate complete feature set for a symbol.

        Args:
            symbol: Trading symbol
            df_5m: 5-minute OHLCV data (or loads from data_service)
            df_1h: 1-hour OHLCV data (or loads from data_service)
            df_1d: Daily OHLCV data (or loads from data_service)

        Returns:
            DataFrame with all features computed
        """
        # Load data if not provided
        if df_5m is None and self.data_service:
            df_5m = self.data_service.load_candles(symbol, "5m")
        if df_1h is None and self.data_service:
            df_1h = self.data_service.load_candles(symbol, "1h")
        if df_1d is None and self.data_service:
            df_1d = self.data_service.load_candles(symbol, "1d")

        if df_5m is None or df_5m.empty:
            logger.error(f"No 5m data for {symbol}")
            return pd.DataFrame()

        logger.info(f"Computing features for {symbol}", rows=len(df_5m))

        # Compute base features on 5-min data
        df = self.compute_all_features(df_5m)

        # Add multi-timeframe context
        if df_1h is not None and not df_1h.empty and df_1d is not None and not df_1d.empty:
            df = self.add_multi_timeframe_context(df, df_1h, df_1d)
        else:
            # Default values if higher timeframes not available
            df["hourly_trend"] = 0
            df["daily_trend"] = 0
            df["daily_range_position"] = 0.5

        # Add symbol column
        df["symbol"] = symbol

        # Drop rows with NaN (from indicator warmup period)
        df = df.dropna(subset=FEATURE_COLUMNS)

        logger.info(f"Generated {len(df)} feature rows for {symbol}")
        return df

    def generate_features_for_universe(
        self,
        symbols: list[str],
        save: bool = True
    ) -> pd.DataFrame:
        """
        Generate features for multiple symbols.

        Args:
            symbols: List of trading symbols
            save: Whether to save to CSV

        Returns:
            Combined DataFrame with features for all symbols
        """
        all_features = []
        total = len(symbols)

        for i, symbol in enumerate(symbols, 1):
            logger.info(f"Processing {i}/{total}: {symbol}")
            print(f"  [{i}/{total}] {symbol}...", end=" ", flush=True)

            try:
                df = self.generate_features_for_symbol(symbol)
                if not df.empty:
                    all_features.append(df)
                    print(f"✓ {len(df)} rows")
                else:
                    print("✗ No data")
            except Exception as e:
                logger.error(f"Failed for {symbol}: {e}")
                print(f"✗ Error: {e}")

        if not all_features:
            return pd.DataFrame()

        combined = pd.concat(all_features, ignore_index=True)
        logger.info(f"Total feature rows: {len(combined)}")

        if save:
            from pathlib import Path
            output_path = Path("data/training/features.csv")
            output_path.parent.mkdir(parents=True, exist_ok=True)
            combined.to_csv(output_path, index=False)
            logger.info(f"Saved features to {output_path}")

        return combined

    def get_latest_features(self, symbol: str, df_5m: pd.DataFrame) -> FeatureVector | None:
        """
        Get the latest feature vector for real-time prediction.

        Args:
            symbol: Trading symbol
            df_5m: Recent 5-minute OHLCV data (at least 100 rows)

        Returns:
            FeatureVector for the latest candle
        """
        df = self.generate_features_for_symbol(symbol, df_5m=df_5m)

        if df.empty:
            return None

        # Get latest row
        latest = df.iloc[-1]

        return FeatureVector(
            symbol=symbol,
            timestamp=latest["timestamp"],
            rsi=latest["rsi"],
            macd=latest["macd"],
            macd_signal=latest["macd_signal"],
            macd_histogram=latest["macd_histogram"],
            ema_ratio=latest["ema_ratio"],
            volatility=latest["volatility"],
            volume_spike=latest["volume_spike"],
            momentum=latest["momentum"],
            bollinger_position=latest["bollinger_position"],
            adx=latest["adx"],
            atr=latest["atr"],
            volatility_regime=latest["volatility_regime"],
            price_acceleration=latest["price_acceleration"],
            range_position=latest["range_position"],
            hourly_trend=int(latest["hourly_trend"]),
            daily_trend=int(latest["daily_trend"]),
            daily_range_position=latest["daily_range_position"],
        )
