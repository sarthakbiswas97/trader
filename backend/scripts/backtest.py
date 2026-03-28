#!/usr/bin/env python3
"""
Run backtesting simulation.

Usage:
    python backend/scripts/backtest.py                    # Long + Short
    python backend/scripts/backtest.py --long-only        # Long only
    python backend/scripts/backtest.py --compare          # Run both and compare
    python backend/scripts/backtest.py --capital 200000   # Custom capital
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from backend.services.backtester import Backtester


def run_backtest(enable_shorting: bool, capital: float, label: str) -> dict:
    """Run a single backtest."""
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")

    bt = Backtester(
        capital=capital,
        enable_shorting=enable_shorting,
    )

    results = bt.run()

    # Generate report
    suffix = "long_short" if enable_shorting else "long_only"
    report_path = bt.generate_report(
        results,
        output_path=str(Path(__file__).parent.parent / "data" / f"backtest_{suffix}.html"),
    )

    return results


def main():
    parser = argparse.ArgumentParser(description="Run backtesting simulation")
    parser.add_argument("--long-only", action="store_true", help="Long only (no shorting)")
    parser.add_argument("--compare", action="store_true", help="Run both long-only and long+short, compare results")
    parser.add_argument("--capital", type=float, default=100000, help="Initial capital (default: 100000)")
    args = parser.parse_args()

    if args.compare:
        # Run both modes and compare
        long_only = run_backtest(enable_shorting=False, capital=args.capital, label="BACKTEST: LONG ONLY")
        long_short = run_backtest(enable_shorting=True, capital=args.capital, label="BACKTEST: LONG + SHORT")

        print("\n" + "=" * 60)
        print("  COMPARISON: LONG ONLY vs LONG + SHORT")
        print("=" * 60)

        rows = [
            ("Total P&L", f"₹{long_only['total_pnl']:,.0f}", f"₹{long_short['total_pnl']:,.0f}"),
            ("Return", f"{long_only['total_pnl_pct']:.2f}%", f"{long_short['total_pnl_pct']:.2f}%"),
            ("Trades", str(long_only["total_trades"]), str(long_short["total_trades"])),
            ("Win Rate", f"{long_only['win_rate']:.1f}%", f"{long_short['win_rate']:.1f}%"),
            ("Profit Factor", f"{long_only['profit_factor']:.2f}", f"{long_short['profit_factor']:.2f}"),
            ("Sharpe", f"{long_only['sharpe_ratio']:.2f}", f"{long_short['sharpe_ratio']:.2f}"),
            ("Max Drawdown", f"{long_only['max_drawdown_pct']:.1f}%", f"{long_short['max_drawdown_pct']:.1f}%"),
            ("Costs", f"₹{long_only['total_costs']:,.0f}", f"₹{long_short['total_costs']:,.0f}"),
        ]

        print(f"\n  {'Metric':<18} {'Long Only':<18} {'Long + Short':<18}")
        print(f"  {'-'*54}")
        for label, lo, ls in rows:
            print(f"  {label:<18} {lo:<18} {ls:<18}")

        # Verdict
        print(f"\n  Verdict: ", end="")
        if long_short["total_pnl"] > long_only["total_pnl"]:
            diff = long_short["total_pnl"] - long_only["total_pnl"]
            print(f"Shorting added ₹{diff:,.0f} in P&L")
        else:
            diff = long_only["total_pnl"] - long_short["total_pnl"]
            print(f"Shorting reduced P&L by ₹{diff:,.0f} — consider disabling")

    else:
        enable_shorting = not args.long_only
        label = "BACKTEST: LONG ONLY" if args.long_only else "BACKTEST: LONG + SHORT"
        run_backtest(enable_shorting=enable_shorting, capital=args.capital, label=label)


if __name__ == "__main__":
    main()
