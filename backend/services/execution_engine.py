"""
Execution Engine - Main trading loop orchestrator.
Coordinates all services to execute the trading strategy.
"""

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import pandas as pd

from backend.broker.base import Broker
from backend.config import settings
from backend.core.logger import get_logger
from backend.ml.inference import PredictionService, Prediction
from backend.services.feature_engine import FeatureEngine, FeatureVector
from backend.services.historical_data import HistoricalDataService
from backend.services.position_manager import PositionManager
from backend.services.risk_guardian import RiskGuardian
from backend.services.stock_ranker import StockRanker
from backend.services.trade_executor import TradeExecutor
from backend.utils.time_utils import (
    now_ist,
    is_market_open,
    can_place_new_entry,
    time_to_market_open,
    format_ist_time,
)

logger = get_logger(__name__)


@dataclass
class CycleResult:
    """Result of a single execution cycle."""
    timestamp: datetime
    market_open: bool
    predictions_generated: int
    signals_found: int
    entries_executed: int
    exits_executed: int
    errors: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "market_open": self.market_open,
            "predictions_generated": self.predictions_generated,
            "signals_found": self.signals_found,
            "entries_executed": self.entries_executed,
            "exits_executed": self.exits_executed,
            "errors": self.errors,
        }


class ExecutionEngine:
    """
    Main trading loop orchestrator.
    Runs every 5 minutes during market hours to:
    1. Fetch latest candle data
    2. Generate predictions for all symbols
    3. Check exit conditions for existing positions
    4. Execute entries for top-ranked signals
    """

    def __init__(
        self,
        broker: Broker,
        symbols: list[str],
        data_service: HistoricalDataService = None,
        cycle_interval_seconds: int = 300,  # 5 minutes
    ):
        self.broker = broker
        self.symbols = symbols
        self.cycle_interval = cycle_interval_seconds

        # Initialize services
        self.data_service = data_service or HistoricalDataService(broker)
        self.feature_engine = FeatureEngine(data_service=self.data_service)
        self.prediction_service = PredictionService()
        self.risk_guardian = RiskGuardian(broker)
        self.position_manager = PositionManager(broker)
        self.stock_ranker = StockRanker(
            min_confidence=0.1,  # 60% probability threshold
            min_probability=0.55,
            max_stocks=5,
        )
        self.trade_executor = TradeExecutor(
            broker=broker,
            risk_guardian=self.risk_guardian,
            position_manager=self.position_manager,
        )

        self.running = False
        self._cycle_count = 0
        self._cycle_history: list[CycleResult] = []

        logger.info(
            "ExecutionEngine initialized",
            symbols=len(symbols),
            cycle_interval=cycle_interval_seconds,
        )

    async def run(self) -> None:
        """
        Main execution loop.
        Runs until stopped or market closes.
        """
        self.running = True
        logger.info("Execution engine starting")

        while self.running:
            try:
                # Check market hours
                if not is_market_open():
                    wait_time = time_to_market_open()
                    logger.info(
                        "Market closed",
                        next_open_in=str(wait_time),
                    )
                    # Wait max 60 seconds before checking again
                    await asyncio.sleep(min(60, wait_time.total_seconds()))
                    continue

                # Run execution cycle
                result = await self._run_cycle()
                self._cycle_history.append(result)

                # Log cycle result
                logger.info(
                    "Cycle complete",
                    cycle=self._cycle_count,
                    predictions=result.predictions_generated,
                    signals=result.signals_found,
                    entries=result.entries_executed,
                    exits=result.exits_executed,
                )

                # Wait for next cycle
                await self._wait_for_next_cycle()

            except Exception as e:
                logger.error(f"Execution cycle error: {e}")
                await asyncio.sleep(30)  # Short pause on error

        logger.info("Execution engine stopped")

    async def _run_cycle(self) -> CycleResult:
        """
        Run a single execution cycle.
        """
        self._cycle_count += 1
        errors = []
        predictions = {}
        ranked_stocks = []
        entry_results = []
        exit_results = []

        try:
            # 1. Fetch latest candles and generate features
            all_features = await self._fetch_features()

            # 2. Generate predictions
            for symbol, features in all_features.items():
                try:
                    pred = self.prediction_service.predict(features)
                    predictions[symbol] = pred
                except Exception as e:
                    errors.append(f"Prediction failed for {symbol}: {e}")
                    logger.error(f"Prediction failed for {symbol}: {e}")

            # 3. Check exits for existing positions
            exit_results = self.trade_executor.check_and_execute_exits(predictions)

            # 4. Rank stocks for new entries
            if can_place_new_entry():
                # Get symbols we already hold
                held_symbols = [p.symbol for p in self.position_manager.get_all_positions()]

                ranked_stocks = self.stock_ranker.rank(
                    predictions,
                    exclude_symbols=held_symbols,
                )

                # 5. Execute entries
                if ranked_stocks:
                    margin = self.broker.get_margin()
                    entry_results = self.trade_executor.execute_entries(
                        ranked_stocks,
                        available_capital=margin.available_cash,
                    )

        except Exception as e:
            errors.append(f"Cycle error: {e}")
            logger.error(f"Cycle error: {e}")

        return CycleResult(
            timestamp=now_ist(),
            market_open=is_market_open(),
            predictions_generated=len(predictions),
            signals_found=len(ranked_stocks),
            entries_executed=sum(1 for r in entry_results if r.success),
            exits_executed=sum(1 for r in exit_results if r.success),
            errors=errors,
        )

    async def _fetch_features(self) -> dict[str, FeatureVector]:
        """
        Fetch latest candle data and compute features for all symbols.
        """
        features = {}
        lookback_minutes = 200 * 5  # 200 candles of 5-min data

        for symbol in self.symbols:
            try:
                # Fetch recent 5-min candles
                end_date = now_ist()
                start_date = end_date - timedelta(minutes=lookback_minutes)

                df_5m = self.data_service.fetch_candles(
                    symbol=symbol,
                    interval="5m",
                    start_date=start_date,
                    end_date=end_date,
                )

                if df_5m.empty or len(df_5m) < 100:
                    logger.warning(f"Insufficient data for {symbol}")
                    continue

                # Compute features
                feature_vector = self.feature_engine.get_latest_features(symbol, df_5m)

                if feature_vector:
                    features[symbol] = feature_vector

            except Exception as e:
                logger.error(f"Failed to fetch features for {symbol}: {e}")

        logger.info(f"Generated features for {len(features)}/{len(self.symbols)} symbols")
        return features

    async def _wait_for_next_cycle(self) -> None:
        """Wait until the next 5-minute candle closes."""
        now = now_ist()

        # Calculate next 5-minute boundary
        minutes = now.minute
        next_5min = ((minutes // 5) + 1) * 5 - minutes
        if next_5min == 0:
            next_5min = 5

        wait_seconds = next_5min * 60 - now.second + 5  # +5 seconds buffer

        logger.debug(f"Waiting {wait_seconds}s for next cycle")
        await asyncio.sleep(wait_seconds)

    def stop(self) -> None:
        """Stop the execution engine."""
        self.running = False
        logger.info("Stop requested")

    def square_off_all(self) -> list[dict[str, Any]]:
        """
        Manually square off all positions.
        """
        results = self.trade_executor.square_off_all()
        return [r.to_dict() for r in results]

    def get_status(self) -> dict[str, Any]:
        """Get current engine status."""
        return {
            "running": self.running,
            "cycle_count": self._cycle_count,
            "last_cycle": (
                self._cycle_history[-1].to_dict()
                if self._cycle_history else None
            ),
            "positions": self.position_manager.get_summary(),
            "risk": self.risk_guardian.get_status(),
            "executor": self.trade_executor.get_summary(),
        }

    def get_recent_cycles(self, limit: int = 10) -> list[dict[str, Any]]:
        """Get recent cycle results."""
        return [c.to_dict() for c in self._cycle_history[-limit:]]


def create_engine(
    broker: Broker,
    symbols: list[str] = None,
) -> ExecutionEngine:
    """
    Factory function to create a configured ExecutionEngine.

    Args:
        broker: Broker instance (Paper or Zerodha)
        symbols: List of symbols to trade (defaults to NIFTY 50)

    Returns:
        Configured ExecutionEngine
    """
    # Default to NIFTY 50 symbols
    if symbols is None:
        symbols = [
            "RELIANCE", "INFY", "TCS", "HDFCBANK", "ICICIBANK",
            "SBIN", "BHARTIARTL", "ITC", "KOTAKBANK", "LT",
            "HINDUNILVR", "AXISBANK", "BAJFINANCE", "ASIANPAINT", "MARUTI",
            "TITAN", "SUNPHARMA", "ULTRACEMCO", "NESTLEIND", "WIPRO",
            "HCLTECH", "POWERGRID", "NTPC", "TECHM", "M&M",
            "BAJAJFINSV", "ONGC", "ADANIENT", "ADANIPORTS", "COALINDIA",
            "JSWSTEEL", "TATASTEEL", "GRASIM", "INDUSINDBK", "BRITANNIA",
            "CIPLA", "DRREDDY", "DIVISLAB", "EICHERMOT", "HEROMOTOCO",
            "BPCL", "APOLLOHOSP", "SBILIFE", "TATACONSUM", "HINDALCO",
            "BAJAJ-AUTO", "UPL", "SHREECEM",
        ]

    # Create data service and set the kite client from broker
    data_service = HistoricalDataService()

    # For Zerodha broker, set the kite client
    if hasattr(broker, "_kite") and broker._kite:
        data_service.set_kite(broker._kite)

    return ExecutionEngine(
        broker=broker,
        symbols=symbols,
        data_service=data_service,
    )
