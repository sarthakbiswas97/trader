"""
Breakout Strategy Backtester.

Tests the breakout/breakdown strategy on historical data
with real Zerodha costs and slippage.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import math
import numpy as np
import pandas as pd

from backend.core.logger import get_logger
from backend.core.symbols import NIFTY_50
from backend.services.backtester import ZerodhaCosts, BacktestTrade
from backend.services.historical_data import HistoricalDataService
from backend.strategies.breakout.detector import BreakoutDetector, Setup
from backend.strategies.breakout.filters import filter_setups
from backend.strategies.breakout.market_regime import MarketRegime
from backend.strategies.breakout.scorer import SetupScorer, SCORER_PATH

logger = get_logger(__name__)

_BACKEND_DIR = Path(__file__).parent.parent.parent


class BreakoutBacktester:
    """
    Backtest the breakout strategy on historical 5-min data.

    For each trading day:
      1. Load previous day's high/low
      2. Scan today's candles for setups
      3. Execute trades on detected setups
      4. Manage exits (ATR-based SL, time-based, target)
    """

    def __init__(
        self,
        capital: float = 100000.0,
        max_trades_per_day: int = 5,
        max_position_pct: float = 0.05,
        sl_atr_multiplier: float = 1.5,     # Stop-loss = entry ± 1.5 * ATR
        tp_atr_multiplier: float = 2.5,     # Take-profit = entry ± 2.5 * ATR
        max_hold_candles: int = 24,          # 2 hours max hold
        slippage_pct: float = 0.0005,
        enable_shorting: bool = True,
        symbols: list[str] = None,
        test_start_date: date | None = None,
        test_end_date: date | None = None,
    ):
        self.initial_capital = capital
        self.capital = capital
        self.max_trades_per_day = max_trades_per_day
        self.max_position_pct = max_position_pct
        self.sl_atr_mult = sl_atr_multiplier
        self.tp_atr_mult = tp_atr_multiplier
        self.max_hold_candles = max_hold_candles
        self.slippage_pct = slippage_pct
        self.enable_shorting = enable_shorting
        self.symbols = symbols or NIFTY_50
        self.test_start_date = test_start_date
        self.test_end_date = test_end_date

        self.costs = ZerodhaCosts()
        self.detector = BreakoutDetector()
        self.market_regime = MarketRegime()
        self.scorer = SetupScorer() if SCORER_PATH.exists() else None
        self.ml_threshold = 0.5  # Min ML score to trade
        self.trades: list[BacktestTrade] = []
        self.equity_curve: list[dict] = []
        self._positions: dict[str, dict] = {}
        self._trades_today: set[str] = set()
        self._scanned_today: set[str] = set()  # Stocks already scanned (avoid re-scanning)

    def run(self) -> dict:
        """Run the backtest."""
        print("=" * 60)
        print("BREAKOUT STRATEGY BACKTEST")
        print("=" * 60)

        # Load all data
        ds = HistoricalDataService()
        all_data = {}

        for symbol in self.symbols:
            df = ds.load_candles(symbol, "5m")
            if not df.empty and len(df) >= 50:
                all_data[symbol] = df

        if not all_data:
            raise RuntimeError("No data loaded")

        # Get trading days
        all_dates = set()
        for df in all_data.values():
            all_dates.update(df["timestamp"].dt.date.unique())
        trading_days = sorted(all_dates)

        # Apply date filters
        if self.test_start_date:
            trading_days = [d for d in trading_days if d >= self.test_start_date]
        if self.test_end_date:
            trading_days = [d for d in trading_days if d <= self.test_end_date]

        if len(trading_days) < 2:
            raise RuntimeError("Need at least 2 trading days")

        print(f"\n  Stocks: {len(all_data)}")
        print(f"  Trading days: {len(trading_days)}")
        print(f"  Period: {trading_days[0]} to {trading_days[-1]}")
        print(f"  Mode: {'Long + Short' if self.enable_shorting else 'Long Only'}")
        print(f"  SL: {self.sl_atr_mult}x ATR, TP: {self.tp_atr_mult}x ATR")

        # Load market regime
        self.market_regime.load()
        print(f"  Regime: NIFTY 50 index loaded")

        # Simulate day by day
        for day_idx in range(1, len(trading_days)):
            today = trading_days[day_idx]
            yesterday = trading_days[day_idx - 1]
            self._trades_today.clear()
            self._scanned_today.clear()

            # Get previous day's high/low per stock
            prev_day_levels = {}
            for symbol, df in all_data.items():
                prev_candles = df[df["timestamp"].dt.date == yesterday]
                if not prev_candles.empty:
                    prev_day_levels[symbol] = {
                        "high": prev_candles["high"].max(),
                        "low": prev_candles["low"].min(),
                    }

            # Get today's candles per stock
            today_data = {}
            for symbol, df in all_data.items():
                today_candles = df[df["timestamp"].dt.date == today]
                if len(today_candles) >= 5:
                    today_data[symbol] = today_candles

            # Check market regime — skip non-trending days
            regime_info = self.market_regime.get_info(today)
            if not self.market_regime.should_trade(today):
                # Still manage existing positions even on non-trending days
                day_trades = self._manage_positions_only(today, today_data)
            else:
                # Determine allowed directions from market
                allow_longs = self.market_regime.allow_longs(today) and self.enable_shorting  # enable_shorting controls both
                allow_shorts = self.market_regime.allow_shorts(today) and self.enable_shorting

                # If enable_shorting is False, only allow longs when market is UP
                if not self.enable_shorting:
                    allow_longs = self.market_regime.get_direction(today) == "UP"
                    allow_shorts = False

                # Scan for setups + manage positions
                day_trades = self._simulate_day(today, today_data, prev_day_levels, allow_longs, allow_shorts)

            # Record equity
            self.equity_curve.append({
                "date": today,
                "capital": self.capital,
                "equity": self.capital,
                "trades_today": len(day_trades),
            })

            if day_trades:
                pnl = self.capital - self.initial_capital
                setups_str = ", ".join(f"{t.symbol}({t.side})" for t in day_trades[:3])
                print(f"  {today}: ₹{self.capital:,.0f} | P&L ₹{pnl:,.0f} | Trades: {len(day_trades)} [{setups_str}]")

        # Close remaining positions
        for symbol in list(self._positions.keys()):
            for sym, df in all_data.items():
                if sym == symbol:
                    last_row = df.iloc[-1]
                    self._close_position(symbol, last_row["close"], last_row["timestamp"], "backtest_end")

        # Results
        results = self._calculate_metrics()
        self._print_summary(results)

        return results

    def _manage_positions_only(
        self,
        today: date,
        today_data: dict[str, pd.DataFrame],
    ) -> list[BacktestTrade]:
        """On non-trending days, only manage existing positions (exits)."""
        day_trades = []
        for symbol in list(self._positions.keys()):
            if symbol in today_data:
                for _, row in today_data[symbol].iterrows():
                    if symbol in self._positions:
                        trade = self._check_exit(symbol, row)
                        if trade:
                            day_trades.append(trade)
                # Force close at end of day
                if symbol in self._positions:
                    last = today_data[symbol].iloc[-1]
                    trade = self._close_position(symbol, last["close"], last["timestamp"], "market_close")
                    if trade:
                        day_trades.append(trade)
        return day_trades

    def _simulate_day(
        self,
        today: date,
        today_data: dict[str, pd.DataFrame],
        prev_levels: dict[str, dict],
        allow_longs: bool = True,
        allow_shorts: bool = True,
    ) -> list[BacktestTrade]:
        """Simulate one trading day with direction-aware entries."""
        day_trades = []

        all_candles = []
        for symbol, df in today_data.items():
            for _, row in df.iterrows():
                all_candles.append((row["timestamp"], symbol, row))

        all_candles.sort(key=lambda x: x[0])

        stock_candle_buffers: dict[str, list] = {s: [] for s in today_data}

        for ts, symbol, row in all_candles:
            stock_candle_buffers[symbol].append(row)

            # 1. Check exits for existing positions
            if symbol in self._positions:
                trade = self._check_exit(symbol, row)
                if trade:
                    day_trades.append(trade)
                    continue

            # 2. Detect new setups — scan each stock ONCE per day
            if (symbol not in self._positions
                    and symbol not in self._trades_today
                    and symbol not in self._scanned_today
                    and len(stock_candle_buffers[symbol]) >= 15  # Need enough data for indicators
                    and len(self._trades_today) < self.max_trades_per_day):

                self._scanned_today.add(symbol)

                buffer_df = pd.DataFrame(stock_candle_buffers[symbol])
                prev = prev_levels.get(symbol, {})
                pdh = prev.get("high", float("inf"))
                pdl = prev.get("low", 0)

                setups = self.detector.scan(symbol, buffer_df, pdh, pdl)

                if setups:
                    # Filter by quality
                    filtered = filter_setups(
                        setups,
                        already_traded_today=self._trades_today,
                        held_symbols=set(self._positions.keys()),
                    )

                    # Direction filter from market regime
                    direction_filtered = []
                    for s in filtered:
                        if s.direction == "LONG" and allow_longs:
                            direction_filtered.append(s)
                        elif s.direction == "SHORT" and allow_shorts:
                            direction_filtered.append(s)

                    if not direction_filtered:
                        continue

                    # ML scoring: pick best setup by predicted follow-through probability
                    if self.scorer:
                        regime_info = self.market_regime.get_info(today)
                        best_setup = None
                        best_score = 0

                        for s in direction_filtered:
                            features = {
                                "breakout_strength": abs(s.trigger_price - s.reference_level) / s.reference_level if s.reference_level > 0 else 0,
                                "volume_ratio": s.volume_ratio if not np.isnan(s.volume_ratio) else 1.0,
                                "candle_strength": s.candle_strength,
                                "consolidation_tightness": s.consolidation_tightness,
                                "atr_pct": s.atr / s.trigger_price if s.trigger_price > 0 else 0,
                                "market_adx": regime_info.get("adx", 0),
                                "market_trend_strength": regime_info.get("trend_strength", 0),
                                "direction_aligned": 1 if (
                                    (s.direction == "LONG" and regime_info.get("direction") == "UP") or
                                    (s.direction == "SHORT" and regime_info.get("direction") == "DOWN")
                                ) else 0,
                                "hour": ts.hour if hasattr(ts, "hour") else 10,
                                "is_opening": 1 if s.setup_type == "opening" else 0,
                                "is_short": 1 if s.direction == "SHORT" else 0,
                                "score": s.score,
                            }

                            ml_score = self.scorer.score(features)
                            if ml_score > best_score:
                                best_score = ml_score
                                best_setup = s

                        if best_setup and best_score >= self.ml_threshold:
                            self._enter_position(best_setup, row)
                    else:
                        # No scorer — use rule-based ranking
                        from backend.strategies.breakout.ranker import rank_setups
                        ranked = rank_setups(direction_filtered, max_trades=1)
                        if ranked:
                            self._enter_position(ranked[0], row)

        # Force close remaining positions at end of day
        for symbol in list(self._positions.keys()):
            if symbol in today_data:
                last_row = today_data[symbol].iloc[-1]
                trade = self._close_position(symbol, last_row["close"], last_row["timestamp"], "market_close")
                if trade:
                    day_trades.append(trade)

        return day_trades

    def _enter_position(self, setup: Setup, row: pd.Series) -> None:
        """Enter a position based on a detected setup."""
        price = setup.trigger_price
        is_short = setup.direction == "SHORT"

        # Position sizing
        max_alloc = self.capital * self.max_position_pct
        quantity = int(max_alloc / price)
        if quantity <= 0 or quantity * price < 1000:
            return

        # Slippage
        if is_short:
            entry_price = price * (1 - self.slippage_pct)
        else:
            entry_price = price * (1 + self.slippage_pct)

        # ATR-based stops
        atr = setup.atr if setup.atr > 0 else entry_price * 0.005
        if is_short:
            stop_loss = entry_price + atr * self.sl_atr_mult
            take_profit = entry_price - atr * self.tp_atr_mult
        else:
            stop_loss = entry_price - atr * self.sl_atr_mult
            take_profit = entry_price + atr * self.tp_atr_mult

        self._positions[setup.symbol] = {
            "side": setup.direction,
            "entry_price": entry_price,
            "entry_time": setup.timestamp,
            "quantity": quantity,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "atr": atr,
            "candles_held": 0,
            "setup_type": setup.setup_type,
            "setup_score": setup.score,
        }

        self._trades_today.add(setup.symbol)

    def _check_exit(self, symbol: str, row: pd.Series) -> BacktestTrade | None:
        """Check exit conditions with trailing stop-loss."""
        pos = self._positions[symbol]
        pos["candles_held"] += 1

        price = row["close"]
        high = row["high"]
        low = row["low"]
        is_short = pos["side"] == "SHORT"
        entry = pos["entry_price"]
        atr = pos.get("atr", abs(entry * 0.005))

        # Trailing SL: move stop to breakeven after 1 ATR profit
        if is_short:
            max_favorable = entry - low  # Best price for short
            if max_favorable >= atr:
                # Move SL to breakeven (entry price)
                pos["stop_loss"] = min(pos["stop_loss"], entry)
        else:
            max_favorable = high - entry  # Best price for long
            if max_favorable >= atr:
                pos["stop_loss"] = max(pos["stop_loss"], entry)

        exit_reason = None

        if is_short:
            if high >= pos["stop_loss"]:
                exit_reason = "stop_loss"
                price = pos["stop_loss"]
            elif low <= pos["take_profit"]:
                exit_reason = "take_profit"
                price = pos["take_profit"]
        else:
            if low <= pos["stop_loss"]:
                exit_reason = "stop_loss"
                price = pos["stop_loss"]
            elif high >= pos["take_profit"]:
                exit_reason = "take_profit"
                price = pos["take_profit"]

        # Max hold time
        if not exit_reason and pos["candles_held"] >= self.max_hold_candles:
            exit_reason = "max_hold_time"

        if exit_reason:
            return self._close_position(symbol, price, row["timestamp"], exit_reason)

        return None

    def _close_position(self, symbol: str, price: float, timestamp, reason: str) -> BacktestTrade | None:
        """Close position and record trade."""
        if symbol not in self._positions:
            return None

        pos = self._positions.pop(symbol)
        is_short = pos["side"] == "SHORT"

        # Slippage on exit
        if is_short:
            exit_price = price * (1 + self.slippage_pct)
        else:
            exit_price = price * (1 - self.slippage_pct)

        entry_price = pos["entry_price"]
        quantity = pos["quantity"]

        if is_short:
            gross_pnl = (entry_price - exit_price) * quantity
        else:
            gross_pnl = (exit_price - entry_price) * quantity

        costs = self.costs.round_trip_cost(entry_price, exit_price, quantity, is_short)
        slippage_cost = abs(price * self.slippage_pct) * quantity * 2
        net_pnl = gross_pnl - costs

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
            exit_reason=reason,
            confidence=pos["setup_score"],
            direction=pos["side"],
        )

        self.trades.append(trade)
        return trade

    def _calculate_metrics(self) -> dict:
        """Calculate metrics (reuses logic from main backtester)."""
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
                "exit_reasons": {},
            }

        winners = [t for t in self.trades if t.net_pnl > 0]
        losers = [t for t in self.trades if t.net_pnl <= 0]
        long_trades = [t for t in self.trades if t.side == "LONG"]
        short_trades = [t for t in self.trades if t.side == "SHORT"]

        total_pnl = sum(t.net_pnl for t in self.trades)
        gross_profit = sum(t.net_pnl for t in winners) if winners else 0
        gross_loss = abs(sum(t.net_pnl for t in losers)) if losers else 0
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

        # Drawdown
        equity_values = [e["equity"] for e in self.equity_curve] if self.equity_curve else [self.initial_capital]
        peak = self.initial_capital
        max_dd = 0
        for eq in equity_values:
            peak = max(peak, eq)
            max_dd = max(max_dd, (peak - eq) / peak if peak > 0 else 0)

        # Sharpe
        if len(equity_values) > 1:
            returns = pd.Series(equity_values).pct_change().dropna()
            sharpe = (returns.mean() / returns.std() * np.sqrt(252)) if returns.std() > 0 else 0
        else:
            sharpe = 0

        # Exit reason breakdown
        exit_reasons = {}
        for t in self.trades:
            exit_reasons[t.exit_reason] = exit_reasons.get(t.exit_reason, 0) + 1

        # Per-stock
        stock_pnl = {}
        for t in self.trades:
            stock_pnl.setdefault(t.symbol, []).append(t.net_pnl)
        per_stock = {
            sym: {"trades": len(pnls), "total_pnl": sum(pnls), "win_rate": sum(1 for p in pnls if p > 0) / len(pnls) * 100}
            for sym, pnls in stock_pnl.items()
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
            "max_drawdown": max_dd * self.initial_capital,
            "max_drawdown_pct": max_dd * 100,
            "sharpe_ratio": sharpe,
            "profit_factor": profit_factor,
            "total_costs": sum(t.costs for t in self.trades),
            "total_slippage": sum(t.slippage_cost for t in self.trades),
            "long_trades": len(long_trades),
            "long_pnl": sum(t.net_pnl for t in long_trades),
            "long_win_rate": (sum(1 for t in long_trades if t.net_pnl > 0) / len(long_trades) * 100) if long_trades else 0,
            "short_trades": len(short_trades),
            "short_pnl": sum(t.net_pnl for t in short_trades),
            "short_win_rate": (sum(1 for t in short_trades if t.net_pnl > 0) / len(short_trades) * 100) if short_trades else 0,
            "per_stock": per_stock,
            "equity_curve": self.equity_curve,
            "exit_reasons": exit_reasons,
            "enable_shorting": self.enable_shorting,
            "trades": [
                {
                    "symbol": t.symbol, "side": t.side,
                    "entry_time": str(t.entry_time), "exit_time": str(t.exit_time),
                    "entry_price": t.entry_price, "exit_price": t.exit_price,
                    "quantity": t.quantity, "net_pnl": t.net_pnl,
                    "costs": t.costs, "exit_reason": t.exit_reason,
                }
                for t in self.trades
            ],
        }

    def _print_summary(self, results: dict):
        mode = "Long + Short" if results["enable_shorting"] else "Long Only"
        print(f"\n{'='*60}")
        print(f"BREAKOUT BACKTEST COMPLETE")
        print(f"{'='*60}")
        print(f"\n  Mode: {mode}")
        print(f"  Initial: ₹{results['initial_capital']:,.0f}")
        print(f"  Final:   ₹{results['final_capital']:,.0f}")
        print(f"  P&L:     ₹{results['total_pnl']:,.0f} ({results['total_pnl_pct']:.2f}%)")
        print(f"\n  Trades:  {results['total_trades']}")
        print(f"  Win Rate: {results['win_rate']:.1f}%")
        print(f"  Avg Win:  ₹{results['avg_win']:,.0f}")
        print(f"  Avg Loss: ₹{results['avg_loss']:,.0f}")
        print(f"  PF:       {results['profit_factor']:.2f}")
        print(f"  Sharpe:   {results['sharpe_ratio']:.2f}")
        print(f"  Max DD:   {results['max_drawdown_pct']:.1f}%")
        print(f"  Costs:    ₹{results['total_costs']:,.0f}")

        if results.get("exit_reasons"):
            print(f"\n  Exit Reasons:")
            for reason, count in sorted(results["exit_reasons"].items(), key=lambda x: -x[1]):
                print(f"    {reason}: {count}")

        if results["long_trades"]:
            print(f"\n  Long:  {results['long_trades']} trades | ₹{results['long_pnl']:,.0f} | {results['long_win_rate']:.0f}% win")
        if results["short_trades"]:
            print(f"  Short: {results['short_trades']} trades | ₹{results['short_pnl']:,.0f} | {results['short_win_rate']:.0f}% win")
