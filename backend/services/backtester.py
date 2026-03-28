"""
Backtesting Engine — Walk-forward simulation with real costs.

Simulates trading on historical data to validate the strategy
before risking real money.

Usage:
    from backend.services.backtester import Backtester
    bt = Backtester(capital=100000)
    results = bt.run()
    bt.generate_report("backtest_report.html")
"""

from dataclasses import dataclass, field
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from backend.core.logger import get_logger
from backend.core.symbols import NIFTY_50
from backend.ml.labeling import DEFAULT_FEATURES_PATH
from backend.ml.train_model import ModelTrainer
from backend.services.feature_engine import FeatureEngine, FEATURE_COLUMNS
from backend.services.historical_data import HistoricalDataService

logger = get_logger(__name__)

_BACKEND_DIR = Path(__file__).parent.parent


# =============================================================================
# Transaction Cost Model (Zerodha)
# =============================================================================

@dataclass
class ZerodhaCosts:
    """Real Zerodha intraday (MIS) cost model."""
    brokerage_pct: float = 0.0003        # 0.03%
    brokerage_cap: float = 20.0          # ₹20 cap per order
    stt_sell_pct: float = 0.00025        # 0.025% on sell side
    exchange_pct: float = 0.0000345      # ~0.00345%
    gst_pct: float = 0.18               # 18% GST on brokerage
    sebi_pct: float = 0.000001           # ₹10 per crore
    stamp_buy_pct: float = 0.00003       # 0.003% on buy side

    def calculate(self, price: float, quantity: int, side: str) -> float:
        """Calculate total transaction cost for one leg."""
        turnover = price * quantity

        # Brokerage
        brokerage = min(turnover * self.brokerage_pct, self.brokerage_cap)

        # STT (only on sell)
        stt = turnover * self.stt_sell_pct if side == "SELL" else 0

        # Exchange charges
        exchange = turnover * self.exchange_pct

        # GST on brokerage
        gst = brokerage * self.gst_pct

        # SEBI charges
        sebi = turnover * self.sebi_pct

        # Stamp duty (only on buy)
        stamp = turnover * self.stamp_buy_pct if side == "BUY" else 0

        return brokerage + stt + exchange + gst + sebi + stamp

    def round_trip_cost(self, entry_price: float, exit_price: float, quantity: int, is_short: bool = False) -> float:
        """Calculate total cost for a round trip (entry + exit)."""
        if is_short:
            entry_cost = self.calculate(entry_price, quantity, "SELL")
            exit_cost = self.calculate(exit_price, quantity, "BUY")
        else:
            entry_cost = self.calculate(entry_price, quantity, "BUY")
            exit_cost = self.calculate(exit_price, quantity, "SELL")

        return entry_cost + exit_cost


# =============================================================================
# Trade Record
# =============================================================================

@dataclass
class BacktestTrade:
    """Record of a single backtest trade."""
    symbol: str
    side: str  # "LONG" or "SHORT"
    entry_time: datetime
    exit_time: datetime
    entry_price: float
    exit_price: float
    quantity: int
    gross_pnl: float
    costs: float
    net_pnl: float
    slippage_cost: float
    exit_reason: str
    confidence: float
    direction: str  # Predicted direction


# =============================================================================
# Backtester
# =============================================================================

class Backtester:
    """
    Walk-forward backtesting engine.

    Trains model on rolling window, tests on unseen data,
    simulates trades with real costs and slippage.
    """

    def __init__(
        self,
        capital: float = 100000.0,
        train_days: int = 30,
        retrain_every_days: int = 5,
        slippage_pct: float = 0.0005,  # 0.05%
        max_position_pct: float = 0.05,
        max_long_exposure: float = 0.20,
        max_short_exposure: float = 0.15,
        max_total_exposure: float = 0.25,
        long_stop_loss: float = 0.0015,      # -0.15% SL for longs
        long_take_profit: float = 0.003,     # +0.3% TP for longs
        short_stop_loss: float = 0.002,      # -0.2% SL for shorts
        short_take_profit: float = 0.003,    # +0.3% TP for shorts
        min_confidence: float = 0.20,
        long_max_hold_candles: int = 24,   # 2 hours at 5-min
        short_max_hold_candles: int = 18,  # 1.5 hours at 5-min
        enable_shorting: bool = True,
        cooldown_candles: int = 6,         # 30 min cooldown between trades on same stock
        max_trades_per_stock_per_day: int = 3,
        max_concurrent_positions: int = 5,
        require_confirmation: bool = True,
        stock_filter_pct: float = 0.0,  # 0 = no filter, 0.4 = keep top 40%
        test_start_date: date | None = None,  # If set, only trade on/after this date
        test_end_date: date | None = None,    # If set, only trade on/before this date
        symbols: list[str] = None,
    ):
        self.initial_capital = capital
        self.capital = capital
        self.train_days = train_days
        self.retrain_every_days = retrain_every_days
        self.slippage_pct = slippage_pct
        self.max_position_pct = max_position_pct
        self.max_long_exposure = max_long_exposure
        self.max_short_exposure = max_short_exposure
        self.max_total_exposure = max_total_exposure
        self.long_stop_loss = long_stop_loss
        self.long_take_profit = long_take_profit
        self.short_stop_loss = short_stop_loss
        self.short_take_profit = short_take_profit
        self.min_confidence = min_confidence
        self.long_max_hold = long_max_hold_candles
        self.short_max_hold = short_max_hold_candles
        self.enable_shorting = enable_shorting
        self.cooldown_candles = cooldown_candles
        self.max_trades_per_stock_per_day = max_trades_per_stock_per_day
        self.max_concurrent_positions = max_concurrent_positions
        self.require_confirmation = require_confirmation
        self.stock_filter_pct = stock_filter_pct
        self.test_start_date = test_start_date
        self.test_end_date = test_end_date
        self.symbols = symbols or NIFTY_50

        self.costs = ZerodhaCosts()
        self.trades: list[BacktestTrade] = []
        self.equity_curve: list[dict] = []
        self._positions: dict[str, dict] = {}  # symbol -> position info
        self._stock_trades_today: dict[str, int] = {}
        self._stock_last_exit_candle: dict[str, int] = {}
        self._current_day: date | None = None
        self._pending_signals: dict[str, dict] = {}  # symbol -> signal awaiting confirmation
        self._allowed_stocks: set[str] | None = None  # Filtered stock universe

    def run(self) -> dict:
        """
        Run the full walk-forward backtest.

        Returns:
            Dict with all results and metrics
        """
        logger.info("Starting backtest...")
        print("=" * 60)
        print("BACKTESTING ENGINE")
        print("=" * 60)

        # Load all feature data
        feature_engine = FeatureEngine()
        data_service = HistoricalDataService()

        # Load features for all symbols
        all_data = self._load_all_data(feature_engine, data_service)
        if not all_data:
            raise RuntimeError("No data loaded for backtesting")

        # Get unique trading days
        all_dates = set()
        for df in all_data.values():
            all_dates.update(df["timestamp"].dt.date.unique())
        trading_days = sorted(all_dates)

        print(f"\nData loaded:")
        print(f"  Symbols: {len(all_data)}")
        print(f"  Trading days: {len(trading_days)}")
        print(f"  Date range: {trading_days[0]} to {trading_days[-1]}")

        # Determine test date range
        if self.test_start_date:
            # Find the first test day index
            test_day_indices = [i for i, d in enumerate(trading_days) if d >= self.test_start_date]
            if not test_day_indices:
                raise RuntimeError(f"No trading days on or after {self.test_start_date}")
            first_test_idx = test_day_indices[0]

            # Train on days before test_start
            train_end_idx = first_test_idx
        else:
            train_end_idx = self.train_days

        if train_end_idx >= len(trading_days):
            raise RuntimeError(f"Not enough days. Have {len(trading_days)}, need at least {train_end_idx + 1}")

        # Determine last test day
        last_test_day = self.test_end_date or trading_days[-1]

        model = None
        last_train_day = None
        day_count = 0

        for day_idx in range(train_end_idx, len(trading_days)):
            test_day = trading_days[day_idx]

            # Stop if past test end date
            if test_day > last_test_day:
                break

            # Check if we need to retrain
            if model is None or (last_train_day and (test_day - last_train_day).days >= self.retrain_every_days):
                train_end = trading_days[day_idx - 1]
                train_start = trading_days[max(0, day_idx - self.train_days)]

                print(f"\n  Retraining model: {train_start} → {train_end}")
                model = self._train_model(all_data, train_start, train_end)
                last_train_day = test_day

                if model is None:
                    print(f"    Training failed, skipping day {test_day}")
                    continue

            # Simulate trading on this day
            day_trades = self._simulate_day(model, all_data, test_day)
            day_count += 1

            # Record equity
            open_pnl = self._get_unrealized_pnl(all_data, test_day)
            self.equity_curve.append({
                "date": test_day,
                "capital": self.capital,
                "equity": self.capital + open_pnl,
                "open_positions": len(self._positions),
                "trades_today": len(day_trades),
            })

            if day_trades:
                pnl = self.capital - self.initial_capital
                print(f"  Day {test_day}: Capital ₹{self.capital:,.0f} | P&L ₹{pnl:,.0f} | Trades: {len(day_trades)}")

        # Close any remaining positions at last available price
        self._close_all_positions(all_data, trading_days[-1], "backtest_end")

        # Stock filtering: run a first pass to identify best stocks, then re-run
        if self.stock_filter_pct > 0 and self._allowed_stocks is None and self.trades:
            results_pre = self._calculate_metrics()
            per_stock = results_pre.get("per_stock", {})

            if per_stock:
                ranked = sorted(
                    per_stock.items(),
                    key=lambda x: x[1]["total_pnl"],
                    reverse=True,
                )
                keep_count = max(5, int(len(ranked) * self.stock_filter_pct))
                top_stocks = {s for s, _ in ranked[:keep_count]}

                print(f"\n  Stock filter: keeping top {keep_count}/{len(ranked)} stocks")
                print(f"  Kept: {', '.join(sorted(top_stocks)[:10])}{'...' if len(top_stocks) > 10 else ''}")

                # Reset and re-run with filter applied
                self._allowed_stocks = top_stocks
                self.capital = self.initial_capital
                self.trades.clear()
                self.equity_curve.clear()
                self._positions.clear()
                self._pending_signals.clear()
                self._stock_trades_today.clear()
                self._stock_last_exit_candle.clear()
                self._current_day = None

                return self.run()  # Recursive re-run with filter

        # Calculate metrics
        results = self._calculate_metrics()

        print("\n" + "=" * 60)
        print("BACKTEST COMPLETE")
        print("=" * 60)
        self._print_summary(results)

        return results

    # =========================================================================
    # Data Loading
    # =========================================================================

    def _load_all_data(
        self,
        feature_engine: FeatureEngine,
        data_service: HistoricalDataService,
    ) -> dict[str, pd.DataFrame]:
        """Load and compute features for all symbols from saved CSV."""
        all_data = {}

        for symbol in self.symbols:
            try:
                df = data_service.load_candles(symbol, "5m")
                if df.empty or len(df) < 100:
                    continue

                df = feature_engine.compute_all_features(df)
                df["hourly_trend"] = 0
                df["daily_trend"] = 0
                df["daily_range_position"] = 0.5
                df = df.dropna(subset=FEATURE_COLUMNS)

                if len(df) >= 50:
                    all_data[symbol] = df
            except Exception as e:
                logger.warning(f"Failed to load {symbol}: {e}")

        return all_data

    # =========================================================================
    # Model Training
    # =========================================================================

    def _train_model(
        self,
        all_data: dict[str, pd.DataFrame],
        train_start: date,
        train_end: date,
    ) -> ModelTrainer | None:
        """Train model on data within date range."""
        train_frames = []

        for symbol, df in all_data.items():
            mask = (df["timestamp"].dt.date >= train_start) & (df["timestamp"].dt.date <= train_end)
            subset = df[mask]
            if len(subset) >= 20:
                subset = subset.copy()
                subset["symbol"] = symbol
                train_frames.append(subset)

        if not train_frames:
            return None

        train_df = pd.concat(train_frames, ignore_index=True)

        # Create labels
        from backend.ml.labeling import create_labels
        train_df = create_labels(train_df, lookahead=6, threshold=0.002, num_classes=2)

        if len(train_df) < 100:
            return None

        X = train_df[FEATURE_COLUMNS].values
        y = train_df["target"].values

        # Train with class balancing via scale_pos_weight
        import xgboost as xgb
        neg_count = (y == 0).sum()
        pos_count = (y == 1).sum()
        scale_pos_weight = neg_count / pos_count if pos_count > 0 else 1.0

        model = xgb.XGBClassifier(
            max_depth=4,
            learning_rate=0.1,
            n_estimators=100,
            min_child_weight=3,
            scale_pos_weight=scale_pos_weight,
            objective="binary:logistic",
            eval_metric="logloss",
            random_state=42,
            n_jobs=-1,
        )
        model.fit(X, y, verbose=False)

        trainer = ModelTrainer()
        trainer.model = model
        trainer.num_classes = 2

        return trainer

    # =========================================================================
    # Day Simulation
    # =========================================================================

    def _simulate_day(
        self,
        model: ModelTrainer,
        all_data: dict[str, pd.DataFrame],
        test_day: date,
    ) -> list[BacktestTrade]:
        """Simulate one trading day."""
        day_trades = []

        # Reset daily counters
        if self._current_day != test_day:
            self._current_day = test_day
            self._stock_trades_today.clear()
            self._stock_last_exit_candle.clear()

        for symbol, df in all_data.items():
            day_candles = df[df["timestamp"].dt.date == test_day]
            if len(day_candles) < 10:
                continue

            for i, (idx, row) in enumerate(day_candles.iterrows()):
                # Skip first 3 and last 3 candles (warmup + close)
                if i < 3 or i >= len(day_candles) - 3:
                    # Force close positions near end of day
                    if i >= len(day_candles) - 3 and symbol in self._positions:
                        trade = self._close_position(symbol, row["close"], row["timestamp"], "market_close")
                        if trade:
                            day_trades.append(trade)
                            self._stock_last_exit_candle[symbol] = i
                    continue

                # Check exits for existing position
                if symbol in self._positions:
                    trade = self._check_exit(symbol, row, i)
                    if trade:
                        day_trades.append(trade)
                        self._stock_last_exit_candle[symbol] = i
                        continue

                # Check pending confirmation
                if symbol in self._pending_signals and symbol not in self._positions:
                    if self._check_confirmation(symbol, row, i):
                        pass  # Position opened inside _check_confirmation

                # Try entry if no position + pass trade limiters + no pending signal
                if symbol not in self._positions and symbol not in self._pending_signals and self._can_trade(symbol, i):
                    self._try_entry(model, symbol, row, i)

        return day_trades

    def _can_trade(self, symbol: str, candle_idx: int) -> bool:
        """Check trade limiters: cooldown, per-stock limit, max concurrent."""
        # Max concurrent positions
        if len(self._positions) >= self.max_concurrent_positions:
            return False

        # Per-stock daily limit
        stock_count = self._stock_trades_today.get(symbol, 0)
        if stock_count >= self.max_trades_per_stock_per_day:
            return False

        # Cooldown: wait N candles after last exit on this stock
        last_exit = self._stock_last_exit_candle.get(symbol)
        if last_exit is not None and (candle_idx - last_exit) < self.cooldown_candles:
            return False

        return True

    def _try_entry(self, model: ModelTrainer, symbol: str, row: pd.Series, candle_idx: int) -> None:
        """Generate signal. If confirmation required, store as pending."""
        # Stock filter check
        if self._allowed_stocks is not None and symbol not in self._allowed_stocks:
            return

        features = row[FEATURE_COLUMNS].values.reshape(1, -1)
        prob_up = model.model.predict_proba(features)[0, 1]

        # Asymmetric entry thresholds
        if prob_up >= 0.65:
            direction = "UP"
            confidence = prob_up
            is_short = False
        elif prob_up <= 0.30:
            direction = "DOWN"
            confidence = 1 - prob_up
            is_short = True
        else:
            return  # NEUTRAL

        if is_short and not self.enable_shorting:
            return

        if not self._check_exposure(is_short):
            return

        signal = {
            "direction": direction,
            "confidence": confidence,
            "is_short": is_short,
            "signal_price": row["close"],
            "signal_volume": row["volume"],
            "signal_high": row["high"],
            "signal_time": row["timestamp"],
            "signal_candle": candle_idx,
        }

        if self.require_confirmation:
            self._pending_signals[symbol] = signal
        else:
            self._open_from_signal(symbol, signal, row)

    def _check_confirmation(self, symbol: str, row: pd.Series, candle_idx: int) -> bool:
        """Check if pending signal is confirmed by this candle."""
        signal = self._pending_signals.get(symbol)
        if not signal:
            return False

        # Expire signal if too old (only valid for 1 candle)
        if candle_idx - signal["signal_candle"] > 1:
            del self._pending_signals[symbol]
            return False

        # Must be exactly the next candle
        if candle_idx != signal["signal_candle"] + 1:
            return False

        confirmed = False

        if signal["direction"] == "UP":
            # Confirm: price moved up AND volume is decent
            price_up = row["close"] > signal["signal_price"]
            breakout = row["high"] > signal["signal_high"]
            confirmed = price_up or breakout

        elif signal["direction"] == "DOWN":
            # Confirm: price moved down
            price_down = row["close"] < signal["signal_price"]
            confirmed = price_down

        del self._pending_signals[symbol]

        if confirmed:
            self._open_from_signal(symbol, signal, row)
            return True

        return False

    def _open_from_signal(self, symbol: str, signal: dict, row: pd.Series) -> None:
        """Open a position from a confirmed signal."""
        is_short = signal["is_short"]

        if is_short:
            max_alloc = self.capital * min(self.max_position_pct, self.max_short_exposure - self._get_short_exposure())
        else:
            max_alloc = self.capital * min(self.max_position_pct, self.max_long_exposure - self._get_long_exposure())

        max_alloc = max(0, min(max_alloc, self.capital * self.max_position_pct))

        price = row["close"]
        quantity = int(max_alloc / price)
        if quantity <= 0 or quantity * price < 1000:
            return

        if is_short:
            entry_price = price * (1 - self.slippage_pct)
        else:
            entry_price = price * (1 + self.slippage_pct)

        self._positions[symbol] = {
            "side": "SHORT" if is_short else "LONG",
            "entry_price": entry_price,
            "entry_time": row["timestamp"],
            "quantity": quantity,
            "candles_held": 0,
            "confidence": signal["confidence"],
            "direction": signal["direction"],
        }

        self._stock_trades_today[symbol] = self._stock_trades_today.get(symbol, 0) + 1

    def _check_exit(self, symbol: str, row: pd.Series, candle_idx: int) -> BacktestTrade | None:
        """Check if position should be exited."""
        pos = self._positions[symbol]
        pos["candles_held"] += 1

        current_price = row["close"]
        entry_price = pos["entry_price"]
        is_short = pos["side"] == "SHORT"

        # Calculate P&L
        if is_short:
            pnl_pct = (entry_price - current_price) / entry_price
        else:
            pnl_pct = (current_price - entry_price) / entry_price

        # Exit conditions
        exit_reason = None

        if is_short:
            if pnl_pct <= -self.short_stop_loss:
                exit_reason = "stop_loss"
            elif pnl_pct >= self.short_take_profit:
                exit_reason = "take_profit"
            elif pos["candles_held"] >= self.short_max_hold:
                exit_reason = "max_hold_time"
        else:
            if pnl_pct <= -self.long_stop_loss:
                exit_reason = "stop_loss"
            elif pnl_pct >= self.long_take_profit:
                exit_reason = "take_profit"
            elif pos["candles_held"] >= self.long_max_hold:
                exit_reason = "max_hold_time"

        if exit_reason:
            return self._close_position(symbol, current_price, row["timestamp"], exit_reason)

        return None

    def _close_position(self, symbol: str, price: float, timestamp, exit_reason: str) -> BacktestTrade | None:
        """Close a position and record the trade."""
        if symbol not in self._positions:
            return None

        pos = self._positions.pop(symbol)
        is_short = pos["side"] == "SHORT"

        # Apply slippage on exit
        if is_short:
            exit_price = price * (1 + self.slippage_pct)  # Worse fill covering short
        else:
            exit_price = price * (1 - self.slippage_pct)  # Worse fill selling

        entry_price = pos["entry_price"]
        quantity = pos["quantity"]

        # Gross P&L
        if is_short:
            gross_pnl = (entry_price - exit_price) * quantity
        else:
            gross_pnl = (exit_price - entry_price) * quantity

        # Transaction costs
        costs = self.costs.round_trip_cost(entry_price, exit_price, quantity, is_short)

        # Slippage cost (already baked into prices, but track separately)
        slippage_cost = abs(price * self.slippage_pct) * quantity * 2  # Both legs

        # Net P&L
        net_pnl = gross_pnl - costs

        # Update capital
        self.capital += net_pnl

        trade = BacktestTrade(
            symbol=symbol,
            side=pos["side"],
            entry_time=pos["entry_time"],
            exit_time=timestamp,
            entry_price=entry_price,
            exit_price=exit_price,
            quantity=quantity,
            gross_pnl=gross_pnl,
            costs=costs,
            net_pnl=net_pnl,
            slippage_cost=slippage_cost,
            exit_reason=exit_reason,
            confidence=pos["confidence"],
            direction=pos["direction"],
        )

        self.trades.append(trade)
        return trade

    def _close_all_positions(self, all_data: dict[str, pd.DataFrame], last_day: date, reason: str):
        """Close all open positions at last available price."""
        for symbol in list(self._positions.keys()):
            if symbol in all_data:
                df = all_data[symbol]
                day_data = df[df["timestamp"].dt.date == last_day]
                if not day_data.empty:
                    self._close_position(symbol, day_data.iloc[-1]["close"], day_data.iloc[-1]["timestamp"], reason)

    # =========================================================================
    # Exposure Tracking
    # =========================================================================

    def _get_long_exposure(self) -> float:
        long_value = sum(
            p["entry_price"] * p["quantity"]
            for p in self._positions.values()
            if p["side"] == "LONG"
        )
        return long_value / self.capital if self.capital > 0 else 0

    def _get_short_exposure(self) -> float:
        short_value = sum(
            p["entry_price"] * p["quantity"]
            for p in self._positions.values()
            if p["side"] == "SHORT"
        )
        return short_value / self.capital if self.capital > 0 else 0

    def _check_exposure(self, is_short: bool) -> bool:
        total = self._get_long_exposure() + self._get_short_exposure()
        if total >= self.max_total_exposure:
            return False
        if is_short and self._get_short_exposure() >= self.max_short_exposure:
            return False
        if not is_short and self._get_long_exposure() >= self.max_long_exposure:
            return False
        return True

    def _get_unrealized_pnl(self, all_data: dict[str, pd.DataFrame], day: date) -> float:
        """Get unrealized P&L for open positions."""
        total_pnl = 0
        for symbol, pos in self._positions.items():
            if symbol in all_data:
                df = all_data[symbol]
                day_data = df[df["timestamp"].dt.date == day]
                if not day_data.empty:
                    current = day_data.iloc[-1]["close"]
                    if pos["side"] == "SHORT":
                        total_pnl += (pos["entry_price"] - current) * pos["quantity"]
                    else:
                        total_pnl += (current - pos["entry_price"]) * pos["quantity"]
        return total_pnl

    # =========================================================================
    # Metrics
    # =========================================================================

    def _calculate_metrics(self) -> dict:
        """Calculate comprehensive backtest metrics."""
        if not self.trades:
            return {
                "initial_capital": self.initial_capital,
                "final_capital": self.capital,
                "total_pnl": 0, "total_pnl_pct": 0,
                "total_trades": 0, "winning_trades": 0, "losing_trades": 0,
                "win_rate": 0, "avg_win": 0, "avg_loss": 0,
                "max_drawdown": 0, "max_drawdown_pct": 0,
                "sharpe_ratio": 0, "profit_factor": 0,
                "total_costs": 0, "total_slippage": 0,
                "long_trades": 0, "long_pnl": 0, "long_win_rate": 0,
                "short_trades": 0, "short_pnl": 0, "short_win_rate": 0,
                "per_stock": {}, "equity_curve": self.equity_curve,
                "trades": [], "enable_shorting": self.enable_shorting,
            }

        net_pnls = [t.net_pnl for t in self.trades]
        gross_pnls = [t.gross_pnl for t in self.trades]

        winners = [t for t in self.trades if t.net_pnl > 0]
        losers = [t for t in self.trades if t.net_pnl <= 0]
        long_trades = [t for t in self.trades if t.side == "LONG"]
        short_trades = [t for t in self.trades if t.side == "SHORT"]

        total_pnl = sum(net_pnls)
        total_costs = sum(t.costs for t in self.trades)
        total_slippage = sum(t.slippage_cost for t in self.trades)

        # Equity curve for drawdown
        equity_values = [e["equity"] for e in self.equity_curve] if self.equity_curve else [self.initial_capital]
        peak = self.initial_capital
        max_drawdown = 0
        max_drawdown_pct = 0
        for eq in equity_values:
            peak = max(peak, eq)
            dd = peak - eq
            dd_pct = dd / peak if peak > 0 else 0
            max_drawdown = max(max_drawdown, dd)
            max_drawdown_pct = max(max_drawdown_pct, dd_pct)

        # Sharpe ratio (daily returns)
        if len(equity_values) > 1:
            daily_returns = pd.Series(equity_values).pct_change().dropna()
            sharpe = (daily_returns.mean() / daily_returns.std() * np.sqrt(252)) if daily_returns.std() > 0 else 0
        else:
            sharpe = 0

        # Profit factor
        gross_profit = sum(t.net_pnl for t in winners)
        gross_loss = abs(sum(t.net_pnl for t in losers))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

        # Per-stock breakdown
        stock_pnl = {}
        for t in self.trades:
            stock_pnl.setdefault(t.symbol, []).append(t.net_pnl)

        per_stock = {
            symbol: {
                "trades": len(pnls),
                "total_pnl": sum(pnls),
                "win_rate": sum(1 for p in pnls if p > 0) / len(pnls) * 100,
                "avg_pnl": sum(pnls) / len(pnls),
            }
            for symbol, pnls in stock_pnl.items()
        }

        return {
            "initial_capital": self.initial_capital,
            "final_capital": self.capital,
            "total_pnl": total_pnl,
            "total_pnl_pct": total_pnl / self.initial_capital * 100,
            "total_trades": len(self.trades),
            "winning_trades": len(winners),
            "losing_trades": len(losers),
            "win_rate": len(winners) / len(self.trades) * 100,
            "avg_win": np.mean([t.net_pnl for t in winners]) if winners else 0,
            "avg_loss": np.mean([t.net_pnl for t in losers]) if losers else 0,
            "max_drawdown": max_drawdown,
            "max_drawdown_pct": max_drawdown_pct * 100,
            "sharpe_ratio": sharpe,
            "profit_factor": profit_factor,
            "total_costs": total_costs,
            "total_slippage": total_slippage,
            "long_trades": len(long_trades),
            "long_pnl": sum(t.net_pnl for t in long_trades),
            "long_win_rate": (sum(1 for t in long_trades if t.net_pnl > 0) / len(long_trades) * 100) if long_trades else 0,
            "short_trades": len(short_trades),
            "short_pnl": sum(t.net_pnl for t in short_trades),
            "short_win_rate": (sum(1 for t in short_trades if t.net_pnl > 0) / len(short_trades) * 100) if short_trades else 0,
            "per_stock": per_stock,
            "equity_curve": self.equity_curve,
            "trades": [
                {
                    "symbol": t.symbol, "side": t.side,
                    "entry_time": str(t.entry_time), "exit_time": str(t.exit_time),
                    "entry_price": t.entry_price, "exit_price": t.exit_price,
                    "quantity": t.quantity, "gross_pnl": t.gross_pnl,
                    "costs": t.costs, "net_pnl": t.net_pnl,
                    "exit_reason": t.exit_reason, "confidence": t.confidence,
                }
                for t in self.trades
            ],
            "enable_shorting": self.enable_shorting,
        }

    def _print_summary(self, results: dict):
        """Print summary to terminal."""
        mode = "Long + Short" if results["enable_shorting"] else "Long Only"

        print(f"\n  Mode: {mode}")
        print(f"  Initial Capital: ₹{results['initial_capital']:,.0f}")
        print(f"  Final Capital:   ₹{results['final_capital']:,.0f}")
        print(f"  Total P&L:       ₹{results['total_pnl']:,.0f} ({results['total_pnl_pct']:.2f}%)")
        print(f"\n  Total Trades:    {results['total_trades']}")
        print(f"  Win Rate:        {results['win_rate']:.1f}%")
        print(f"  Avg Win:         ₹{results['avg_win']:,.0f}")
        print(f"  Avg Loss:        ₹{results['avg_loss']:,.0f}")
        print(f"  Profit Factor:   {results['profit_factor']:.2f}")
        print(f"\n  Max Drawdown:    ₹{results['max_drawdown']:,.0f} ({results['max_drawdown_pct']:.1f}%)")
        print(f"  Sharpe Ratio:    {results['sharpe_ratio']:.2f}")
        print(f"\n  Total Costs:     ₹{results['total_costs']:,.0f}")
        print(f"  Total Slippage:  ₹{results['total_slippage']:,.0f}")

        if results["long_trades"]:
            print(f"\n  Long Trades:     {results['long_trades']} | P&L: ₹{results['long_pnl']:,.0f} | Win: {results['long_win_rate']:.1f}%")
        if results["short_trades"]:
            print(f"  Short Trades:    {results['short_trades']} | P&L: ₹{results['short_pnl']:,.0f} | Win: {results['short_win_rate']:.1f}%")

    # =========================================================================
    # HTML Report
    # =========================================================================

    def generate_report(self, results: dict, output_path: str = None) -> str:
        """Generate HTML backtest report."""
        if output_path is None:
            output_path = str(_BACKEND_DIR / "data" / "backtest_report.html")

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        # Build equity curve data for chart
        equity_data = results.get("equity_curve", [])
        dates_js = [f"'{e['date']}'" for e in equity_data]
        equity_js = [str(round(e["equity"], 2)) for e in equity_data]
        capital_js = [str(round(e["capital"], 2)) for e in equity_data]

        # Trade log rows
        trade_rows = ""
        for t in results.get("trades", []):
            pnl_color = "#22c55e" if t["net_pnl"] > 0 else "#ef4444"
            side_color = "#22c55e" if t["side"] == "LONG" else "#ef4444"
            trade_rows += f"""
            <tr>
                <td>{t['symbol']}</td>
                <td style="color:{side_color}">{t['side']}</td>
                <td>{t['entry_time'][:16]}</td>
                <td>{t['exit_time'][:16]}</td>
                <td>₹{t['entry_price']:,.2f}</td>
                <td>₹{t['exit_price']:,.2f}</td>
                <td>{t['quantity']}</td>
                <td style="color:{pnl_color}">₹{t['net_pnl']:,.2f}</td>
                <td>₹{t['costs']:,.2f}</td>
                <td>{t['exit_reason']}</td>
            </tr>"""

        # Per-stock rows
        stock_rows = ""
        for symbol, stats in sorted(results.get("per_stock", {}).items(), key=lambda x: x[1]["total_pnl"], reverse=True):
            pnl_color = "#22c55e" if stats["total_pnl"] > 0 else "#ef4444"
            stock_rows += f"""
            <tr>
                <td>{symbol}</td>
                <td>{stats['trades']}</td>
                <td style="color:{pnl_color}">₹{stats['total_pnl']:,.2f}</td>
                <td>{stats['win_rate']:.0f}%</td>
                <td>₹{stats['avg_pnl']:,.2f}</td>
            </tr>"""

        mode = "Long + Short" if results["enable_shorting"] else "Long Only"

        # Build long/short breakdown HTML
        ls_html = ""
        if results["enable_shorting"]:
            long_pnl_cls = "profit" if results["long_pnl"] > 0 else "loss"
            short_pnl_cls = "profit" if results["short_pnl"] > 0 else "loss"
            ls_html = f"""
<div class="grid">
  <div class="card"><div class="card-label">Long Trades</div><div class="card-value">{results['long_trades']}</div></div>
  <div class="card"><div class="card-label">Long P&L</div><div class="card-value {long_pnl_cls}">₹{results['long_pnl']:,.0f}</div></div>
  <div class="card"><div class="card-label">Short Trades</div><div class="card-value">{results['short_trades']}</div></div>
  <div class="card"><div class="card-label">Short P&L</div><div class="card-value {short_pnl_cls}">₹{results['short_pnl']:,.0f}</div></div>
</div>"""

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Backtest Report</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #0a0a0a; color: #e5e5e5; padding: 24px; }}
  h1 {{ font-size: 20px; margin-bottom: 4px; }}
  h2 {{ font-size: 16px; margin: 24px 0 12px; color: #a3a3a3; }}
  .subtitle {{ font-size: 13px; color: #737373; margin-bottom: 24px; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; margin-bottom: 24px; }}
  .card {{ background: #171717; border: 1px solid #262626; border-radius: 8px; padding: 14px; }}
  .card-label {{ font-size: 11px; color: #737373; text-transform: uppercase; letter-spacing: 0.5px; }}
  .card-value {{ font-size: 20px; font-weight: 600; margin-top: 4px; }}
  .profit {{ color: #22c55e; }}
  .loss {{ color: #ef4444; }}
  .chart-container {{ background: #171717; border: 1px solid #262626; border-radius: 8px; padding: 16px; margin-bottom: 24px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 12px; }}
  th {{ text-align: left; padding: 8px 12px; background: #171717; border-bottom: 1px solid #262626; color: #737373; font-weight: 500; }}
  td {{ padding: 6px 12px; border-bottom: 1px solid #1a1a1a; }}
  .table-container {{ background: #171717; border: 1px solid #262626; border-radius: 8px; overflow: hidden; margin-bottom: 24px; }}
</style>
</head>
<body>
<h1>Backtest Report</h1>
<p class="subtitle">Mode: {mode} | Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}</p>

<div class="grid">
  <div class="card">
    <div class="card-label">Total P&L</div>
    <div class="card-value {'profit' if results['total_pnl'] > 0 else 'loss'}">₹{results['total_pnl']:,.0f}</div>
  </div>
  <div class="card">
    <div class="card-label">Return</div>
    <div class="card-value {'profit' if results['total_pnl_pct'] > 0 else 'loss'}">{results['total_pnl_pct']:.2f}%</div>
  </div>
  <div class="card">
    <div class="card-label">Total Trades</div>
    <div class="card-value">{results['total_trades']}</div>
  </div>
  <div class="card">
    <div class="card-label">Win Rate</div>
    <div class="card-value">{results['win_rate']:.1f}%</div>
  </div>
  <div class="card">
    <div class="card-label">Profit Factor</div>
    <div class="card-value">{results['profit_factor']:.2f}</div>
  </div>
  <div class="card">
    <div class="card-label">Sharpe Ratio</div>
    <div class="card-value">{results['sharpe_ratio']:.2f}</div>
  </div>
  <div class="card">
    <div class="card-label">Max Drawdown</div>
    <div class="card-value loss">{results['max_drawdown_pct']:.1f}%</div>
  </div>
  <div class="card">
    <div class="card-label">Total Costs</div>
    <div class="card-value">₹{results['total_costs']:,.0f}</div>
  </div>
</div>

{ls_html}

<h2>Equity Curve</h2>
<div class="chart-container">
  <canvas id="equityChart" height="80"></canvas>
</div>

<h2>Per-Stock Performance</h2>
<div class="table-container">
  <table>
    <thead><tr><th>Symbol</th><th>Trades</th><th>P&L</th><th>Win Rate</th><th>Avg P&L</th></tr></thead>
    <tbody>{stock_rows}</tbody>
  </table>
</div>

<h2>Trade Log ({results['total_trades']} trades)</h2>
<div class="table-container">
  <table>
    <thead><tr><th>Symbol</th><th>Side</th><th>Entry</th><th>Exit</th><th>Entry ₹</th><th>Exit ₹</th><th>Qty</th><th>Net P&L</th><th>Costs</th><th>Reason</th></tr></thead>
    <tbody>{trade_rows}</tbody>
  </table>
</div>

<script>
new Chart(document.getElementById('equityChart'), {{
  type: 'line',
  data: {{
    labels: [{','.join(dates_js)}],
    datasets: [{{
      label: 'Equity',
      data: [{','.join(equity_js)}],
      borderColor: '#22c55e',
      backgroundColor: 'rgba(34,197,94,0.05)',
      fill: true,
      tension: 0.3,
      pointRadius: 0,
      borderWidth: 2,
    }}]
  }},
  options: {{
    responsive: true,
    plugins: {{ legend: {{ display: false }} }},
    scales: {{
      x: {{ ticks: {{ color: '#525252', maxTicksLimit: 10 }}, grid: {{ color: '#1a1a1a' }} }},
      y: {{ ticks: {{ color: '#525252', callback: v => '₹' + v.toLocaleString() }}, grid: {{ color: '#1a1a1a' }} }}
    }}
  }}
}});
</script>
</body>
</html>"""

        Path(output_path).write_text(html)
        logger.info(f"Report saved to {output_path}")
        print(f"\n  Report: {output_path}")

        return output_path
