#!/usr/bin/env python3
"""
Run daily reversal strategy (pseudo trading).

Usage:
    python backend/scripts/run_reversal.py              # Run daily cycle
    python backend/scripts/run_reversal.py --status     # Show current status
    python backend/scripts/run_reversal.py --reset      # Reset all state
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from backend.broker.session import load_access_token
from backend.config import settings


def main():
    parser = argparse.ArgumentParser(description="Daily reversal pseudo trading")
    parser.add_argument("--status", action="store_true", help="Show current status")
    parser.add_argument("--reset", action="store_true", help="Reset all state")
    parser.add_argument("--offline", action="store_true", help="Use saved data (no Kite)")
    args = parser.parse_args()

    # Connect to Kite if available
    kite = None
    if not args.offline:
        try:
            from kiteconnect import KiteConnect
            token = load_access_token()
            if token:
                kite = KiteConnect(api_key=settings.kite_api_key)
                kite.set_access_token(token)
                print("Connected to Zerodha")
            else:
                print("No access token — using offline mode")
        except Exception as e:
            print(f"Kite connection failed: {e} — using offline mode")

    from backend.strategies.daily_momentum.live import ReversalEngine

    engine = ReversalEngine(kite=kite)

    if args.reset:
        engine.reset()
        print("State reset. Fresh start.")
        return

    if args.status:
        status = engine.get_status()
        print(f"\n{'='*50}")
        print(f"REVERSAL ENGINE STATUS")
        print(f"{'='*50}")
        print(f"  Capital: ₹{status['capital']:,.0f}")
        print(f"  P&L: ₹{status['pnl']:,.0f} ({status['pnl_pct']:+.1f}%)")
        print(f"  Trades: {status['total_trades']} (WR: {status['win_rate']:.0f}%)")
        print(f"  Open Positions: {status['open_positions']}")
        print(f"  Kill Switch: {'ACTIVE' if status['kill_switch_active'] else 'OK'}")

        if status["positions"]:
            print(f"\n  Active Batches:")
            for batch in status["positions"]:
                stocks = [s["symbol"] for s in batch["stocks"]]
                print(f"    Entry: {batch['entry_date']} | Stocks: {', '.join(stocks[:5])}")

        if status["recent_trades"]:
            print(f"\n  Recent Trades:")
            for t in status["recent_trades"][-5:]:
                marker = "WIN" if t["win"] else "LOSS"
                print(f"    {t['symbol']:>12} | {t['entry_date']} → {t['exit_date']} | ₹{t['net_pnl']:+,.0f} | {marker}")
        return

    # Run daily cycle
    result = engine.run_daily()


if __name__ == "__main__":
    main()
