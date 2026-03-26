#!/usr/bin/env python3
"""
Generate features for all downloaded symbols.

Usage:
    python scripts/generate_features.py              # All symbols
    python scripts/generate_features.py --test       # Test with 3 symbols
    python scripts/generate_features.py --symbols RELIANCE TCS
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from backend.services.historical_data import HistoricalDataService
from backend.services.feature_engine import FeatureEngine, FEATURE_COLUMNS


def main():
    parser = argparse.ArgumentParser(description="Generate features from historical data")
    parser.add_argument("--symbols", nargs="+", help="Specific symbols")
    parser.add_argument("--test", action="store_true", help="Test with 3 symbols")
    args = parser.parse_args()

    print("=" * 60)
    print("FEATURE ENGINEERING")
    print("=" * 60)

    # Get available symbols
    data_service = HistoricalDataService()
    available = data_service.get_available_symbols()

    if not available:
        print("❌ No historical data found. Run download_data.py first.")
        sys.exit(1)

    # Determine symbols to process
    if args.symbols:
        symbols = [s for s in args.symbols if s in available]
    elif args.test:
        symbols = available[:3]
    else:
        symbols = available

    print(f"Available symbols: {len(available)}")
    print(f"Processing: {len(symbols)}")
    print(f"Features: {len(FEATURE_COLUMNS)}")
    print(f"\nFeature columns:")
    for i, col in enumerate(FEATURE_COLUMNS, 1):
        print(f"  {i:2}. {col}")
    print("=" * 60 + "\n")

    # Generate features
    engine = FeatureEngine(data_service=data_service)

    try:
        features_df = engine.generate_features_for_universe(symbols, save=True)

        print("\n" + "=" * 60)
        print("FEATURE GENERATION COMPLETE")
        print("=" * 60)

        if features_df.empty:
            print("❌ No features generated")
            sys.exit(1)

        # Summary stats
        print(f"\nTotal rows: {len(features_df):,}")
        print(f"Symbols: {features_df['symbol'].nunique()}")
        print(f"Date range: {features_df['timestamp'].min()} to {features_df['timestamp'].max()}")

        # Feature statistics
        print("\nFeature statistics:")
        for col in FEATURE_COLUMNS:
            vals = features_df[col]
            print(f"  {col:25} min={vals.min():8.3f}  max={vals.max():8.3f}  mean={vals.mean():8.3f}")

        print(f"\nSaved to: data/training/features.csv")

    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        sys.exit(1)


if __name__ == "__main__":
    main()
