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

            # 4. Check exits for open positions (always, even after market hours)
            exit_results = self.trade_executor.check_and_execute_exits(predictions)

            # 5. Extract ATR values from features for dynamic SL/TP
            atr_values = {}
            for symbol, features in all_features.items():
                if hasattr(features, "atr") and features.atr > 0:
                    # Denormalize: feature ATR is atr/close, we need raw ATR
                    ltp = self.broker.get_ltp([symbol]).get(symbol, 0)
                    if ltp > 0:
                        atr_values[symbol] = features.atr * ltp

            # 6. Rank and execute entries (only during market hours)
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
                        atr_values=atr_values,
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


PIPELINE_A_INTERVAL = 7200   # 2 hours in seconds
PIPELINE_B_INTERVAL = 1800   # 30 minutes in seconds
PIPELINE_CAPITAL = 100000.0  # ₹1L per pipeline


@dataclass
class PipelineState:
    """State for a single A/B pipeline."""
    name: str                    # "A" or "B"
    label: str                   # "2-hour scan" or "30-min scan"
    interval_secs: int
    multi_engine: Any            # MultiEngine instance
    last_scan: datetime | None = None
    scan_count: int = 0


class ABReversalEngine:
    """
    A/B testing engine — two independent reversal pipelines.

    Pipeline A: Scans every 2 hours (3 scans/day)
    Pipeline B: Scans every 30 minutes (12 scans/day)

    Both use identical reversal scoring, same regime gate, but
    independent capital (₹1L each), positions, trades, kill switches.
    Every scan is logged to DB for analysis.
    """

    def __init__(self, broker: Broker):
        from collections import deque
        from backend.strategies.multi_engine import MultiEngine
        from backend.core.symbols import NIFTY_100

        from backend.broker.paper import PaperBroker

        self.broker = broker
        self.symbols = NIFTY_100
        self.running = False
        self._cycle_count = 0
        self._cycle_history: deque[CycleResult] = deque(maxlen=100)
        self._latest_predictions: dict = {}

        kite = getattr(broker, "_kite", None)
        kite_api_key = getattr(broker, "kite_api_key", None)
        kite_api_secret = getattr(broker, "kite_api_secret", None)
        access_token = getattr(broker, "_access_token", None)

        # Separate PaperBroker per pipeline — independent capital and positions
        broker_a = PaperBroker(
            initial_capital=PIPELINE_CAPITAL,
            kite_api_key=kite_api_key,
            kite_api_secret=kite_api_secret,
        )
        broker_b = PaperBroker(
            initial_capital=PIPELINE_CAPITAL,
            kite_api_key=kite_api_key,
            kite_api_secret=kite_api_secret,
        )
        # Authenticate both with same Kite session for real market data
        if access_token:
            broker_a.authenticate(access_token=access_token)
            broker_b.authenticate(access_token=access_token)
        else:
            broker_a.authenticate()
            broker_b.authenticate()

        self.brokers = {"A": broker_a, "B": broker_b}

        # Two independent pipelines with their own brokers
        self.pipelines: dict[str, PipelineState] = {
            "A": PipelineState(
                name="A",
                label="2-hour scan",
                interval_secs=PIPELINE_A_INTERVAL,
                multi_engine=MultiEngine(kite=kite, total_capital=PIPELINE_CAPITAL, broker=broker_a),
            ),
            "B": PipelineState(
                name="B",
                label="30-min scan",
                interval_secs=PIPELINE_B_INTERVAL,
                multi_engine=MultiEngine(kite=kite, total_capital=PIPELINE_CAPITAL, broker=broker_b),
            ),
        }

        # Reset both to ensure clean state with separate capital
        for p in self.pipelines.values():
            p.multi_engine.reset()
            p.multi_engine.total_capital = PIPELINE_CAPITAL
            p.multi_engine.cash = PIPELINE_CAPITAL

        # Frontend interface compatibility
        self.risk_guardian = RiskGuardian(broker)
        self.position_manager = PositionManager(broker)
        self.trade_executor = TradeExecutor(
            broker=broker,
            risk_guardian=self.risk_guardian,
            position_manager=self.position_manager,
        )

        logger.info(
            "ABReversalEngine initialized",
            pipelines=["A (2hr)", "B (30min)"],
            capital_per_pipeline=PIPELINE_CAPITAL,
        )

    def stop(self) -> None:
        self.running = False
        logger.info("ABReversalEngine stopped")

    async def run(self) -> None:
        """Main loop — checks both pipelines at their respective intervals."""
        logger.info("ABReversalEngine starting")

        while self.running:
            try:
                if not is_market_open():
                    wait_time = time_to_market_open()
                    logger.info("Market closed", next_open_in=str(wait_time))
                    await asyncio.sleep(min(60, wait_time.total_seconds()))
                    continue

                now = now_ist()

                for pipeline in self.pipelines.values():
                    elapsed = (
                        (now - pipeline.last_scan).total_seconds()
                        if pipeline.last_scan else float("inf")
                    )

                    if elapsed >= pipeline.interval_secs:
                        await self._run_pipeline_cycle(pipeline)

                # Sleep 60s between checks
                await asyncio.sleep(60)

            except Exception as e:
                logger.error(f"ABReversalEngine error: {e}")
                await asyncio.sleep(60)

        logger.info("ABReversalEngine stopped")

    async def _run_pipeline_cycle(self, pipeline: PipelineState) -> None:
        """Run one cycle for a single pipeline and log results."""
        import time as _time

        self._cycle_count += 1
        pipeline.scan_count += 1
        pipeline.last_scan = now_ist()
        start_ms = _time.monotonic()

        try:
            result = pipeline.multi_engine.run_daily()
            duration_ms = int((_time.monotonic() - start_ms) * 1000)

            total_entries = sum(
                len(eng.get("picks", []))
                for eng in result.get("engines", {}).values()
            )
            total_exits = sum(
                len(eng.get("exits", []))
                for eng in result.get("engines", {}).values()
            )

            # Build top picks detail for logging
            top_picks = []
            for eng_name, eng_data in result.get("engines", {}).items():
                for pick in eng_data.get("picks", []):
                    top_picks.append({
                        "symbol": pick["symbol"],
                        "score": pick.get("score", 0),
                        "ret_5d": pick.get("ret_5d", 0),
                        "engine": eng_name,
                        "action": "BUY",
                    })
                for skip in eng_data.get("skipped", []):
                    top_picks.append({
                        "symbol": skip["symbol"],
                        "ret_5d": skip.get("ret_5d", 0),
                        "engine": eng_name,
                        "action": "SKIP",
                        "reason": skip.get("reason", ""),
                    })

            # Count blocked/skipped
            blocked = sum(
                1 for eng in result.get("engines", {}).values()
                if eng.get("action", "").startswith("kill_switch") or
                   eng.get("action") == "regime_inactive"
            )

            # Persist scan log
            self._persist_scan_log(
                pipeline=pipeline.name,
                regime=result.get("regime", "UNKNOWN"),
                stocks_scanned=len(self.symbols),
                buy_signals=total_entries,
                skipped_count=len([p for p in top_picks if p["action"] == "SKIP"]),
                blocked_count=blocked,
                entries_made=total_entries,
                exits_made=total_exits,
                scan_duration_ms=duration_ms,
                top_picks=top_picks,
                regime_signals=result.get("allocation"),
                portfolio_value=result.get("portfolio_value", 0),
                cash=result.get("cash", 0),
                unrealized_pnl=0,
                open_positions_count=sum(
                    eng.get("open_positions", 0)
                    for eng in result.get("engines", {}).values()
                ),
            )

            # Append cycle for frontend
            cycle = CycleResult(
                timestamp=now_ist(),
                market_open=is_market_open(),
                tier=f"pipeline_{pipeline.name}",
                symbols_scanned=len(self.symbols),
                predictions_generated=0,
                signals_found=total_entries,
                entries_executed=total_entries,
                exits_executed=total_exits,
                errors=[result.get("error", "")] if result.get("error") else [],
                hot_watchlist=[],
            )
            self._cycle_history.append(cycle)

            logger.info(
                f"Pipeline {pipeline.name} ({pipeline.label}) cycle complete",
                regime=result.get("regime"),
                entries=total_entries,
                exits=total_exits,
                portfolio=result.get("portfolio_value"),
                scan_number=pipeline.scan_count,
                duration_ms=duration_ms,
            )

        except Exception as e:
            logger.error(f"Pipeline {pipeline.name} cycle failed: {e}")

    def _persist_scan_log(self, **kwargs) -> None:
        """Fire-and-forget: persist scan log to DB."""
        try:
            from backend.db.database import get_session
            from backend.db.repository import ScanLogRepository

            kwargs["timestamp"] = now_ist()
            with get_session() as session:
                ScanLogRepository(session).insert(**kwargs)
        except Exception as e:
            logger.warning(f"Failed to persist scan log: {e}")

    # =========================================================================
    # Frontend interface (same as old ReversalEngine)
    # =========================================================================

    @property
    def multi_engine(self):
        """Default to pipeline A for backward-compatible endpoints."""
        return self.pipelines["A"].multi_engine

    def get_pipeline(self, pipeline_id: str) -> PipelineState | None:
        return self.pipelines.get(pipeline_id.upper())

    def square_off_all(self) -> list[dict[str, Any]]:
        return [r.to_dict() for r in self.trade_executor.square_off_all()]

    def get_status(self) -> dict[str, Any]:
        pipeline_status = {}
        for pid, p in self.pipelines.items():
            me = p.multi_engine
            pipeline_status[pid] = {
                "label": p.label,
                "interval_secs": p.interval_secs,
                "scan_count": p.scan_count,
                "last_scan": p.last_scan.isoformat() if p.last_scan else None,
                "regime": me.current_regime.value if me.current_regime else "unknown",
                "portfolio_value": me.total_capital + me.cash,
                "cash": me.cash,
                "engines": {
                    name: {
                        "capital": state.capital,
                        "open_positions": sum(len(b["stocks"]) for b in state.positions),
                        "total_trades": len(state.trade_history),
                        "pnl": sum(t.get("net_pnl", 0) for t in state.trade_history),
                        "active": state.active,
                    }
                    for name, state in me.engine_states.items()
                },
            }

        return {
            "running": self.running,
            "strategy": "ab_reversal",
            "cycle_count": self._cycle_count,
            "pipelines": pipeline_status,
            "last_cycle": (
                self._cycle_history[-1].to_dict()
                if self._cycle_history else None
            ),
        }

    def get_recent_cycles(self, limit: int = 10) -> list[dict[str, Any]]:
        return [c.to_dict() for c in self._cycle_history[-limit:]]

    def get_hot_watchlist(self) -> list[dict[str, Any]]:
        items = []
        for pid, p in self.pipelines.items():
            for name, state in p.multi_engine.engine_states.items():
                for batch in state.positions:
                    for stock in batch["stocks"]:
                        items.append({
                            "symbol": stock["symbol"],
                            "pipeline": pid,
                            "engine": name,
                            "entry_price": stock["entry_price"],
                            "score": stock.get("score", 0),
                            "entry_date": batch["entry_date"],
                        })
        return items


def create_engine(broker: Broker, **kwargs) -> ABReversalEngine:
    """Factory function to create the A/B reversal testing engine."""
    return ABReversalEngine(broker=broker)
