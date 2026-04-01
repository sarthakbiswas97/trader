"""
Execution Engine - Main trading loop orchestrator.
Uses adaptive tiered scanning:
  Tier 1 (Hot):    Scanned every 2 min — high-confidence signals + open positions
  Tier 2 (Default): Scanned every 5 min — all remaining symbols
"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import pandas as pd

from backend.broker.base import Broker
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
)

logger = get_logger(__name__)

# Tier promotion threshold: confidence >= 20% in either direction
HOT_CONFIDENCE_THRESHOLD = 0.20

# Consecutive weak scans before demotion from Tier 1
DEMOTE_AFTER_WEAK_SCANS = 3

# Scan intervals
TIER1_INTERVAL_SECONDS = 120   # 2 minutes
TIER2_INTERVAL_SECONDS = 300   # 5 minutes


@dataclass
class CycleResult:
    """Result of a single execution cycle."""
    timestamp: datetime
    market_open: bool
    tier: str  # "tier1" or "tier2" or "full"
    symbols_scanned: int
    predictions_generated: int
    signals_found: int
    entries_executed: int
    exits_executed: int
    errors: list[str]
    hot_watchlist: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "market_open": self.market_open,
            "tier": self.tier,
            "symbols_scanned": self.symbols_scanned,
            "predictions_generated": self.predictions_generated,
            "signals_found": self.signals_found,
            "entries_executed": self.entries_executed,
            "exits_executed": self.exits_executed,
            "errors": self.errors,
            "hot_watchlist": self.hot_watchlist,
        }


@dataclass
class WatchlistEntry:
    """Tracks a symbol's tier status."""
    symbol: str
    tier: int = 2  # 1 = hot, 2 = default
    last_confidence: float = 0.0
    last_direction: str = "NEUTRAL"
    weak_scan_count: int = 0  # Consecutive weak scans
    promoted_at: datetime | None = None


class ExecutionEngine:
    """
    Main trading loop with adaptive tiered scanning.

    Tier 1 (Hot Watchlist): Scanned every 2 minutes
      - Symbols with confidence >= 20% (strong UP or DOWN signal)
      - Symbols with open positions (need exit monitoring)
      - First 30 minutes after market open (9:15-9:45)

    Tier 2 (Default): Scanned every 5 minutes
      - All remaining symbols
    """

    def __init__(
        self,
        broker: Broker,
        symbols: list[str],
        data_service: HistoricalDataService = None,
    ):
        self.broker = broker
        self.symbols = symbols

        # Services
        self.data_service = data_service or HistoricalDataService()
        self.feature_engine = FeatureEngine(data_service=self.data_service)
        self.prediction_service = PredictionService()
        self.risk_guardian = RiskGuardian(broker)
        self.position_manager = PositionManager(broker)
        self.stock_ranker = StockRanker(
            min_confidence=0.20,
            min_probability=0.55,
            max_stocks=5,
        )
        self.trade_executor = TradeExecutor(
            broker=broker,
            risk_guardian=self.risk_guardian,
            position_manager=self.position_manager,
        )

        # Watchlist state
        self._watchlist: dict[str, WatchlistEntry] = {
            s: WatchlistEntry(symbol=s) for s in symbols
        }
        self._last_tier2_scan: datetime | None = None
        self._latest_predictions: dict[str, Prediction] = {}

        # Engine state
        self.running = False
        self._cycle_count = 0
        from collections import deque
        self._cycle_history: deque[CycleResult] = deque(maxlen=500)

        logger.info(
            "ExecutionEngine initialized",
            symbols=len(symbols),
            tier1_interval=TIER1_INTERVAL_SECONDS,
            tier2_interval=TIER2_INTERVAL_SECONDS,
        )

    # =========================================================================
    # Tier Management
    # =========================================================================

    def _get_tier1_symbols(self) -> list[str]:
        """Get symbols that should be scanned at Tier 1 frequency."""
        now = now_ist()
        held_symbols = {p.symbol for p in self.position_manager.get_all_positions()}

        # First 30 min after market open → all symbols are hot
        market_open_time = now.replace(hour=9, minute=15, second=0)
        if now - market_open_time < timedelta(minutes=30):
            return self.symbols

        tier1 = set()

        # Symbols with high confidence
        for symbol, entry in self._watchlist.items():
            if entry.tier == 1:
                tier1.add(symbol)

        # Symbols with open positions (always monitor)
        tier1.update(held_symbols)

        return list(tier1)

    def _get_tier2_symbols(self) -> list[str]:
        """Get symbols for Tier 2 scan (everything not in Tier 1)."""
        tier1 = set(self._get_tier1_symbols())
        return [s for s in self.symbols if s not in tier1]

    def _update_tiers(self, predictions: dict[str, Prediction]) -> None:
        """Update tier assignments based on latest predictions."""
        for symbol, pred in predictions.items():
            if symbol not in self._watchlist:
                self._watchlist[symbol] = WatchlistEntry(symbol=symbol)

            entry = self._watchlist[symbol]
            entry.last_confidence = pred.confidence
            entry.last_direction = pred.direction

            # Promote to Tier 1 if confidence is high
            if pred.confidence >= HOT_CONFIDENCE_THRESHOLD and pred.direction != "NEUTRAL":
                if entry.tier != 1:
                    entry.tier = 1
                    entry.promoted_at = now_ist()
                    entry.weak_scan_count = 0
                    logger.info(
                        "Promoted to Tier 1",
                        symbol=symbol,
                        direction=pred.direction,
                        confidence=f"{pred.confidence:.1%}",
                    )
            else:
                # Count weak scans for demotion
                entry.weak_scan_count += 1
                if entry.tier == 1 and entry.weak_scan_count >= DEMOTE_AFTER_WEAK_SCANS:
                    entry.tier = 2
                    entry.weak_scan_count = 0
                    logger.info("Demoted to Tier 2", symbol=symbol)

    def _persist_predictions(self, predictions: dict[str, "Prediction"]) -> None:
        """Fire-and-forget: persist predictions to DB for historical analysis."""
        if not predictions:
            return
        try:
            from backend.db.database import get_session
            from backend.db.repository import PredictionRepository

            cycle_id = self._cycle_count
            ts = now_ist()
            records = [
                {
                    "symbol": pred.symbol,
                    "direction": pred.direction,
                    "probability": pred.probability,
                    "confidence": pred.confidence,
                    "prob_up": pred.prob_up,
                    "prob_down": pred.prob_down,
                    "prob_neutral": pred.prob_neutral,
                    "should_trade": pred.should_trade,
                    "cycle_id": cycle_id,
                    "timestamp": ts,
                }
                for pred in predictions.values()
            ]
            with get_session() as session:
                repo = PredictionRepository(session)
                repo.bulk_insert(records)
        except Exception as e:
            logger.warning(f"Failed to persist predictions: {e}")

    def get_hot_watchlist(self) -> list[dict[str, Any]]:
        """Get current Tier 1 (hot) watchlist for frontend display."""
        result = []
        for symbol in self._get_tier1_symbols():
            entry = self._watchlist.get(symbol)
            pred = self._latest_predictions.get(symbol)

            result.append({
                "symbol": symbol,
                "tier": 1,
                "direction": entry.last_direction if entry else "NEUTRAL",
                "confidence": entry.last_confidence if entry else 0,
                "has_position": self.position_manager.has_position(symbol),
                "promoted_at": entry.promoted_at.isoformat() if entry and entry.promoted_at else None,
            })

        return sorted(result, key=lambda x: x["confidence"], reverse=True)

    # =========================================================================
    # Main Loop
    # =========================================================================

    async def run(self) -> None:
        """Main execution loop with tiered scanning."""
        self.running = True
        logger.info("Execution engine starting")

        while self.running:
            try:
                if not is_market_open():
                    wait_time = time_to_market_open()
                    logger.info("Market closed", next_open_in=str(wait_time))
                    await asyncio.sleep(min(60, wait_time.total_seconds()))
                    continue

                # Determine what to scan this cycle
                now = now_ist()
                needs_tier2 = (
                    self._last_tier2_scan is None
                    or (now - self._last_tier2_scan).total_seconds() >= TIER2_INTERVAL_SECONDS
                )

                if needs_tier2:
                    # Full scan: Tier 1 + Tier 2
                    result = await self._run_cycle(self.symbols, tier_label="full")
                    self._last_tier2_scan = now
                else:
                    # Hot scan: Tier 1 only
                    tier1_symbols = self._get_tier1_symbols()
                    if tier1_symbols:
                        result = await self._run_cycle(tier1_symbols, tier_label="tier1")
                    else:
                        # Nothing hot, wait for next tier2 cycle
                        await asyncio.sleep(30)
                        continue

                self._cycle_history.append(result)

                logger.info(
                    "Cycle complete",
                    cycle=self._cycle_count,
                    tier=result.tier,
                    scanned=result.symbols_scanned,
                    predictions=result.predictions_generated,
                    signals=result.signals_found,
                    entries=result.entries_executed,
                    exits=result.exits_executed,
                    hot_count=len(result.hot_watchlist),
                )

                # Wait for next Tier 1 cycle
                await asyncio.sleep(TIER1_INTERVAL_SECONDS)

            except Exception as e:
                logger.error(f"Execution cycle error: {e}")
                await asyncio.sleep(30)

        logger.info("Execution engine stopped")

    async def _run_cycle(
        self,
        symbols_to_scan: list[str],
        tier_label: str = "full",
    ) -> CycleResult:
        """Run a single execution cycle for the given symbols."""
        self._cycle_count += 1
        errors = []
        predictions = {}
        ranked_stocks = []
        entry_results = []
        exit_results = []

        try:
            # 1. Fetch features for scanned symbols
            all_features = await self._fetch_features(symbols_to_scan)

            # 2. Generate predictions
            for symbol, features in all_features.items():
                try:
                    pred = self.prediction_service.predict(features)
                    predictions[symbol] = pred
                    self._latest_predictions[symbol] = pred
                except Exception as e:
                    errors.append(f"Prediction failed for {symbol}: {e}")

            # 3. Update tier assignments + persist predictions
            self._update_tiers(predictions)
            self._persist_predictions(predictions)

            # 4. Check exits for open positions
            exit_results = self.trade_executor.check_and_execute_exits(predictions)

            # 5. Rank and execute entries
            if can_place_new_entry():
                held_symbols = [p.symbol for p in self.position_manager.get_all_positions()]

                ranked_stocks = self.stock_ranker.rank(
                    predictions,
                    exclude_symbols=held_symbols,
                )

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
            tier=tier_label,
            symbols_scanned=len(symbols_to_scan),
            predictions_generated=len(predictions),
            signals_found=len(ranked_stocks),
            entries_executed=sum(1 for r in entry_results if r.success),
            exits_executed=sum(1 for r in exit_results if r.success),
            errors=errors,
            hot_watchlist=self._get_tier1_symbols(),
        )

    async def _fetch_features(
        self,
        symbols: list[str],
    ) -> dict[str, FeatureVector]:
        """Fetch candle data and compute features for given symbols."""
        features = {}

        for symbol in symbols:
            try:
                end_date = now_ist()
                start_date = end_date - timedelta(days=5)

                df_5m = self.data_service.fetch_candles(
                    symbol=symbol,
                    interval="5m",
                    start_date=start_date,
                    end_date=end_date,
                )

                if df_5m.empty or len(df_5m) < 100:
                    logger.warning(f"Insufficient data for {symbol}")
                    continue

                feature_vector = self.feature_engine.get_latest_features(symbol, df_5m)
                if feature_vector:
                    features[symbol] = feature_vector

            except Exception as e:
                logger.error(f"Failed to fetch features for {symbol}: {e}")

        logger.info(f"Generated features for {len(features)}/{len(symbols)} symbols")
        return features

    # =========================================================================
    # Control
    # =========================================================================

    def stop(self) -> None:
        self.running = False
        logger.info("Stop requested")

    def square_off_all(self) -> list[dict[str, Any]]:
        results = self.trade_executor.square_off_all()
        return [r.to_dict() for r in results]

    def get_status(self) -> dict[str, Any]:
        return {
            "running": self.running,
            "cycle_count": self._cycle_count,
            "last_cycle": (
                self._cycle_history[-1].to_dict()
                if self._cycle_history else None
            ),
            "hot_watchlist": self.get_hot_watchlist(),
            "positions": self.position_manager.get_summary(),
            "risk": self.risk_guardian.get_status(),
            "executor": self.trade_executor.get_summary(),
        }

    def get_recent_cycles(self, limit: int = 10) -> list[dict[str, Any]]:
        return [c.to_dict() for c in self._cycle_history[-limit:]]


def create_engine(
    broker: Broker,
    symbols: list[str] = None,
) -> ExecutionEngine:
    """Factory function to create a configured ExecutionEngine."""
    from backend.core.symbols import NIFTY_50

    if symbols is None:
        symbols = NIFTY_50

    data_service = HistoricalDataService()

    if hasattr(broker, "_kite") and broker._kite:
        data_service.set_kite(broker._kite)

    return ExecutionEngine(
        broker=broker,
        symbols=symbols,
        data_service=data_service,
    )
