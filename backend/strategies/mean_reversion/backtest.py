"""
Mean Reversion Strategy Backtester.

Entry: Stock is overextended (far from VWAP, extreme RSI)
Target: Revert toward VWAP (partial reversion)
Stop: Further extension beyond entry
"""

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from backend.core.logger import get_logger
from backend.core.symbols import NIFTY_100
from backend.services.backtester import ZerodhaCosts, BacktestTrade
from backend.services.historical_data import HistoricalDataService
from backend.strategies.mean_reversion.detector import MeanReversionDetector, MeanReversionSetup

logger = get_logger(__name__)


class MeanReversionBacktester:
    """
    Backtest mean-reversion strategy on historical data.

    For each trading day:
      1. Scan stocks every 5-min bar for overextension
      2. Enter when overextended (far from VWAP + RSI extreme)
      3. Exit when: price reverts toward VWAP (TP), extends further (SL), or time expires
    """

    def __init__(
        self,
        capital: float = 100000.0,
        max_trades_per_day: int = 8,
        max_position_pct: float = 0.05,
        tp_reversion_pct: float = 0.5,   # Take profit at 50% reversion toward VWAP
        sl_extension_pct: float = 0.5,   # Stop loss at 50% further extension
        max_hold_candles: int = 12,      # 1 hour max hold (mean reversion should be fast)
        slippage_pct: float = 0.0005,
        enable_shorting: bool = True,
        min_score: float = 20,           # Minimum overextension score
        cooldown_candles: int = 6,       # 30 min cooldown per stock
        max_concurrent: int = 4,
        symbols: list[str] = None,
    ):
        self.initial_capital = capital
        self.capital = capital
        self.max_trades_per_day = max_trades_per_day
        self.max_position_pct = max_position_pct
        self.tp_reversion_pct = tp_reversion_pct
        self.sl_extension_pct = sl_extension_pct
        self.max_hold_candles = max_hold_candles
        self.slippage_pct = slippage_pct
        self.enable_shorting = enable_shorting
        self.min_score = min_score
        self.cooldown_candles = cooldown_candles
        self.max_concurrent = max_concurrent
        self.symbols = symbols or NIFTY_100

        self.costs = ZerodhaCosts()
        self.detector = MeanReversionDetector()
        self.trades: list[BacktestTrade] = []
        self.equity_curve: list[dict] = []
        self._positions: dict[str, dict] = {}
        self._trades_today: set[str] = set()
        self._last_exit: dict[str, int] = {}  # symbol → candle index of last exit

    def run(self) -> dict:
        """Run the full backtest."""
        print("=" * 60)
        print("MEAN REVERSION BACKTEST")
        print("=" * 60)

        ds = HistoricalDataService()
        all_data = {}

        for symbol in self.symbols:
            df = ds.load_candles(symbol, "5m")
            if not df.empty and len(df) >= 50:
                df["timestamp"] = pd.to_datetime(df["timestamp"])
                all_data[symbol] = df

        if not all_data:
            raise RuntimeError("No data loaded")

        # Get trading days
        all_dates = set()
        for df in all_data.values():
            all_dates.update(df["timestamp"].dt.date.unique())
        trading_days = sorted(all_dates)

        print(f"\n  Stocks: {len(all_data)}")
        print(f"  Trading days: {len(trading_days)}")
        print(f"  Period: {trading_days[0]} to {trading_days[-1]}")
        print(f"  TP: {self.tp_reversion_pct*100:.0f}% reversion toward VWAP")
        print(f"  SL: {self.sl_extension_pct*100:.0f}% further extension")
        print(f"  Max hold: {self.max_hold_candles} candles ({self.max_hold_candles * 5} min)")

        for today in trading_days:
            self._trades_today.clear()
            self._last_exit.clear()
            day_trades = []

            for symbol, df in all_data.items():
                today_candles = df[df["timestamp"].dt.date == today]
                if len(today_candles) < 15:
                    continue

                candle_buffer = []

                for i, (_, row) in enumerate(today_candles.iterrows()):
                    candle_buffer.append(row)

                    # Check exits
                    if symbol in self._positions:
                        trade = self._check_exit(symbol, row, i)
                        if trade:
                            day_trades.append(trade)
                            self._last_exit[symbol] = i

                    # Check entries (only if enough candles + not holding + cooldown)
                    if (symbol not in self._positions
                            and symbol not in self._trades_today
                            and len(candle_buffer) >= 30
                            and len(self._positions) < self.max_concurrent
                            and len(self._trades_today) < self.max_trades_per_day):

                        # Cooldown check
                        last_exit_candle = self._last_exit.get(symbol, -100)
                        if i - last_exit_candle < self.cooldown_candles:
                            continue

                        buffer_df = pd.DataFrame(candle_buffer)
                        setups = self.detector.scan(symbol, buffer_df)

                        for setup in setups:
                            if setup.overextension_score >= self.min_score:
                                if setup.direction == "SHORT" and not self.enable_shorting:
                                    continue
                                self._enter(setup, row)
                                break

                # Force close at end of day
                if symbol in self._positions:
                    last = today_candles.iloc[-1]
                    trade = self._close(symbol, last["close"], last["timestamp"], "market_close")
                    if trade:
                        day_trades.append(trade)

            # Record equity
            self.equity_curve.append({
                "date": today,
                "capital": self.capital,
                "equity": self.capital,
                "trades_today": len(day_trades),
            })

            if day_trades:
                pnl = self.capital - self.initial_capital
                symbols_str = ", ".join(f"{t.symbol}({t.side})" for t in day_trades[:3])
                print(f"  {today}: ₹{self.capital:,.0f} | P&L ₹{pnl:,.0f} | Trades: {len(day_trades)} [{symbols_str}]")

        # Close remaining
        for symbol in list(self._positions.keys()):
            for sym, df in all_data.items():
                if sym == symbol:
                    last = df.iloc[-1]
                    self._close(symbol, last["close"], last["timestamp"], "backtest_end")

        results = self._calculate_metrics()
        self._print_summary(results)
        return results

    def _enter(self, setup: MeanReversionSetup, row: pd.Series) -> None:
        """Enter a mean-reversion position."""
        price = setup.trigger_price
        is_short = setup.direction == "SHORT"

        max_alloc = self.capital * self.max_position_pct
        quantity = int(max_alloc / price)
        if quantity <= 0 or quantity * price < 1000:
            return

        if is_short:
            entry_price = price * (1 - self.slippage_pct)
        else:
            entry_price = price * (1 + self.slippage_pct)

        # Calculate TP and SL based on VWAP distance
        vwap = setup.vwap
        distance_to_vwap = abs(entry_price - vwap)

        if is_short:
            # Short the rip: TP when price drops toward VWAP
            tp_price = entry_price - distance_to_vwap * self.tp_reversion_pct
            sl_price = entry_price + distance_to_vwap * self.sl_extension_pct
        else:
            # Long the dip: TP when price rises toward VWAP
            tp_price = entry_price + distance_to_vwap * self.tp_reversion_pct
            sl_price = entry_price - distance_to_vwap * self.sl_extension_pct

        self._positions[setup.symbol] = {
            "side": setup.direction,
            "entry_price": entry_price,
            "entry_time": setup.timestamp,
            "quantity": quantity,
            "tp_price": tp_price,
            "sl_price": sl_price,
            "vwap_at_entry": vwap,
            "candles_held": 0,
            "score": setup.overextension_score,
        }

        self._trades_today.add(setup.symbol)

    def _check_exit(self, symbol: str, row: pd.Series, candle_idx: int) -> BacktestTrade | None:
        """Check exit conditions."""
        pos = self._positions[symbol]
        pos["candles_held"] += 1

        high = row["high"]
        low = row["low"]
        is_short = pos["side"] == "SHORT"

        exit_reason = None
        exit_price = row["close"]

        if is_short:
            if low <= pos["tp_price"]:
                exit_reason = "take_profit"
                exit_price = pos["tp_price"]
            elif high >= pos["sl_price"]:
                exit_reason = "stop_loss"
                exit_price = pos["sl_price"]
        else:
            if high >= pos["tp_price"]:
                exit_reason = "take_profit"
                exit_price = pos["tp_price"]
            elif low <= pos["sl_price"]:
                exit_reason = "stop_loss"
                exit_price = pos["sl_price"]

        if not exit_reason and pos["candles_held"] >= self.max_hold_candles:
            exit_reason = "max_hold_time"

        if exit_reason:
            return self._close(symbol, exit_price, row["timestamp"], exit_reason)

        return None

    def _close(self, symbol: str, price: float, timestamp, reason: str) -> BacktestTrade | None:
        """Close position and record trade."""
        if symbol not in self._positions:
            return None

        pos = self._positions.pop(symbol)
        is_short = pos["side"] == "SHORT"

        if is_short:
            exit_price = price * (1 + self.slippage_pct)
            gross_pnl = (pos["entry_price"] - exit_price) * pos["quantity"]
        else:
            exit_price = price * (1 - self.slippage_pct)
            gross_pnl = (exit_price - pos["entry_price"]) * pos["quantity"]

        costs = self.costs.round_trip_cost(pos["entry_price"], exit_price, pos["quantity"], is_short)
        net_pnl = gross_pnl - costs
        slippage_cost = abs(price * self.slippage_pct) * pos["quantity"] * 2

        self.capital += net_pnl

        trade = BacktestTrade(
            symbol=symbol,
            side=pos["side"],
            entry_time=pos["entry_time"],
            exit_time=timestamp,
            entry_price=pos["entry_price"],
            exit_price=exit_price,
            quantity=pos["quantity"],
            gross_pnl=gross_pnl,
            costs=costs,
            net_pnl=net_pnl,
            slippage_cost=slippage_cost,
            exit_reason=reason,
            confidence=pos["score"],
            direction=pos["side"],
        )

        self.trades.append(trade)
        return trade

    def _calculate_metrics(self) -> dict:
        """Calculate backtest metrics."""
        if not self.trades:
            return {
                "initial_capital": self.initial_capital,
                "final_capital": self.capital,
                "total_pnl": 0, "total_pnl_pct": 0,
                "total_trades": 0, "winning_trades": 0, "losing_trades": 0,
                "win_rate": 0, "avg_win": 0, "avg_loss": 0,
                "max_drawdown_pct": 0, "sharpe_ratio": 0, "profit_factor": 0,
                "total_costs": 0, "total_slippage": 0,
                "long_trades": 0, "long_pnl": 0, "long_win_rate": 0,
                "short_trades": 0, "short_pnl": 0, "short_win_rate": 0,
                "per_stock": {}, "equity_curve": self.equity_curve,
                "exit_reasons": {}, "enable_shorting": self.enable_shorting,
                "trades": [],
            }

        winners = [t for t in self.trades if t.net_pnl > 0]
        losers = [t for t in self.trades if t.net_pnl <= 0]
        long_t = [t for t in self.trades if t.side == "LONG"]
        short_t = [t for t in self.trades if t.side == "SHORT"]

        total_pnl = sum(t.net_pnl for t in self.trades)
        gp = sum(t.net_pnl for t in winners) if winners else 0
        gl = abs(sum(t.net_pnl for t in losers)) if losers else 0
        pf = gp / gl if gl > 0 else float("inf")

        eq = [e["equity"] for e in self.equity_curve] if self.equity_curve else [self.initial_capital]
        peak = self.initial_capital
        max_dd = 0
        for e in eq:
            peak = max(peak, e)
            max_dd = max(max_dd, (peak - e) / peak if peak > 0 else 0)

        if len(eq) > 1:
            returns = pd.Series(eq).pct_change().dropna()
            sharpe = (returns.mean() / returns.std() * np.sqrt(252)) if returns.std() > 0 else 0
        else:
            sharpe = 0

        exit_reasons = {}
        for t in self.trades:
            exit_reasons[t.exit_reason] = exit_reasons.get(t.exit_reason, 0) + 1

        stock_pnl = {}
        for t in self.trades:
            stock_pnl.setdefault(t.symbol, []).append(t.net_pnl)
        per_stock = {
            s: {"trades": len(p), "total_pnl": sum(p), "win_rate": sum(1 for x in p if x > 0)/len(p)*100, "avg_pnl": sum(p)/len(p)}
            for s, p in stock_pnl.items()
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
            "max_drawdown_pct": max_dd * 100,
            "sharpe_ratio": sharpe,
            "profit_factor": pf,
            "total_costs": sum(t.costs for t in self.trades),
            "total_slippage": sum(t.slippage_cost for t in self.trades),
            "long_trades": len(long_t),
            "long_pnl": sum(t.net_pnl for t in long_t),
            "long_win_rate": (sum(1 for t in long_t if t.net_pnl > 0) / len(long_t) * 100) if long_t else 0,
            "short_trades": len(short_t),
            "short_pnl": sum(t.net_pnl for t in short_t),
            "short_win_rate": (sum(1 for t in short_t if t.net_pnl > 0) / len(short_t) * 100) if short_t else 0,
            "per_stock": per_stock,
            "equity_curve": self.equity_curve,
            "exit_reasons": exit_reasons,
            "enable_shorting": self.enable_shorting,
            "trades": [
                {"symbol": t.symbol, "side": t.side, "entry_time": str(t.entry_time),
                 "exit_time": str(t.exit_time), "entry_price": t.entry_price,
                 "exit_price": t.exit_price, "quantity": t.quantity, "net_pnl": t.net_pnl,
                 "costs": t.costs, "exit_reason": t.exit_reason}
                for t in self.trades
            ],
        }

    def _print_summary(self, r: dict):
        pf = f"{r['profit_factor']:.2f}" if r['profit_factor'] < 100 else "inf"
        print(f"\n{'='*60}")
        print(f"MEAN REVERSION BACKTEST COMPLETE")
        print(f"{'='*60}")
        print(f"\n  Initial: ₹{r['initial_capital']:,.0f}")
        print(f"  Final:   ₹{r['final_capital']:,.0f}")
        print(f"  P&L:     ₹{r['total_pnl']:,.0f} ({r['total_pnl_pct']:.2f}%)")
        print(f"\n  Trades:  {r['total_trades']}")
        print(f"  Win Rate: {r['win_rate']:.1f}%")
        print(f"  Avg Win:  ₹{r['avg_win']:,.0f}")
        print(f"  Avg Loss: ₹{r['avg_loss']:,.0f}")
        print(f"  PF:       {pf}")
        print(f"  Sharpe:   {r['sharpe_ratio']:.2f}")
        print(f"  Max DD:   {r['max_drawdown_pct']:.1f}%")
        print(f"  Costs:    ₹{r['total_costs']:,.0f}")
        if r.get("exit_reasons"):
            print(f"\n  Exit Reasons:")
            for reason, count in sorted(r["exit_reasons"].items(), key=lambda x: -x[1]):
                print(f"    {reason}: {count}")
        if r["long_trades"]:
            print(f"\n  Long:  {r['long_trades']} trades | ₹{r['long_pnl']:,.0f} | {r['long_win_rate']:.0f}% win")
        if r["short_trades"]:
            print(f"  Short: {r['short_trades']} trades | ₹{r['short_pnl']:,.0f} | {r['short_win_rate']:.0f}% win")
