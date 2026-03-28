#!/usr/bin/env python3
"""
Rolling Window Robustness Test.

Tests the strategy across multiple non-overlapping time windows
to verify consistency — not just one lucky period.

Usage:
    python backend/scripts/robustness.py
    python backend/scripts/robustness.py --train-days 25 --test-days 5
"""

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import numpy as np
import pandas as pd

from backend.core.symbols import NIFTY_50
from backend.services.feature_engine import FeatureEngine, FEATURE_COLUMNS
from backend.services.historical_data import HistoricalDataService
from backend.services.backtester import Backtester


def get_trading_days() -> list[date]:
    """Load all available trading days from historical data."""
    ds = HistoricalDataService()
    fe = FeatureEngine()

    all_dates = set()
    for symbol in NIFTY_50[:5]:  # Check a few stocks for date range
        df = ds.load_candles(symbol, "5m")
        if not df.empty:
            all_dates.update(df["timestamp"].dt.date.unique())

    return sorted(all_dates)


def run_window(
    window_id: int,
    train_start: date,
    train_end: date,
    test_start: date,
    test_end: date,
) -> dict:
    """Run backtest for a single window."""
    bt = Backtester(
        capital=100000,
        train_days=999,  # We control dates manually via the data
        long_take_profit=0.008,
        long_stop_loss=0.005,
        short_take_profit=0.008,
        short_stop_loss=0.00375,  # 0.5% * 0.75
        require_confirmation=True,
        stock_filter_pct=0.4,
        enable_shorting=True,
    )

    # Override: manually limit data to train+test window
    # The backtester will use train_days to split, but we feed it only the right data
    results = bt.run()

    return results


def main():
    parser = argparse.ArgumentParser(description="Rolling window robustness test")
    parser.add_argument("--train-days", type=int, default=20, help="Training window (days)")
    parser.add_argument("--test-days", type=int, default=5, help="Test window (days)")
    parser.add_argument("--step-days", type=int, default=5, help="Step between windows (days)")
    args = parser.parse_args()

    print("=" * 70)
    print("ROLLING WINDOW ROBUSTNESS TEST")
    print("=" * 70)

    # Get available trading days
    trading_days = get_trading_days()
    total_days = len(trading_days)

    print(f"\n  Available trading days: {total_days}")
    print(f"  Date range: {trading_days[0]} to {trading_days[-1]}")
    print(f"  Train window: {args.train_days} days")
    print(f"  Test window: {args.test_days} days")
    print(f"  Step size: {args.step_days} days")

    # Generate windows
    windows = []
    start = 0
    while start + args.train_days + args.test_days <= total_days:
        train_start = trading_days[start]
        train_end = trading_days[start + args.train_days - 1]
        test_start = trading_days[start + args.train_days]
        test_end_idx = min(start + args.train_days + args.test_days - 1, total_days - 1)
        test_end = trading_days[test_end_idx]

        windows.append({
            "id": len(windows) + 1,
            "train_start": train_start,
            "train_end": train_end,
            "test_start": test_start,
            "test_end": test_end,
            "train_start_idx": start,
        })
        start += args.step_days

    print(f"  Windows to test: {len(windows)}")

    if not windows:
        print("\n  Not enough data for even one window!")
        sys.exit(1)

    # Run each window
    window_results = []

    for w in windows:
        print(f"\n  Window {w['id']}: Train {w['train_start']}→{w['train_end']} | Test {w['test_start']}→{w['test_end']}")

        bt = Backtester(
            capital=100000,
            train_days=args.train_days,
            retrain_every_days=args.test_days,
            long_take_profit=0.008,
            long_stop_loss=0.005,
            short_take_profit=0.008,
            short_stop_loss=0.00375,
            require_confirmation=True,
            stock_filter_pct=0.0,  # No stock filter per-window (avoids lookahead bias)
            enable_shorting=True,
            test_start_date=w["test_start"],
            test_end_date=w["test_end"],
        )

        try:
            results = bt.run()

            pf = results["profit_factor"]
            pf_str = f"{pf:.2f}" if pf < 100 else "inf"

            window_results.append({
                "window": w["id"],
                "test_period": f"{w['test_start']} → {w['test_end']}",
                "pnl": results["total_pnl"],
                "pnl_pct": results["total_pnl_pct"],
                "trades": results["total_trades"],
                "win_rate": results["win_rate"],
                "profit_factor": results["profit_factor"],
                "max_dd": results["max_drawdown_pct"],
                "avg_win": results["avg_win"],
                "avg_loss": results["avg_loss"],
                "sharpe": results["sharpe_ratio"],
                "long_trades": results["long_trades"],
                "short_trades": results["short_trades"],
            })

            print(f"    P&L: ₹{results['total_pnl']:,.0f} | PF: {pf_str} | Trades: {results['total_trades']} | WR: {results['win_rate']:.0f}%")

        except Exception as e:
            print(f"    ERROR: {e}")
            window_results.append({
                "window": w["id"],
                "test_period": f"{w['test_start']} → {w['test_end']}",
                "pnl": 0, "pnl_pct": 0, "trades": 0, "win_rate": 0,
                "profit_factor": 0, "max_dd": 0, "avg_win": 0, "avg_loss": 0,
                "sharpe": 0, "long_trades": 0, "short_trades": 0,
            })

    # Summary
    print("\n" + "=" * 70)
    print("ROBUSTNESS RESULTS")
    print("=" * 70)

    print(f"\n  {'Win':>4} {'Test Period':<28} {'PnL':>9} {'Trades':>7} {'WR':>6} {'PF':>6} {'DD':>6} {'AvgW':>6} {'AvgL':>6}")
    print(f"  {'-'*80}")

    for r in window_results:
        pf = f"{r['profit_factor']:.2f}" if r["profit_factor"] < 100 else "inf"
        marker = "✓" if r["profit_factor"] > 1 else "✗"
        print(
            f"  {marker} {r['window']:>2}  {r['test_period']:<28}"
            f" {r['pnl']:>8,.0f}"
            f" {r['trades']:>7}"
            f" {r['win_rate']:>5.0f}%"
            f" {pf:>6}"
            f" {r['max_dd']:>5.1f}%"
            f" {r['avg_win']:>5,.0f}"
            f" {r['avg_loss']:>5,.0f}"
        )

    # Consistency metrics
    total_windows = len(window_results)
    profitable_windows = sum(1 for r in window_results if r["profit_factor"] > 1)
    consistency = profitable_windows / total_windows * 100 if total_windows > 0 else 0

    total_pnl = sum(r["pnl"] for r in window_results)
    avg_pf = np.mean([r["profit_factor"] for r in window_results if r["trades"] > 0]) if window_results else 0
    total_trades = sum(r["trades"] for r in window_results)

    print(f"\n  {'='*80}")
    print(f"  CONSISTENCY SCORE: {profitable_windows}/{total_windows} windows profitable ({consistency:.0f}%)")
    print(f"  {'='*80}")
    print(f"\n  Aggregate P&L:      ₹{total_pnl:,.0f}")
    print(f"  Avg Profit Factor:  {avg_pf:.2f}")
    print(f"  Total Trades:       {total_trades}")

    # Verdict
    print(f"\n  VERDICT: ", end="")
    if consistency >= 80:
        print("STRONG — Strategy has real edge across market conditions")
    elif consistency >= 60:
        print("PROMISING — Edge exists but conditional on market regime")
    elif consistency >= 40:
        print("WEAK — Edge is inconsistent, needs regime filtering")
    else:
        print("NO EDGE — Strategy does not generalize")

    # Generate HTML report
    report_path = Path(__file__).parent.parent / "data" / "robustness_report.html"
    _generate_report(window_results, consistency, total_pnl, avg_pf, report_path)
    print(f"\n  Report: {report_path}")


def _generate_report(results: list, consistency: float, total_pnl: float, avg_pf: float, path: Path):
    """Generate HTML robustness report."""
    from datetime import datetime

    window_labels = [f"W{r['window']}" for r in results]
    pnl_values = [str(round(r["pnl"], 2)) for r in results]
    pf_values = [str(min(round(r["profit_factor"], 2), 5)) for r in results]
    pnl_colors = ["'#22c55e'" if r["pnl"] > 0 else "'#ef4444'" for r in results]

    table_rows = ""
    for r in results:
        pf = f"{r['profit_factor']:.2f}" if r["profit_factor"] < 100 else "∞"
        pnl_color = "#22c55e" if r["pnl"] > 0 else "#ef4444"
        table_rows += f"""
        <tr>
            <td>W{r['window']}</td>
            <td>{r['test_period']}</td>
            <td style="color:{pnl_color}">₹{r['pnl']:,.0f}</td>
            <td>{r['trades']}</td>
            <td>{r['win_rate']:.0f}%</td>
            <td>{pf}</td>
            <td>{r['max_dd']:.1f}%</td>
        </tr>"""

    verdict_color = "#22c55e" if consistency >= 60 else "#ef4444"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><title>Robustness Report</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ font-family:-apple-system,sans-serif; background:#0a0a0a; color:#e5e5e5; padding:24px; }}
  h1 {{ font-size:20px; margin-bottom:4px; }}
  h2 {{ font-size:16px; margin:24px 0 12px; color:#a3a3a3; }}
  .subtitle {{ font-size:13px; color:#737373; margin-bottom:24px; }}
  .grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:12px; margin-bottom:24px; }}
  .card {{ background:#171717; border:1px solid #262626; border-radius:8px; padding:14px; }}
  .card-label {{ font-size:11px; color:#737373; text-transform:uppercase; }}
  .card-value {{ font-size:20px; font-weight:600; margin-top:4px; }}
  .profit {{ color:#22c55e; }} .loss {{ color:#ef4444; }}
  .chart-container {{ background:#171717; border:1px solid #262626; border-radius:8px; padding:16px; margin-bottom:24px; }}
  table {{ width:100%; border-collapse:collapse; font-size:12px; }}
  th {{ text-align:left; padding:8px 12px; background:#171717; border-bottom:1px solid #262626; color:#737373; }}
  td {{ padding:6px 12px; border-bottom:1px solid #1a1a1a; }}
  .table-container {{ background:#171717; border:1px solid #262626; border-radius:8px; overflow:hidden; }}
</style>
</head>
<body>
<h1>Robustness Report</h1>
<p class="subtitle">Rolling Window Validation | {datetime.now().strftime('%Y-%m-%d %H:%M')}</p>

<div class="grid">
  <div class="card">
    <div class="card-label">Consistency Score</div>
    <div class="card-value" style="color:{verdict_color}">{consistency:.0f}%</div>
  </div>
  <div class="card">
    <div class="card-label">Aggregate P&L</div>
    <div class="card-value {'profit' if total_pnl > 0 else 'loss'}">₹{total_pnl:,.0f}</div>
  </div>
  <div class="card">
    <div class="card-label">Avg Profit Factor</div>
    <div class="card-value">{avg_pf:.2f}</div>
  </div>
  <div class="card">
    <div class="card-label">Windows Tested</div>
    <div class="card-value">{len(results)}</div>
  </div>
</div>

<h2>P&L per Window</h2>
<div class="chart-container"><canvas id="pnlChart" height="60"></canvas></div>

<h2>Profit Factor per Window</h2>
<div class="chart-container"><canvas id="pfChart" height="60"></canvas></div>

<h2>Window Details</h2>
<div class="table-container">
<table>
<thead><tr><th>Window</th><th>Test Period</th><th>P&L</th><th>Trades</th><th>Win Rate</th><th>PF</th><th>Max DD</th></tr></thead>
<tbody>{table_rows}</tbody>
</table>
</div>

<script>
new Chart(document.getElementById('pnlChart'), {{
  type:'bar',
  data:{{ labels:[{','.join(f"'{w}'" for w in window_labels)}], datasets:[{{ data:[{','.join(pnl_values)}], backgroundColor:[{','.join(pnl_colors)}], borderRadius:4 }}] }},
  options:{{ responsive:true, plugins:{{legend:{{display:false}}}}, scales:{{ x:{{ticks:{{color:'#525252'}},grid:{{display:false}}}}, y:{{ticks:{{color:'#525252',callback:v=>'₹'+v}},grid:{{color:'#1a1a1a'}}}} }} }}
}});
new Chart(document.getElementById('pfChart'), {{
  type:'bar',
  data:{{ labels:[{','.join(f"'{w}'" for w in window_labels)}], datasets:[{{ data:[{','.join(pf_values)}], backgroundColor:[{','.join("'#22c55e'" if float(v) > 1 else "'#ef4444'" for v in pf_values)}], borderRadius:4 }}] }},
  options:{{ responsive:true, plugins:{{legend:{{display:false}},annotation:{{annotations:{{line1:{{type:'line',yMin:1,yMax:1,borderColor:'#525252',borderDash:[5,5]}}}}}}}}, scales:{{ x:{{ticks:{{color:'#525252'}},grid:{{display:false}}}}, y:{{ticks:{{color:'#525252'}},grid:{{color:'#1a1a1a'}}}} }} }}
}});
</script>
</body></html>"""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html)


if __name__ == "__main__":
    main()
