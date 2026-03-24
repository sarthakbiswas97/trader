#!/usr/bin/env python3
"""
Download historical data for NIFTY 50 stocks using Zerodha Kite Connect.

Usage:
    python scripts/download_data.py                     # Download all
    python scripts/download_data.py --symbols RELIANCE TCS  # Specific symbols
    python scripts/download_data.py --days 30           # Last 30 days only
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.services.historical_data import HistoricalDataService
from backend.core.logger import setup_logging, get_logger
from backend.config import settings

setup_logging()
logger = get_logger(__name__)

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
    parser.add_argument("--access-token", type=str, help="Kite access token")
    args = parser.parse_args()

    print("=" * 60)
    print("HISTORICAL DATA DOWNLOADER (Zerodha Kite)")
    print("=" * 60)

    if args.symbols:
        symbols = args.symbols
    elif args.test:
        symbols = ["RELIANCE", "TCS", "INFY"]
    else:
        symbols = NIFTY_50

    print(f"Symbols: {len(symbols)}")
    print(f"Days: {args.days}")
    print(f"Intervals: {args.intervals}")

    if not args.access_token:
        print("\n⚠️  No access token provided.")
        print(f"\n1. Visit: https://kite.zerodha.com/connect/login?v=3&api_key={settings.kite_api_key}")
        print("2. Login and copy the request_token from the redirect URL")
        print("3. Generate access token and re-run with --access-token")
        return

    print("=" * 60)

    from kiteconnect import KiteConnect

    kite = KiteConnect(api_key=settings.kite_api_key)
    kite.set_access_token(args.access_token)

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

        success = 0
        failed = 0
        for symbol in symbols:
            if symbol in results and results[symbol]:
                success += 1
                intervals_got = list(results[symbol].keys())
                rows = sum(len(df) for df in results[symbol].values())
                print(f"  ✅ {symbol}: {intervals_got} ({rows} total rows)")
            else:
                failed += 1
                print(f"  ❌ {symbol}: Failed")

        print(f"\nSuccess: {success}/{len(symbols)}")
        if failed:
            print(f"Failed: {failed}")

    except KeyboardInterrupt:
        print("\nDownload interrupted by user")
        sys.exit(1)


if __name__ == "__main__":
    main()
