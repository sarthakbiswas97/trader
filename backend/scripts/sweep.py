#!/usr/bin/env python3
"""
TP/SL Parameter Sweep — find optimal exit parameters.

Tests combinations of take-profit and stop-loss values,
with stock filtering and entry confirmation.

Usage:
    python backend/scripts/sweep.py
    python backend/scripts/sweep.py --no-filter    # Skip stock filtering
    python backend/scripts/sweep.py --no-confirm   # Skip entry confirmation
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from backend.services.backtester import Backtester


def main():
    parser = argparse.ArgumentParser(description="TP/SL parameter sweep")
    parser.add_argument("--no-filter", action="store_true", help="Disable stock filtering")
    parser.add_argument("--no-confirm", action="store_true", help="Disable entry confirmation")
    args = parser.parse_args()

    # Parameter grid
    tp_values = [0.003, 0.004, 0.005, 0.006, 0.008]  # 0.3% to 0.8%
    sl_values = [0.002, 0.003, 0.004, 0.005]          # 0.2% to 0.5%

    stock_filter = 0.0 if args.no_filter else 0.4
    confirmation = not args.no_confirm

    print("=" * 70)
    print("PARAMETER SWEEP")
    print("=" * 70)
    print(f"\n  Stock filter: {'top 40%' if stock_filter else 'disabled'}")
    print(f"  Confirmation: {'1-candle momentum' if confirmation else 'disabled'}")
    print(f"  TP grid: {[f'{v*100:.1f}%' for v in tp_values]}")
    print(f"  SL grid: {[f'{v*100:.1f}%' for v in sl_values]}")
    print(f"  Total combinations: {len(tp_values) * len(sl_values)}")

    results = []

    for tp in tp_values:
        for sl in sl_values:
            label = f"TP={tp*100:.1f}% SL={sl*100:.1f}%"
            print(f"\n  Testing {label}...", end=" ", flush=True)

            try:
                bt = Backtester(
                    capital=100000,
                    long_take_profit=tp,
                    long_stop_loss=sl,
                    short_take_profit=tp,
                    short_stop_loss=sl * 0.75,  # Tighter SL for shorts
                    require_confirmation=confirmation,
                    stock_filter_pct=stock_filter,
                    enable_shorting=True,
                )

                res = bt.run()

                results.append({
                    "tp": tp,
                    "sl": sl,
                    "pnl": res["total_pnl"],
                    "pnl_pct": res["total_pnl_pct"],
                    "trades": res["total_trades"],
                    "win_rate": res["win_rate"],
                    "profit_factor": res["profit_factor"],
                    "max_dd": res["max_drawdown_pct"],
                    "avg_win": res["avg_win"],
                    "avg_loss": res["avg_loss"],
                    "sharpe": res["sharpe_ratio"],
                    "costs": res["total_costs"],
                })

                pf = res["profit_factor"]
                pf_str = f"{pf:.2f}" if pf < 100 else "inf"
                print(f"P&L: ₹{res['total_pnl']:,.0f} | PF: {pf_str} | WR: {res['win_rate']:.0f}% | Trades: {res['total_trades']}")

            except Exception as e:
                print(f"ERROR: {e}")
                results.append({
                    "tp": tp, "sl": sl, "pnl": 0, "pnl_pct": 0,
                    "trades": 0, "win_rate": 0, "profit_factor": 0,
                    "max_dd": 0, "avg_win": 0, "avg_loss": 0,
                    "sharpe": 0, "costs": 0,
                })

    # Summary table
    print("\n" + "=" * 70)
    print("SWEEP RESULTS")
    print("=" * 70)

    print(f"\n  {'TP':>6} {'SL':>6} {'P&L':>10} {'Trades':>7} {'WR':>6} {'PF':>6} {'DD':>6} {'AvgW':>7} {'AvgL':>7} {'Sharpe':>7}")
    print(f"  {'-'*68}")

    # Sort by profit factor
    results.sort(key=lambda x: x["profit_factor"], reverse=True)

    for r in results:
        pf = f"{r['profit_factor']:.2f}" if r["profit_factor"] < 100 else "inf"
        print(
            f"  {r['tp']*100:>5.1f}% {r['sl']*100:>5.1f}%"
            f" {r['pnl']:>9,.0f}"
            f" {r['trades']:>7}"
            f" {r['win_rate']:>5.1f}%"
            f" {pf:>6}"
            f" {r['max_dd']:>5.1f}%"
            f" {r['avg_win']:>6,.0f}"
            f" {r['avg_loss']:>6,.0f}"
            f" {r['sharpe']:>7.2f}"
        )

    # Best result
    if results:
        best = results[0]
        print(f"\n  BEST: TP={best['tp']*100:.1f}% SL={best['sl']*100:.1f}%")
        print(f"    P&L: ₹{best['pnl']:,.0f} ({best['pnl_pct']:.2f}%)")
        print(f"    Profit Factor: {best['profit_factor']:.2f}")
        print(f"    Win Rate: {best['win_rate']:.1f}%")
        print(f"    Max Drawdown: {best['max_dd']:.1f}%")

        # Generate report for best
        bt = Backtester(
            capital=100000,
            long_take_profit=best["tp"],
            long_stop_loss=best["sl"],
            short_take_profit=best["tp"],
            short_stop_loss=best["sl"] * 0.75,
            require_confirmation=confirmation,
            stock_filter_pct=stock_filter,
            enable_shorting=True,
        )
        res = bt.run()
        bt.generate_report(res, str(Path(__file__).parent.parent / "data" / "backtest_best.html"))


if __name__ == "__main__":
    main()
