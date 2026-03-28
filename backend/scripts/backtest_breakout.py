#!/usr/bin/env python3
"""
Backtest the breakout strategy.

Usage:
    python backend/scripts/backtest_breakout.py
    python backend/scripts/backtest_breakout.py --long-only
    python backend/scripts/backtest_breakout.py --compare
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from backend.strategies.breakout.backtest import BreakoutBacktester
from backend.services.backtester import Backtester


def main():
    parser = argparse.ArgumentParser(description="Backtest breakout strategy")
    parser.add_argument("--long-only", action="store_true")
    parser.add_argument("--compare", action="store_true", help="Compare breakout vs old prediction strategy")
    parser.add_argument("--capital", type=float, default=100000)
    args = parser.parse_args()

    if args.compare:
        # Run both strategies
        print("\n" + "=" * 70)
        print("  STRATEGY COMPARISON: PREDICTION vs BREAKOUT")
        print("=" * 70)

        # Old prediction strategy
        print("\n--- OLD: Prediction-based ---")
        old_bt = Backtester(
            capital=args.capital,
            long_take_profit=0.008, long_stop_loss=0.005,
            short_take_profit=0.008, short_stop_loss=0.00375,
            require_confirmation=True, enable_shorting=True,
        )
        old_results = old_bt.run()

        # New breakout strategy
        print("\n--- NEW: Breakout-based ---")
        new_bt = BreakoutBacktester(capital=args.capital, enable_shorting=True)
        new_results = new_bt.run()

        # Compare
        print("\n" + "=" * 70)
        print("  HEAD-TO-HEAD COMPARISON")
        print("=" * 70)

        rows = [
            ("P&L", f"₹{old_results['total_pnl']:,.0f}", f"₹{new_results['total_pnl']:,.0f}"),
            ("Return", f"{old_results['total_pnl_pct']:.2f}%", f"{new_results['total_pnl_pct']:.2f}%"),
            ("Trades", str(old_results["total_trades"]), str(new_results["total_trades"])),
            ("Win Rate", f"{old_results['win_rate']:.1f}%", f"{new_results['win_rate']:.1f}%"),
            ("Profit Factor", f"{old_results['profit_factor']:.2f}", f"{new_results['profit_factor']:.2f}"),
            ("Avg Win", f"₹{old_results['avg_win']:,.0f}", f"₹{new_results['avg_win']:,.0f}"),
            ("Avg Loss", f"₹{old_results['avg_loss']:,.0f}", f"₹{new_results['avg_loss']:,.0f}"),
            ("Max DD", f"{old_results['max_drawdown_pct']:.1f}%", f"{new_results['max_drawdown_pct']:.1f}%"),
            ("Costs", f"₹{old_results['total_costs']:,.0f}", f"₹{new_results['total_costs']:,.0f}"),
        ]

        print(f"\n  {'Metric':<16} {'Prediction':<16} {'Breakout':<16}")
        print(f"  {'-'*48}")
        for label, old, new in rows:
            print(f"  {label:<16} {old:<16} {new:<16}")

    else:
        bt = BreakoutBacktester(
            capital=args.capital,
            enable_shorting=not args.long_only,
        )
        results = bt.run()

        # Generate report
        # Add avg_pnl to per_stock (expected by report template)
        for sym, stats in results.get("per_stock", {}).items():
            if "avg_pnl" not in stats:
                stats["avg_pnl"] = stats["total_pnl"] / stats["trades"] if stats["trades"] > 0 else 0

        from backend.services.backtester import Backtester as _BT
        dummy = _BT.__new__(_BT)
        dummy.trades = bt.trades
        dummy.equity_curve = bt.equity_curve
        report_path = str(Path(__file__).parent.parent / "data" / "backtest_breakout.html")
        dummy.generate_report(results, report_path)


if __name__ == "__main__":
    main()
