"""
Midcap Momentum Backtest — regime-aware.

Tests pure momentum (buy winners) on midcap stocks,
segmented by market regime to validate the hypothesis:
  - BULL regime: momentum works (buy winners, ride trends)
  - BEAR regime: reversal works (buy losers, catch bounces)

Also compares large-cap reversal vs midcap momentum
across different market conditions.
"""

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from backend.core.logger import get_logger
from backend.core.symbols import NIFTY_50, NIFTY_100_EXTRA, NIFTY_100
from backend.services.historical_data import HistoricalDataService
from backend.strategies.regime import Regime, RegimeClassifier

logger = get_logger(__name__)

_BACKEND_DIR = Path(__file__).parent.parent.parent
_INDEX_DIR = _BACKEND_DIR / "data" / "index"


def _load_nifty_daily() -> pd.DataFrame:
    """Load NIFTY 50 index daily data."""
    path = _INDEX_DIR / "NIFTY50_daily.csv"
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_csv(path)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df["date"] = df["timestamp"].dt.date
    df = df.set_index("date").sort_index()
    return df


def _classify_regime_series(nifty_df: pd.DataFrame) -> pd.Series:
    """
    Classify each trading day into BULL/NEUTRAL/WEAK.

    Returns Series: date → Regime
    """
    classifier = RegimeClassifier()
    regimes = {}

    closes = nifty_df["close"]
    dma_50 = closes.rolling(50, min_periods=30).mean()

    for i in range(50, len(nifty_df)):
        dt = nifty_df.index[i]
        close = closes.iloc[i]
        dma = dma_50.iloc[i]

        ret_5d = (close - closes.iloc[i - 5]) / closes.iloc[i - 5] if i >= 5 else 0
        ret_1d = (close - closes.iloc[i - 1]) / closes.iloc[i - 1] if i >= 1 else 0

        # Breadth is not available per-day from index data alone,
        # so use 0.5 default (regime still works from trend + momentum)
        regime = classifier.classify(close, dma, ret_5d, ret_1d, 0.5)
        regimes[dt] = regime

    return pd.Series(regimes)


def _compute_backtest_allocation(
    regime: Regime,
    rolling_ic: float | None,
    nifty_ret_5d: float | None,
    current_drawdown: float = 0.0,
) -> float:
    """
    Continuous confidence-scored allocation for backtest.

    Matches production logic: soft DD curve, regime-weighted k,
    regime-specific floors.
    """
    # Regime config: base, floor, dd_k
    config = {
        Regime.BULL: (0.75, 0.25, 0.5),
        Regime.NEUTRAL: (0.60, 0.15, 0.7),
        Regime.WEAK: (0.25, 0.08, 1.0),
    }
    base, floor, dd_k = config[regime]

    # Confidence from IC + momentum
    scores, weights = [], []

    if rolling_ic is not None:
        ic_score = max(0, min(1, (rolling_ic + 0.02) / 0.04))
        scores.append(ic_score)
        weights.append(0.50)

    if nifty_ret_5d is not None:
        mom_score = max(0, min(1, (nifty_ret_5d + 0.015) / 0.03))
        scores.append(mom_score)
        weights.append(0.50)

    confidence = sum(s * w for s, w in zip(scores, weights)) / sum(weights) if scores else 0.5

    # Scale: confidence 0→base-15%, 0.5→base, 1→base+15%
    alloc = base + (confidence - 0.5) * 0.30

    # Soft drawdown curve: alloc *= (1 - k * drawdown)
    if current_drawdown > 0.03:
        alloc *= (1.0 - dd_k * current_drawdown)

    # Regime-specific floor and cap
    return max(floor, min(0.85, alloc))


def run_regime_backtest(
    holding_days: int = 5,
    top_n: int = 10,
    capital: float = 100000.0,
    cost_per_trade_pct: float = 0.001,
    universe: str = "nifty50",  # "nifty50", "midcap", "nifty100"
    strategy: str = "reversal",  # "reversal" (buy losers) or "momentum" (buy winners)
) -> dict:
    """
    Run regime-segmented backtest.

    Tests whether momentum or reversal works better in each regime.

    Args:
        holding_days: Rebalance frequency
        top_n: Stocks to pick per rebalance
        capital: Starting capital
        cost_per_trade_pct: Round-trip cost
        universe: Which stock universe
        strategy: "reversal" = buy losers, "momentum" = buy winners
    """
    symbols = {
        "nifty50": NIFTY_50,
        "midcap": NIFTY_100_EXTRA,
        "nifty100": NIFTY_100,
    }[universe]

    ds = HistoricalDataService()

    print("=" * 60)
    print(f"REGIME-AWARE {strategy.upper()} BACKTEST — {universe.upper()}")
    print("=" * 60)

    # Load daily data
    all_data = {}
    for symbol in symbols:
        df = ds.load_candles(symbol, "daily")
        if df.empty or len(df) < 30:
            continue
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df = df.sort_values("timestamp").reset_index(drop=True)
        all_data[symbol] = df

    if len(all_data) < 10:
        print(f"\n  Only {len(all_data)} stocks have data. Need at least 10.")
        print("  Download more data first: python -m backend.scripts.download_data")
        return {"error": "insufficient_data", "stocks": len(all_data)}

    # Build price panel
    returns_data = {}
    for symbol, df in all_data.items():
        df_indexed = df.set_index(df["timestamp"].dt.date)
        returns_data[symbol] = df_indexed["close"]

    price_panel = pd.DataFrame(returns_data)
    common_dates = sorted(price_panel.dropna(thresh=max(10, len(all_data) // 2)).index)
    price_panel = price_panel.loc[common_dates]

    print(f"\n  Stocks: {len(all_data)}")
    print(f"  Trading days: {len(common_dates)}")
    print(f"  Period: {common_dates[0]} to {common_dates[-1]}")
    print(f"  Strategy: {strategy}")

    # Classify regimes
    nifty_df = _load_nifty_daily()
    if nifty_df.empty:
        print("  No NIFTY index data — running without regime segmentation")
        regime_series = pd.Series(Regime.NEUTRAL, index=common_dates)
    else:
        regime_series = _classify_regime_series(nifty_df)

    # Momentum scores
    mom_5d = price_panel.pct_change(5)
    mom_10d = price_panel.pct_change(10)
    mom_21d = price_panel.pct_change(21)

    if strategy == "reversal":
        # Buy biggest losers: ascending=False means lowest returns → highest rank
        score = (mom_5d.rank(axis=1, pct=True, ascending=False) +
                 mom_10d.rank(axis=1, pct=True, ascending=False) +
                 mom_21d.rank(axis=1, pct=True, ascending=False)) / 3
    else:
        # Buy biggest winners: ascending=True means highest returns → highest rank
        score = (mom_5d.rank(axis=1, pct=True) +
                 mom_10d.rank(axis=1, pct=True) +
                 mom_21d.rank(axis=1, pct=True)) / 3

    # Forward returns
    fwd_5d = price_panel.pct_change(holding_days).shift(-holding_days)

    # IC by regime
    lookback = 21
    regime_ics = {Regime.BULL: [], Regime.NEUTRAL: [], Regime.WEAK: []}
    all_ics = []

    for dt in common_dates[lookback:-holding_days]:
        if dt not in score.index or dt not in fwd_5d.index:
            continue

        scores = score.loc[dt].dropna()
        returns = fwd_5d.loc[dt].dropna()
        common = scores.index.intersection(returns.index)
        if len(common) < 10:
            continue

        ic, _ = spearmanr(scores[common], returns[common])
        if np.isnan(ic):
            continue

        regime = regime_series.get(dt, Regime.NEUTRAL)
        regime_ics[regime].append(ic)
        all_ics.append({"date": dt, "ic": ic, "regime": regime})

    # Print IC results
    print(f"\n  Information Coefficient by Regime:")
    print(f"  {'Regime':<10} {'Mean IC':>10} {'Hit Rate':>10} {'t-stat':>10} {'Days':>6}")
    print(f"  {'-'*48}")

    for regime in [Regime.BULL, Regime.NEUTRAL, Regime.WEAK]:
        ics = regime_ics[regime]
        if len(ics) > 5:
            mean_ic = np.mean(ics)
            t = mean_ic / (np.std(ics) / np.sqrt(len(ics))) if np.std(ics) > 0 else 0
            hit = np.mean([ic > 0 for ic in ics]) * 100
            sig = "***" if abs(t) > 3 else "**" if abs(t) > 2 else "*" if abs(t) > 1.5 else ""
            print(f"  {regime.value:<10} {mean_ic:>10.4f} {hit:>9.0f}% {t:>10.2f} {len(ics):>6} {sig}")
        else:
            print(f"  {regime.value:<10} {'insufficient data':>40}")

    if all_ics:
        all_ic_vals = [x["ic"] for x in all_ics]
        mean_all = np.mean(all_ic_vals)
        t_all = mean_all / (np.std(all_ic_vals) / np.sqrt(len(all_ic_vals)))
        print(f"  {'ALL':<10} {mean_all:>10.4f} {np.mean([x > 0 for x in all_ic_vals])*100:>9.0f}% {t_all:>10.2f} {len(all_ic_vals):>6}")

    # Dynamic allocation: scales with NIFTY momentum (matches production)
    # Simulate portfolio with dynamic regime-aware allocation
    portfolio_value = capital
    trade_log = []
    equity_curve = [{"date": str(common_dates[lookback]), "equity": capital}]
    total_utilization = []

    rebalance_dates = common_dates[lookback::holding_days]

    # Pre-compute NIFTY 5d returns for midcap scaling
    nifty_closes = nifty_df["close"] if not nifty_df.empty else pd.Series()
    nifty_ret_5d_series = nifty_closes.pct_change(5) if len(nifty_closes) > 5 else pd.Series()

    # Track rolling IC for dynamic WEAK sizing
    running_ics = []

    for i, rebal_date in enumerate(rebalance_dates[:-1]):
        if rebal_date not in score.index:
            continue

        next_rebal = rebalance_dates[i + 1]
        regime = regime_series.get(rebal_date, Regime.NEUTRAL)

        # Compute running IC from recent predictions
        if len(running_ics) > 5:
            recent_ic = np.mean(running_ics[-20:])
        else:
            recent_ic = None

        # Get NIFTY 5d return for this date
        nifty_5d = nifty_ret_5d_series.get(rebal_date, None)
        nifty_5d = float(nifty_5d) if nifty_5d is not None and not np.isnan(nifty_5d) else None

        # Current drawdown for dampening
        peak_value = max(e["equity"] for e in equity_curve) if equity_curve else capital
        current_dd = max(0, (peak_value - portfolio_value) / peak_value)

        # Dynamic allocation (continuous, confidence-scored)
        alloc = _compute_backtest_allocation(regime, recent_ic, nifty_5d, current_dd)
        total_utilization.append(alloc)

        scores_row = score.loc[rebal_date].dropna()
        if len(scores_row) < top_n:
            equity_curve.append({"date": str(next_rebal), "equity": portfolio_value})
            continue

        # Pick top stocks
        ranked = scores_row.sort_values(ascending=False)
        picks = ranked.head(top_n).index.tolist()

        # Calculate returns
        if rebal_date in price_panel.index and next_rebal in price_panel.index:
            stock_returns = []
            for s in picks:
                if s in price_panel.columns:
                    entry = price_panel.loc[rebal_date, s]
                    exit_p = price_panel.loc[next_rebal, s]
                    if entry > 0 and not np.isnan(exit_p):
                        stock_returns.append((exit_p - entry) / entry)

            if stock_returns:
                avg_ret = np.mean(stock_returns)

                portfolio_ret = avg_ret * alloc
                cost = top_n * 2 * cost_per_trade_pct * alloc / top_n
                net_ret = portfolio_ret - cost
                portfolio_value *= (1 + net_ret)

                trade_log.append({
                    "date": rebal_date,
                    "regime": regime.value,
                    "picks": picks[:3],
                    "avg_ret": avg_ret,
                    "alloc": alloc,
                    "net_ret": net_ret,
                    "portfolio": portfolio_value,
                })

                # Track IC for dynamic WEAK sizing
                if rebal_date in fwd_5d.index:
                    fwd = fwd_5d.loc[rebal_date].dropna()
                    sc = score.loc[rebal_date].dropna()
                    common_syms = sc.index.intersection(fwd.index)
                    if len(common_syms) >= 10:
                        period_ic, _ = spearmanr(sc[common_syms], fwd[common_syms])
                        if not np.isnan(period_ic):
                            running_ics.append(period_ic)

        equity_curve.append({"date": str(next_rebal), "equity": portfolio_value})

    # Results
    total_pnl = portfolio_value - capital
    total_ret = total_pnl / capital * 100

    eq_series = pd.Series([e["equity"] for e in equity_curve])
    peak = eq_series.cummax()
    drawdown = (peak - eq_series) / peak
    max_dd = drawdown.max() * 100

    period_returns = eq_series.pct_change().dropna()
    sharpe = (period_returns.mean() / period_returns.std() * np.sqrt(252 / holding_days)) if len(period_returns) > 1 and period_returns.std() > 0 else 0

    winning = sum(1 for t in trade_log if t.get("net_ret", 0) > 0)
    trading = len(trade_log)
    win_rate = winning / trading * 100 if trading > 0 else 0
    # Count periods where alloc < 50% as "reduced exposure"
    reduced_periods = sum(1 for t in trade_log if t.get("alloc", 1) < 0.50)

    print(f"\n{'='*60}")
    print(f"PORTFOLIO RESULTS — {strategy.upper()} / {universe.upper()}")
    print(f"{'='*60}")
    print(f"\n  Initial:       ₹{capital:,.0f}")
    print(f"  Final:         ₹{portfolio_value:,.0f}")
    print(f"  P&L:           ₹{total_pnl:,.0f} ({total_ret:+.2f}%)")
    print(f"  Sharpe:        {sharpe:.2f}")
    print(f"  Max DD:        {max_dd:.1f}%")
    avg_util = np.mean(total_utilization) * 100 if total_utilization else 0
    print(f"  Win Rate:      {win_rate:.0f}% ({winning}/{trading})")
    print(f"  Avg Util:      {avg_util:.0f}% capital deployed")
    print(f"  Reduced Alloc: {reduced_periods}/{len(trade_log)} periods (alloc < 50%)")

    # Per-regime P&L
    print(f"\n  P&L by Regime:")
    for regime in [Regime.BULL, Regime.NEUTRAL, Regime.WEAK]:
        regime_trades = [t for t in trade_log if t.get("regime") == regime.value]
        if regime_trades:
            regime_pnl = sum(t["net_ret"] for t in regime_trades) * 100
            regime_wr = sum(1 for t in regime_trades if t["net_ret"] > 0) / len(regime_trades) * 100
            avg_alloc = np.mean([t.get("alloc", 0) for t in regime_trades]) * 100
            print(f"    {regime.value:<10} {regime_pnl:>8.2f}% return, {regime_wr:.0f}% WR, {avg_alloc:.0f}% avg alloc ({len(regime_trades)} periods)")
        else:
            print(f"    {regime.value:<10} no trades")

    return {
        "strategy": strategy,
        "universe": universe,
        "capital": capital,
        "final_value": portfolio_value,
        "total_pnl": total_pnl,
        "total_return_pct": total_ret,
        "sharpe": sharpe,
        "max_drawdown_pct": max_dd,
        "win_rate": win_rate,
        "reduced_periods": reduced_periods,
        "total_periods": len(trade_log),
        "ic_by_regime": {
            r.value: {
                "mean_ic": np.mean(regime_ics[r]) if regime_ics[r] else 0,
                "count": len(regime_ics[r]),
            }
            for r in Regime
        },
        "equity_curve": equity_curve,
        "trade_log": trade_log,
    }


def compare_strategies(holding_days: int = 5, top_n: int = 10) -> dict:
    """
    Compare momentum vs reversal across regimes.

    This is the key validation: shows that reversal dominates
    in BEAR/NEUTRAL while momentum works in BULL.
    """
    print("\n" + "=" * 70)
    print("STRATEGY COMPARISON: MOMENTUM vs REVERSAL by REGIME")
    print("=" * 70)

    results = {}
    for strategy in ["reversal", "momentum"]:
        for universe in ["nifty50"]:
            key = f"{strategy}_{universe}"
            results[key] = run_regime_backtest(
                holding_days=holding_days,
                top_n=top_n,
                universe=universe,
                strategy=strategy,
            )
            print()

    # Summary comparison
    print("\n" + "=" * 70)
    print("COMPARISON SUMMARY")
    print("=" * 70)
    print(f"\n  {'Config':<25} {'Return':>10} {'Sharpe':>8} {'MaxDD':>8} {'WinRate':>8}")
    print(f"  {'-'*60}")

    for key, r in results.items():
        if "error" in r:
            continue
        print(f"  {key:<25} {r['total_return_pct']:>9.2f}% {r['sharpe']:>8.2f} {r['max_drawdown_pct']:>7.1f}% {r['win_rate']:>7.0f}%")

    return results


if __name__ == "__main__":
    compare_strategies()
