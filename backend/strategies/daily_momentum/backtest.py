"""
Daily Momentum Backtest.

Each day:
  1. Compute momentum factors for all stocks
  2. Rank stocks cross-sectionally
  3. Long top quintile, short bottom quintile
  4. Hold for N days, then rebalance

Evaluated by:
  - Information Coefficient (IC)
  - Quintile spread (top minus bottom return)
  - Long-short portfolio P&L
"""

from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from backend.core.logger import get_logger
from backend.core.symbols import NIFTY_100
from backend.services.backtester import ZerodhaCosts
from backend.services.historical_data import HistoricalDataService

logger = get_logger(__name__)

_BACKEND_DIR = Path(__file__).parent.parent.parent


def run_momentum_backtest(
    holding_days: int = 5,
    top_n: int = 10,
    bottom_n: int = 10,
    capital: float = 100000.0,
    momentum_lookback: int = 21,
    cost_per_trade_pct: float = 0.001,  # ~0.1% round trip (realistic for daily)
    symbols: list[str] = None,
) -> dict:
    """
    Run daily momentum cross-sectional backtest.

    Args:
        holding_days: Rebalance every N days
        top_n: Number of stocks to long
        bottom_n: Number of stocks to short
        capital: Initial capital
        momentum_lookback: Days for momentum calculation
        cost_per_trade_pct: Transaction cost as % of trade value
        symbols: Stock universe

    Returns:
        Results dict with IC, spreads, P&L
    """
    symbols = symbols or NIFTY_100
    ds = HistoricalDataService()

    print("=" * 60)
    print("DAILY MOMENTUM BACKTEST")
    print("=" * 60)

    # Load daily data for all stocks
    all_data = {}
    for symbol in symbols:
        df = ds.load_candles(symbol, "daily")
        if df.empty or len(df) < 100:
            continue
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df = df.sort_values("timestamp").reset_index(drop=True)
        all_data[symbol] = df

    if not all_data:
        raise RuntimeError("No daily data found. Download with daily interval first.")

    # Build panel: for each date, compute returns for all stocks
    # Find common dates
    date_sets = [set(df["timestamp"].dt.date) for df in all_data.values()]
    common_dates = sorted(set.intersection(*date_sets))

    print(f"\n  Stocks: {len(all_data)}")
    print(f"  Common trading days: {len(common_dates)}")
    print(f"  Period: {common_dates[0]} to {common_dates[-1]}")
    print(f"  Momentum lookback: {momentum_lookback} days")
    print(f"  Holding period: {holding_days} days")
    print(f"  Long top {top_n} / Short bottom {bottom_n}")

    # Compute daily returns panel
    returns_data = {}
    for symbol, df in all_data.items():
        df = df.set_index(df["timestamp"].dt.date)
        returns_data[symbol] = df["close"]

    price_panel = pd.DataFrame(returns_data)
    price_panel = price_panel.loc[common_dates]

    # Forward returns for different horizons
    fwd_returns = {}
    for h in [1, 3, 5, 10, 21]:
        fwd_returns[h] = price_panel.pct_change(h).shift(-h)

    # Momentum factors
    mom_1d = price_panel.pct_change(1)
    mom_5d = price_panel.pct_change(5)
    mom_10d = price_panel.pct_change(10)
    mom_21d = price_panel.pct_change(21)

    # Combined momentum score (simple equal-weight)
    # Skip most recent 1-day (reversal effect) — use 5d + 10d + 21d
    momentum_score = (mom_5d.rank(axis=1, pct=True) +
                      mom_10d.rank(axis=1, pct=True) +
                      mom_21d.rank(axis=1, pct=True)) / 3

    # Compute IC: correlation between momentum score and forward return
    ic_results = {}
    for horizon, fwd in fwd_returns.items():
        daily_ics = []
        for dt in common_dates[momentum_lookback:-horizon]:
            if dt not in momentum_score.index or dt not in fwd.index:
                continue

            scores = momentum_score.loc[dt].dropna()
            returns = fwd.loc[dt].dropna()

            common = scores.index.intersection(returns.index)
            if len(common) < 20:
                continue

            ic, _ = spearmanr(scores[common], returns[common])
            if not np.isnan(ic):
                daily_ics.append({"date": dt, "ic": ic})

        if daily_ics:
            ic_df = pd.DataFrame(daily_ics)
            ic_results[horizon] = {
                "mean_ic": ic_df["ic"].mean(),
                "median_ic": ic_df["ic"].median(),
                "ic_std": ic_df["ic"].std(),
                "ic_hit_rate": (ic_df["ic"] > 0).mean() * 100,
                "t_stat": ic_df["ic"].mean() / (ic_df["ic"].std() / np.sqrt(len(ic_df))),
                "n_days": len(ic_df),
            }

    print(f"\n  Information Coefficient (IC):")
    print(f"  {'Horizon':<10} {'Mean IC':>10} {'Hit Rate':>10} {'t-stat':>10} {'Days':>6}")
    print(f"  {'-'*48}")
    for h in sorted(ic_results.keys()):
        r = ic_results[h]
        sig = "***" if abs(r["t_stat"]) > 3 else "**" if abs(r["t_stat"]) > 2 else "*" if abs(r["t_stat"]) > 1.5 else ""
        print(f"  {h}d{'':<8} {r['mean_ic']:>10.4f} {r['ic_hit_rate']:>9.0f}% {r['t_stat']:>10.2f} {r['n_days']:>6} {sig}")

    # Quintile analysis for the target holding period
    target_fwd = fwd_returns.get(holding_days)
    if target_fwd is None:
        target_fwd = fwd_returns[min(fwd_returns.keys(), key=lambda x: abs(x - holding_days))]

    quintile_returns = {q: [] for q in range(5)}

    for dt in common_dates[momentum_lookback:-holding_days]:
        if dt not in momentum_score.index or dt not in target_fwd.index:
            continue

        scores = momentum_score.loc[dt].dropna()
        returns = target_fwd.loc[dt].dropna()

        common = scores.index.intersection(returns.index)
        if len(common) < 20:
            continue

        ranked = scores[common].rank(pct=True)
        for symbol in common:
            q = min(int(ranked[symbol] * 5), 4)
            quintile_returns[q].append(returns[symbol])

    print(f"\n  Quintile Returns ({holding_days}-day forward):")
    print(f"  {'Quintile':<10} {'Mean Return':>12} {'Count':>8}")
    print(f"  {'-'*32}")

    q_means = {}
    for q in range(5):
        if quintile_returns[q]:
            mean_ret = np.mean(quintile_returns[q])
            q_means[q] = mean_ret
            label = "BOTTOM" if q == 0 else ("TOP" if q == 4 else "")
            print(f"  Q{q+1} {label:<6} {mean_ret*100:>11.4f}% {len(quintile_returns[q]):>8}")

    if 0 in q_means and 4 in q_means:
        spread = q_means[4] - q_means[0]
        print(f"\n  Long-Short Spread: {spread*100:.4f}% per {holding_days}-day period")
        annualized = spread * (252 / holding_days)
        print(f"  Annualized Spread: {annualized*100:.2f}%")

    # Simulate portfolio
    portfolio_value = capital
    trade_log = []
    equity_curve = [{"date": common_dates[momentum_lookback], "equity": capital}]

    rebalance_dates = common_dates[momentum_lookback::holding_days]

    for i, rebal_date in enumerate(rebalance_dates[:-1]):
        if rebal_date not in momentum_score.index:
            continue

        next_rebal = rebalance_dates[i + 1] if i + 1 < len(rebalance_dates) else common_dates[-1]

        scores = momentum_score.loc[rebal_date].dropna()
        if len(scores) < top_n + bottom_n:
            continue

        # Select top and bottom stocks
        ranked = scores.sort_values(ascending=False)
        longs = ranked.head(top_n).index.tolist()
        shorts = ranked.tail(bottom_n).index.tolist()

        # Calculate returns over holding period
        if rebal_date in price_panel.index and next_rebal in price_panel.index:
            long_returns = []
            short_returns = []

            for s in longs:
                if s in price_panel.columns:
                    entry = price_panel.loc[rebal_date, s]
                    exit_p = price_panel.loc[next_rebal, s]
                    if entry > 0:
                        ret = (exit_p - entry) / entry
                        long_returns.append(ret)

            for s in shorts:
                if s in price_panel.columns:
                    entry = price_panel.loc[rebal_date, s]
                    exit_p = price_panel.loc[next_rebal, s]
                    if entry > 0:
                        ret = (entry - exit_p) / entry  # Short profit
                        short_returns.append(ret)

            # Portfolio return (equal weight)
            if long_returns and short_returns:
                avg_long = np.mean(long_returns)
                avg_short = np.mean(short_returns)
                portfolio_ret = (avg_long + avg_short) / 2  # Long-short

                # Subtract costs (rebalance = sell old + buy new)
                n_trades = (top_n + bottom_n) * 2  # Enter + exit
                cost_pct = n_trades * cost_per_trade_pct / (top_n + bottom_n)
                net_ret = portfolio_ret - cost_pct

                portfolio_value *= (1 + net_ret)

                trade_log.append({
                    "date": rebal_date,
                    "longs": longs[:3],
                    "shorts": shorts[:3],
                    "long_ret": avg_long,
                    "short_ret": avg_short,
                    "net_ret": net_ret,
                    "portfolio": portfolio_value,
                })

        equity_curve.append({"date": next_rebal, "equity": portfolio_value})

    # Portfolio metrics
    total_pnl = portfolio_value - capital
    total_ret = total_pnl / capital * 100

    eq_series = pd.Series([e["equity"] for e in equity_curve])
    peak = eq_series.cummax()
    drawdown = (peak - eq_series) / peak
    max_dd = drawdown.max() * 100

    period_returns = eq_series.pct_change().dropna()
    sharpe = (period_returns.mean() / period_returns.std() * np.sqrt(252 / holding_days)) if period_returns.std() > 0 else 0

    winning_periods = sum(1 for t in trade_log if t["net_ret"] > 0)
    total_periods = len(trade_log)
    win_rate = winning_periods / total_periods * 100 if total_periods > 0 else 0

    print(f"\n{'='*60}")
    print(f"PORTFOLIO RESULTS")
    print(f"{'='*60}")
    print(f"\n  Initial:   ₹{capital:,.0f}")
    print(f"  Final:     ₹{portfolio_value:,.0f}")
    print(f"  P&L:       ₹{total_pnl:,.0f} ({total_ret:.2f}%)")
    print(f"  Periods:   {total_periods}")
    print(f"  Win Rate:  {win_rate:.0f}%")
    print(f"  Sharpe:    {sharpe:.2f}")
    print(f"  Max DD:    {max_dd:.1f}%")

    # Show some trades
    if trade_log:
        print(f"\n  Recent periods:")
        for t in trade_log[-5:]:
            print(f"    {t['date']}: L={t['long_ret']*100:+.2f}% S={t['short_ret']*100:+.2f}% Net={t['net_ret']*100:+.2f}% → ₹{t['portfolio']:,.0f}")

    return {
        "capital": capital,
        "final_value": portfolio_value,
        "total_pnl": total_pnl,
        "total_return_pct": total_ret,
        "periods": total_periods,
        "win_rate": win_rate,
        "sharpe": sharpe,
        "max_drawdown_pct": max_dd,
        "ic_results": ic_results,
        "quintile_means": q_means,
        "spread": q_means.get(4, 0) - q_means.get(0, 0) if q_means else 0,
        "equity_curve": equity_curve,
        "trade_log": trade_log,
        "holding_days": holding_days,
    }
