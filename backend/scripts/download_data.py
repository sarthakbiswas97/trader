#!/usr/bin/env python3
"""
Download historical data for NIFTY 50 stocks using Zerodha Kite Connect.
Rate limited to 3 requests/second.

Usage:
    python scripts/download_data.py                     # Download all NIFTY 50
    python scripts/download_data.py --symbols RELIANCE TCS  # Specific symbols
    python scripts/download_data.py --days 30           # Last 30 days only
    python scripts/download_data.py --test              # Test with 3 symbols
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from backend.services.historical_data import HistoricalDataService
from backend.broker.session import load_access_token
from backend.config import settings

NIFTY_50 = [
    "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK",
    "HINDUNILVR", "SBIN", "BHARTIARTL", "ITC", "KOTAKBANK",
    "LT", "AXISBANK", "BAJFINANCE", "ASIANPAINT", "MARUTI",
    "TITAN", "SUNPHARMA", "ULTRACEMCO", "NESTLEIND", "WIPRO",
    "HCLTECH", "TATAMOTORS", "POWERGRID", "NTPC", "TECHM",
    "M&M", "BAJAJFINSV", "ONGC", "ADANIENT", "ADANIPORTS",
    "COALINDIA", "JSWSTEEL", "TATASTEEL", "GRASIM", "INDUSINDBK",
    "BRITANNIA", "CIPLA", "DRREDDY", "DIVISLAB", "EICHERMOT",
    "HEROMOTOCO", "BPCL", "APOLLOHOSP", "SBILIFE", "TATACONSUM",
    "HINDALCO", "LTIM", "BAJAJ-AUTO", "SHRIRAMFIN", "TRENT"
]


def main():
    parser = argparse.ArgumentParser(description="Download historical stock data")
    parser.add_argument("--symbols", nargs="+", help="Specific symbols to download")
    parser.add_argument("--days", type=int, default=60, help="Days of history (default: 60)")
    parser.add_argument("--intervals", nargs="+", default=["5m", "1h", "1d"],
                        help="Intervals to download (default: 5m 1h 1d)")
    parser.add_argument("--test", action="store_true", help="Test with 3 symbols only")
    args = parser.parse_args()

    print("=" * 60)
    print("HISTORICAL DATA DOWNLOADER (Zerodha Kite)")
    print("=" * 60)

    # Load access token from saved session
    access_token = load_access_token()
    if not access_token:
        print("\n❌ No valid session found.")
        print("   Run 'python scripts/auth.py' first to authenticate.")
        sys.exit(1)

    # Initialize Kite client
    from kiteconnect import KiteConnect
    kite = KiteConnect(api_key=settings.kite_api_key)
    kite.set_access_token(access_token)

    # Verify connection
    try:
        profile = kite.profile()
        print(f"✅ Connected as: {profile['user_name']}")
    except Exception as e:
        print(f"\n❌ Session expired. Run 'python scripts/auth.py' again.")
        print(f"   Error: {e}")
        sys.exit(1)

    # Determine symbols
    if args.symbols:
        symbols = args.symbols
    elif args.test:
        symbols = ["RELIANCE", "TCS", "INFY"]
    else:
        symbols = NIFTY_50

    print(f"\nSymbols: {len(symbols)}")
    print(f"Days: {args.days}")
    print(f"Intervals: {args.intervals}")

    # Estimate time
    total_requests = len(symbols) * len(args.intervals) + 1  # +1 for instruments
    estimated_time = total_requests * 0.35
    print(f"Estimated time: ~{estimated_time/60:.1f} minutes")
    print("=" * 60 + "\n")

    # Initialize service and download
    service = HistoricalDataService(kite=kite)

    try:
        results = service.download_universe(
            symbols=symbols,
            intervals=args.intervals,
            days=args.days
        )

        print("\n" + "=" * 60)
        print("DOWNLOAD COMPLETE")
        print("=" * 60)

        # Summary
        success = 0
        failed = 0
        total_rows = 0

        for symbol in symbols:
            if symbol in results and results[symbol]:
                success += 1
                rows = sum(len(df) for df in results[symbol].values())
                total_rows += rows
            else:
                failed += 1

        print(f"\nSuccess: {success}/{len(symbols)} symbols")
        print(f"Total rows: {total_rows:,}")
        if failed:
            print(f"Failed: {failed}")

        print(f"\nData saved to: data/historical/")

    except KeyboardInterrupt:
        print("\n\nDownload interrupted by user")
        sys.exit(1)


if __name__ == "__main__":
    main()
