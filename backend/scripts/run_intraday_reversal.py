#!/usr/bin/env python3
"""
Run intraday entry filter on today's reversal picks.

Monitors 5-min candles for entry confirmation signals.

Usage:
    python backend/scripts/run_intraday_reversal.py          # Run live monitoring
    python backend/scripts/run_intraday_reversal.py --scan    # Single scan (no loop)
"""

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from backend.broker.session import load_access_token
from backend.config import settings


def main():
    parser = argparse.ArgumentParser(description="Intraday entry for reversal picks")
    parser.add_argument("--scan", action="store_true", help="Single scan, no loop")
    args = parser.parse_args()

    # Connect to Kite
    from kiteconnect import KiteConnect
    token = load_access_token()
    if not token:
        print("No access token. Run: make auth")
        sys.exit(1)

    kite = KiteConnect(api_key=settings.kite_api_key)
    kite.set_access_token(token)
    print("Connected to Zerodha")

    # Get today's reversal picks from saved state
    import json
    portfolio_file = Path("backend/data/pseudo_trading/portfolio.json")

    if not portfolio_file.exists():
        print("No reversal picks found. Run: make reversal")
        sys.exit(1)

    state = json.loads(portfolio_file.read_text())
    picks = []
    for batch in state.get("positions", []):
        for stock in batch.get("stocks", []):
            picks.append(stock["symbol"])

    if not picks:
        print("No active reversal picks.")
        sys.exit(1)

    print(f"\nToday's reversal picks ({len(picks)} stocks):")
    for p in picks:
        print(f"  {p}")

    # Initialize intraday filter
    from backend.strategies.daily_momentum.intraday_entry import IntradayEntryFilter

    filter = IntradayEntryFilter(picks)

    # Fetch current 5-min candles
    from backend.services.historical_data import HistoricalDataService
    from backend.utils.time_utils import now_ist

    ds = HistoricalDataService()
    ds.set_kite(kite)

    now = now_ist()

    print(f"\nScanning at {now.strftime('%H:%M:%S')}...")

    for symbol in picks:
        try:
            # Fetch today's 5-min candles
            from datetime import timedelta
            start = now.replace(hour=9, minute=15, second=0)
            df = ds.fetch_candles(symbol, interval="5m", start_date=start, end_date=now)

            if df.empty:
                print(f"  {symbol}: no data")
                continue

            # Process each candle through the filter
            for _, row in df.iterrows():
                candle = {
                    "timestamp": row["timestamp"],
                    "open": row["open"],
                    "high": row["high"],
                    "low": row["low"],
                    "close": row["close"],
                    "volume": row["volume"],
                }
                signal = filter.process_candle(symbol, candle)

        except Exception as e:
            print(f"  {symbol}: error - {e}")

    # Print results
    filter.print_status()

    # Show current prices for context
    print(f"\n  Current Prices:")
    ltp = kite.ltp([f"NSE:{s}" for s in picks])
    for sym in picks:
        key = f"NSE:{sym}"
        if key in ltp:
            price = ltp[key]["last_price"]
            triggered = sym in filter.triggered
            marker = "← ENTRY TRIGGERED" if triggered else ""
            print(f"    {sym:>12}: ₹{price:,.2f} {marker}")

    if not args.scan:
        # Loop mode: keep scanning every 5 minutes
        print(f"\n  Monitoring... (Ctrl+C to stop)")
        print(f"  Next scan in 5 minutes")

        try:
            while True:
                time.sleep(300)  # 5 minutes
                now = now_ist()

                if now.time() > datetime.strptime("15:15", "%H:%M").time():
                    print("\n  Market closing soon. Stopping.")
                    break

                print(f"\n  Re-scanning at {now.strftime('%H:%M:%S')}...")

                for symbol in picks:
                    if symbol in filter.triggered:
                        continue  # Already triggered

                    try:
                        start = now - timedelta(minutes=10)
                        df = ds.fetch_candles(symbol, interval="5m", start_date=start, end_date=now)
                        if not df.empty:
                            row = df.iloc[-1]
                            candle = {
                                "timestamp": row["timestamp"],
                                "open": row["open"],
                                "high": row["high"],
                                "low": row["low"],
                                "close": row["close"],
                                "volume": row["volume"],
                            }
                            signal = filter.process_candle(symbol, candle)
                            if signal:
                                print(f"    NEW ENTRY: {symbol} @ ₹{signal.entry_price:,.2f} ({signal.trigger})")
                    except Exception:
                        pass

                filter.print_status()

        except KeyboardInterrupt:
            print("\n  Stopped.")

    # Final summary
    print(f"\n{'='*50}")
    print(f"INTRADAY ENTRY SUMMARY")
    print(f"{'='*50}")
    status = filter.get_status()
    print(f"  Triggered: {len(status['triggered'])} / {len(picks)}")
    print(f"  Skipped: {len(status['pending'])}")

    if status["triggered"]:
        print(f"\n  Entries to execute (MIS):")
        for sym, info in status["triggered"].items():
            print(f"    BUY {sym} @ ₹{info['price']:,.2f} (MIS) — {info['trigger']}")


if __name__ == "__main__":
    main()
