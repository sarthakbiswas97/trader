#!/usr/bin/env python3
"""
Run the multi-engine trading system.

This is the main entry point for daily paper trading.
Run once per trading day after 9:30 AM IST.

Usage:
    python -m backend.scripts.run_multi_engine          # Run daily cycle
    python -m backend.scripts.run_multi_engine --status  # Show current status
    python -m backend.scripts.run_multi_engine --reset   # Reset all state
    python -m backend.scripts.run_multi_engine --offline # Use saved data (no Kite)
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from backend.strategies.multi_engine import MultiEngine


def main():
    parser = argparse.ArgumentParser(description="Multi-engine trading system")
    parser.add_argument("--status", action="store_true", help="Show current status")
    parser.add_argument("--reset", action="store_true", help="Reset all state")
    parser.add_argument("--offline", action="store_true", help="Use saved data only")
    parser.add_argument("--capital", type=float, default=100000, help="Initial capital")
    args = parser.parse_args()

    # Connect to Kite (unless offline)
    kite = None
    if not args.offline and not args.status:
        try:
            from kiteconnect import KiteConnect
            from backend.broker.session import load_access_token
            from backend.config import settings

            token = load_access_token()
            if token:
                kite = KiteConnect(api_key=settings.kite_api_key)
                kite.set_access_token(token)
                profile = kite.profile()
                print(f"Connected as: {profile['user_name']}")
            else:
                print("No valid Kite session. Running with saved data.")
        except Exception as e:
            print(f"Kite connection failed: {e}. Running with saved data.")

    engine = MultiEngine(kite=kite, total_capital=args.capital)

    if args.reset:
        engine.reset()
        print("Multi-engine state reset.")
        return

    if args.status:
        status = engine.get_status()
        print(json.dumps(status, indent=2, default=str))
        return

    # Run daily cycle
    result = engine.run_daily()

    # Save result summary
    print(f"\nResult saved. Portfolio: ₹{result['portfolio_value']:,.0f}")


if __name__ == "__main__":
    main()
