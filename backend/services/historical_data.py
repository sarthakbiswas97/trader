"""
Historical data fetcher service.
Uses Zerodha Kite Connect API for OHLCV candle data.
Rate limited to 3 requests/second for historical data API.
"""

import time
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from backend.core.logger import get_logger
from backend.utils.time_utils import IST

logger = get_logger(__name__)

DATA_DIR = Path(__file__).parent.parent.parent / "data" / "historical"
DATA_DIR.mkdir(parents=True, exist_ok=True)

INTERVAL_MAP = {
    "1m": "minute",
    "3m": "3minute",
    "5m": "5minute",
    "10m": "10minute",
    "15m": "15minute",
    "30m": "30minute",
    "1h": "60minute",
    "1d": "day",
}

# Rate limiting: 3 requests per second
RATE_LIMIT_DELAY = 0.35  # seconds between requests (slightly > 1/3)


class HistoricalDataService:
    """
    Service for fetching and storing historical market data from Zerodha.
    Respects Kite API rate limits (3 req/sec for historical data).
    """

    def __init__(self, kite=None):
        self._kite = kite
        self._instruments_cache = {}
        self._last_request_time = 0
        logger.info("HistoricalDataService initialized")

    def set_kite(self, kite):
        """Set authenticated Kite client."""
        self._kite = kite

    def _ensure_kite(self):
        if not self._kite:
            raise RuntimeError("Kite client not set. Call set_kite() first.")

    def _rate_limit(self):
        """Enforce rate limiting between API calls."""
        elapsed = time.time() - self._last_request_time
        if elapsed < RATE_LIMIT_DELAY:
            time.sleep(RATE_LIMIT_DELAY - elapsed)
        self._last_request_time = time.time()

    def get_instrument_token(self, symbol: str, exchange: str = "NSE") -> int:
        """Get instrument token for a symbol."""
        self._ensure_kite()

        cache_key = f"{exchange}:{symbol}"
        if cache_key in self._instruments_cache:
            return self._instruments_cache[cache_key]

        # Load all instruments once (this is a single API call)
        self._rate_limit()
        instruments = self._kite.instruments(exchange=exchange)
        for inst in instruments:
            key = f"{exchange}:{inst['tradingsymbol']}"
            self._instruments_cache[key] = inst["instrument_token"]

        return self._instruments_cache.get(cache_key, 0)

    def fetch_candles(
        self,
        symbol: str,
        interval: str = "5m",
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        days: int = 60,
    ) -> pd.DataFrame:
        """
        Fetch historical candles for a symbol.

        Args:
            symbol: Trading symbol (e.g., "RELIANCE")
            interval: Candle interval ("1m", "5m", "15m", "30m", "1h", "1d")
            start_date: Start date
            end_date: End date
            days: Number of days if dates not specified

        Returns:
            DataFrame with columns: timestamp, open, high, low, close, volume
        """
        self._ensure_kite()

        if end_date is None:
            end_date = datetime.now(IST)
        if start_date is None:
            start_date = end_date - timedelta(days=days)

        instrument_token = self.get_instrument_token(symbol)
        if not instrument_token:
            logger.error(f"Instrument token not found for {symbol}")
            return pd.DataFrame()

        kite_interval = INTERVAL_MAP.get(interval, "5minute")

        logger.info(
            f"Fetching candles",
            symbol=symbol,
            interval=interval,
            start=start_date.date(),
            end=end_date.date(),
        )

        try:
            self._rate_limit()
            data = self._kite.historical_data(
                instrument_token=instrument_token,
                from_date=start_date,
                to_date=end_date,
                interval=kite_interval,
            )

            if not data:
                logger.warning(f"No data returned for {symbol}")
                return pd.DataFrame()

            df = pd.DataFrame(data)
            df = df.rename(columns={"date": "timestamp"})
            df = df[["timestamp", "open", "high", "low", "close", "volume"]]

            if df["timestamp"].dt.tz is None:
                df["timestamp"] = df["timestamp"].dt.tz_localize(IST)
            else:
                df["timestamp"] = df["timestamp"].dt.tz_convert(IST)

            logger.info(f"Fetched {len(df)} candles for {symbol}")
            return df

        except Exception as e:
            logger.error(f"Failed to fetch candles for {symbol}: {e}")
            return pd.DataFrame()

    def download_symbol(
        self,
        symbol: str,
        intervals: list[str] = ["5m", "1h", "1d"],
        days: int = 60,
        save: bool = True,
    ) -> dict[str, pd.DataFrame]:
        """Download data for a symbol at multiple intervals."""
        result = {}

        for interval in intervals:
            logger.info(f"Downloading {symbol} {interval}")
            df = self.fetch_candles(symbol, interval, days=days)

            if df.empty:
                logger.warning(f"No data for {symbol} {interval}")
                continue

            result[interval] = df

            if save:
                filepath = DATA_DIR / f"{symbol}_{interval}.csv"
                df.to_csv(filepath, index=False)
                logger.info(f"Saved {len(df)} rows to {filepath.name}")

        return result

    def download_universe(
        self,
        symbols: list[str],
        intervals: list[str] = ["5m", "1h", "1d"],
        days: int = 60,
    ) -> dict[str, dict[str, pd.DataFrame]]:
        """Download data for multiple symbols with progress tracking."""
        result = {}
        total = len(symbols)
        total_requests = total * len(intervals)
        estimated_time = total_requests * RATE_LIMIT_DELAY

        logger.info(
            f"Starting download",
            symbols=total,
            intervals=len(intervals),
            total_requests=total_requests,
            estimated_minutes=round(estimated_time / 60, 1),
        )

        for i, symbol in enumerate(symbols, 1):
            logger.info(f"Progress: {i}/{total} - {symbol}")
            print(f"  [{i}/{total}] {symbol}...", end=" ", flush=True)

            try:
                result[symbol] = self.download_symbol(symbol, intervals, days)
                intervals_done = list(result[symbol].keys())
                print(f"✓ {intervals_done}")
            except Exception as e:
                logger.error(f"Failed to download {symbol}: {e}")
                print(f"✗ Error: {e}")
                continue

        logger.info(f"Downloaded data for {len(result)}/{total} symbols")
        return result

    def load_candles(self, symbol: str, interval: str = "5m") -> pd.DataFrame:
        """Load previously downloaded candles from CSV."""
        filepath = DATA_DIR / f"{symbol}_{interval}.csv"

        if not filepath.exists():
            logger.warning(f"No saved data for {symbol} {interval}")
            return pd.DataFrame()

        df = pd.read_csv(filepath)
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        return df

    def get_available_symbols(self) -> list[str]:
        """List symbols with downloaded data."""
        files = DATA_DIR.glob("*_5m.csv")
        return sorted([f.stem.replace("_5m", "") for f in files])
