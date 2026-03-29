"""
30-Min Trend Backtest.

Resamples 5-min data to 30-min, detects trends + pullbacks,
trades with trailing stop and ATR-based targets.
"""

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from backend.core.logger import get_logger
from backend.core.symbols import NIFTY_100
from backend.services.backtester import ZerodhaCosts, BacktestTrade
from backend.services.historical_data import HistoricalDataService
from backend.strategies.trend_30m.strategy import (
    resample_to_30min,
    compute_trend_features,
    detect_pullback,
    TrendSetup,
)

logger = get_logger(__name__)


class TrendBacktester:
    """30-min trend following backtester."""

    def __init__(
        self,
        capital: float = 100000.0,
        max_trades_per_day: int = 3,
        max_position_pct: float = 0.05,
        tp_atr_mult: float = 3.0,        # Take profit at 3x ATR (larger moves)
        sl_atr_mult: float = 1.5,        # Stop loss at 1.5x ATR
        trail_atr_mult: float = 1.5,     # Trailing stop at 1.5x ATR
        max_hold_candles: int = 8,        # 8 x 30min = 4 hours max
        slippage_pct: float = 0.0005,
        enable_shorting: bool = True,
        min_quality: float = 25,
        max_concurrent: int = 3,
        symbols: list[str] = None,
    ):
        self.initial_capital = capital
        self.capital = capital
        self.max_trades_per_day = max_trades_per_day
        self.max_position_pct = max_position_pct
        self.tp_atr_mult = tp_atr_mult
        self.sl_atr_mult = sl_atr_mult
        self.trail_atr_mult = trail_atr_mult
        self.max_hold_candles = max_hold_candles
        self.slippage_pct = slippage_pct
        self.enable_shorting = enable_shorting
        self.min_quality = min_quality
        self.max_concurrent = max_concurrent
        self.symbols = symbols or NIFTY_100

        self.costs = ZerodhaCosts()
        self.trades: list[BacktestTrade] = []
        self.equity_curve: list[dict] = []
        self._positions: dict[str, dict] = {}
        self._day_trades: int = 0

    def run(self) -> dict:
        """Run the 30-min trend backtest."""
        print("=" * 60)
        print("30-MIN TREND FOLLOWING BACKTEST")
        print("=" * 60)

        ds = HistoricalDataService()

        # Load and resample all stocks to 30-min
        all_30m = {}
        for symbol in self.symbols:
            df = ds.load_candles(symbol, "5m")
            if df.empty or len(df) < 100:
                continue
            df["timestamp"] = pd.to_datetime(df["timestamp"])
            df_30m = resample_to_30min(df)
            if len(df_30m) >= 30:
                df_30m = compute_trend_features(df_30m)
                df_30m.attrs["symbol"] = symbol
                all_30m[symbol] = df_30m

        # Load NIFTY 30-min for market direction
        nifty_5m = pd.read_csv("backend/data/index/NIFTY50_5m.csv")
        nifty_5m["timestamp"] = pd.to_datetime(nifty_5m["timestamp"])
        nifty_30m = resample_to_30min(nifty_5m)
        nifty_30m = compute_trend_features(nifty_30m)
        nifty_trend_map = {}
        for _, row in nifty_30m.iterrows():
            nifty_trend_map[row["timestamp"]] = int(row["trend"])

        # Get trading days
        all_dates = set()
        for df in all_30m.values():
            all_dates.update(df["timestamp"].dt.date.unique())
        trading_days = sorted(all_dates)

        print(f"\n  Stocks (30-min): {len(all_30m)}")
        print(f"  Trading days: {len(trading_days)}")
        print(f"  Period: {trading_days[0]} to {trading_days[-1]}")
        print(f"  TP: {self.tp_atr_mult}x ATR | SL: {self.sl_atr_mult}x ATR | Trail: {self.trail_atr_mult}x ATR")

        for today in trading_days:
            self._day_trades = 0
            day_trades = []

            # Build candle timeline across all stocks
            candle_events = []
            for symbol, df in all_30m.items():
                day_candles = df[df["timestamp"].dt.date == today]
                for _, row in day_candles.iterrows():
                    candle_events.append((row["timestamp"], symbol, row, df))

            candle_events.sort(key=lambda x: x[0])

            for ts, symbol, row, full_df in candle_events:
                # Check exits
                if symbol in self._positions:
                    trade = self._check_exit(symbol, row)
                    if trade:
                        day_trades.append(trade)

                # Check entries
                if (symbol not in self._positions
                        and self._day_trades < self.max_trades_per_day
                        and len(self._positions) < self.max_concurrent):

                    # Get candles up to current timestamp
                    hist = full_df[full_df["timestamp"] <= ts]
                    if len(hist) < 5:
                        continue

                    hist.attrs["symbol"] = symbol

                    # Get NIFTY trend at this timestamp
                    nifty_t = nifty_trend_map.get(ts, 0)

                    setup = detect_pullback(hist, nifty_trend=nifty_t)

                    if setup and setup.quality_score >= self.min_quality:
                        if setup.direction == "SHORT" and not self.enable_shorting:
                            continue
                        self._enter(setup)

            # Force close at end of day
            for symbol in list(self._positions.keys()):
                if symbol in all_30m:
                    day_data = all_30m[symbol][all_30m[symbol]["timestamp"].dt.date == today]
                    if not day_data.empty:
                        last = day_data.iloc[-1]
                        trade = self._close(symbol, last["close"], last["timestamp"], "market_close")
                        if trade:
                            day_trades.append(trade)

            self.equity_curve.append({
                "date": today,
                "capital": self.capital,
                "equity": self.capital,
                "trades_today": len(day_trades),
            })

            if day_trades:
                pnl = self.capital - self.initial_capital
                syms = ", ".join(f"{t.symbol}({t.side})" for t in day_trades[:3])
                print(f"  {today}: ₹{self.capital:,.0f} | P&L ₹{pnl:,.0f} | Trades: {len(day_trades)} [{syms}]")

        results = self._metrics()
        self._print(results)
        return results

    def _enter(self, setup: TrendSetup) -> None:
        """Enter position with ATR-based stops."""
        price = setup.entry_price
        is_short = setup.direction == "SHORT"
        atr = setup.atr

        max_alloc = self.capital * self.max_position_pct
        quantity = int(max_alloc / price)
        if quantity <= 0 or quantity * price < 1000:
            return

        if is_short:
            entry = price * (1 - self.slippage_pct)
            tp = entry - atr * self.tp_atr_mult
            sl = entry + atr * self.sl_atr_mult
        else:
            entry = price * (1 + self.slippage_pct)
            tp = entry + atr * self.tp_atr_mult
            sl = entry - atr * self.sl_atr_mult

        self._positions[setup.symbol] = {
            "side": setup.direction,
            "entry_price": entry,
            "entry_time": setup.timestamp,
            "quantity": quantity,
            "tp": tp,
            "sl": sl,
            "atr": atr,
            "best_price": entry,  # For trailing stop
            "candles_held": 0,
            "score": setup.quality_score,
        }

        self._day_trades += 1

    def _check_exit(self, symbol: str, row: pd.Series) -> BacktestTrade | None:
        """Check exits with trailing stop."""
        pos = self._positions[symbol]
        pos["candles_held"] += 1

        high, low, close = row["high"], row["low"], row["close"]
        is_short = pos["side"] == "SHORT"
        atr = pos["atr"]

        # Update trailing stop
        if is_short:
            pos["best_price"] = min(pos["best_price"], low)
            trail_stop = pos["best_price"] + atr * self.trail_atr_mult
            pos["sl"] = min(pos["sl"], trail_stop)  # Tighten stop only
        else:
            pos["best_price"] = max(pos["best_price"], high)
            trail_stop = pos["best_price"] - atr * self.trail_atr_mult
            pos["sl"] = max(pos["sl"], trail_stop)

        exit_reason = None
        exit_price = close

        if is_short:
            if low <= pos["tp"]:
                exit_reason = "take_profit"
                exit_price = pos["tp"]
            elif high >= pos["sl"]:
                exit_reason = "stop_loss"
                exit_price = pos["sl"]
        else:
            if high >= pos["tp"]:
                exit_reason = "take_profit"
                exit_price = pos["tp"]
            elif low <= pos["sl"]:
                exit_reason = "stop_loss"
                exit_price = pos["sl"]

        if not exit_reason and pos["candles_held"] >= self.max_hold_candles:
            exit_reason = "max_hold_time"

        if exit_reason:
            return self._close(symbol, exit_price, row["timestamp"], exit_reason)
        return None

    def _close(self, symbol: str, price: float, timestamp, reason: str) -> BacktestTrade | None:
        if symbol not in self._positions:
            return None

        pos = self._positions.pop(symbol)
        is_short = pos["side"] == "SHORT"

        if is_short:
            exit_price = price * (1 + self.slippage_pct)
            gross = (pos["entry_price"] - exit_price) * pos["quantity"]
        else:
            exit_price = price * (1 - self.slippage_pct)
            gross = (exit_price - pos["entry_price"]) * pos["quantity"]

        costs = self.costs.round_trip_cost(pos["entry_price"], exit_price, pos["quantity"], is_short)
        net = gross - costs
        slippage = abs(price * self.slippage_pct) * pos["quantity"] * 2

        self.capital += net

        trade = BacktestTrade(
            symbol=symbol, side=pos["side"],
            entry_time=pos["entry_time"], exit_time=timestamp,
            entry_price=pos["entry_price"], exit_price=exit_price,
            quantity=pos["quantity"], gross_pnl=gross,
            costs=costs, net_pnl=net, slippage_cost=slippage,
            exit_reason=reason, confidence=pos["score"],
            direction=pos["side"],
        )
        self.trades.append(trade)
        return trade

    def _metrics(self) -> dict:
        if not self.trades:
            return {
                "initial_capital": self.initial_capital, "final_capital": self.capital,
                "total_pnl": 0, "total_pnl_pct": 0, "total_trades": 0,
                "winning_trades": 0, "losing_trades": 0, "win_rate": 0,
                "avg_win": 0, "avg_loss": 0, "max_drawdown_pct": 0,
                "sharpe_ratio": 0, "profit_factor": 0,
                "total_costs": 0, "total_slippage": 0,
                "long_trades": 0, "long_pnl": 0, "long_win_rate": 0,
                "short_trades": 0, "short_pnl": 0, "short_win_rate": 0,
                "per_stock": {}, "equity_curve": self.equity_curve,
                "exit_reasons": {}, "enable_shorting": self.enable_shorting, "trades": [],
            }

        w = [t for t in self.trades if t.net_pnl > 0]
        l = [t for t in self.trades if t.net_pnl <= 0]
        lo = [t for t in self.trades if t.side == "LONG"]
        sh = [t for t in self.trades if t.side == "SHORT"]

        pnl = sum(t.net_pnl for t in self.trades)
        gp = sum(t.net_pnl for t in w) if w else 0
        gl = abs(sum(t.net_pnl for t in l)) if l else 0
        pf = gp / gl if gl > 0 else float("inf")

        eq = [e["equity"] for e in self.equity_curve] if self.equity_curve else [self.initial_capital]
        pk = self.initial_capital
        mdd = 0
        for e in eq:
            pk = max(pk, e)
            mdd = max(mdd, (pk - e) / pk if pk > 0 else 0)

        sharpe = 0
        if len(eq) > 1:
            r = pd.Series(eq).pct_change().dropna()
            sharpe = (r.mean() / r.std() * np.sqrt(252)) if r.std() > 0 else 0

        exits = {}
        for t in self.trades:
            exits[t.exit_reason] = exits.get(t.exit_reason, 0) + 1

        sp = {}
        for t in self.trades:
            sp.setdefault(t.symbol, []).append(t.net_pnl)
        per_stock = {s: {"trades": len(p), "total_pnl": sum(p), "win_rate": sum(1 for x in p if x > 0)/len(p)*100, "avg_pnl": sum(p)/len(p)} for s, p in sp.items()}

        return {
            "initial_capital": self.initial_capital, "final_capital": self.capital,
            "total_pnl": pnl, "total_pnl_pct": pnl / self.initial_capital * 100,
            "total_trades": len(self.trades),
            "winning_trades": len(w), "losing_trades": len(l),
            "win_rate": len(w) / len(self.trades) * 100,
            "avg_win": np.mean([t.net_pnl for t in w]) if w else 0,
            "avg_loss": np.mean([t.net_pnl for t in l]) if l else 0,
            "max_drawdown_pct": mdd * 100, "sharpe_ratio": sharpe,
            "profit_factor": pf,
            "total_costs": sum(t.costs for t in self.trades),
            "total_slippage": sum(t.slippage_cost for t in self.trades),
            "long_trades": len(lo), "long_pnl": sum(t.net_pnl for t in lo),
            "long_win_rate": (sum(1 for t in lo if t.net_pnl > 0) / len(lo) * 100) if lo else 0,
            "short_trades": len(sh), "short_pnl": sum(t.net_pnl for t in sh),
            "short_win_rate": (sum(1 for t in sh if t.net_pnl > 0) / len(sh) * 100) if sh else 0,
            "per_stock": per_stock, "equity_curve": self.equity_curve,
            "exit_reasons": exits, "enable_shorting": self.enable_shorting,
            "trades": [{"symbol": t.symbol, "side": t.side, "entry_time": str(t.entry_time),
                        "exit_time": str(t.exit_time), "entry_price": t.entry_price,
                        "exit_price": t.exit_price, "quantity": t.quantity,
                        "net_pnl": t.net_pnl, "costs": t.costs, "exit_reason": t.exit_reason}
                       for t in self.trades],
        }

    def _print(self, r: dict):
        pf = f"{r['profit_factor']:.2f}" if r['profit_factor'] < 100 else "inf"
        print(f"\n{'='*60}")
        print(f"30-MIN TREND BACKTEST COMPLETE")
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
