#!/usr/bin/env python3
"""
Train the ML model for price direction prediction.

Usage:
    python scripts/train.py                    # Train with default settings
    python scripts/train.py --full             # Full hyperparameter search
    python scripts/train.py --lookahead 12     # Predict 1 hour ahead
    python scripts/train.py --threshold 0.01   # 1% threshold for UP
    python scripts/train.py --half-life 30     # Decay weighting (30-day half-life)
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from backend.ml.train_model import train_and_save
from backend.ml.labeling import prepare_training_data
from backend.services.feature_engine import FEATURE_COLUMNS


def main():
    parser = argparse.ArgumentParser(description="Train ML model")
    parser.add_argument("--features", default="data/training/features.csv",
                        help="Path to features CSV")
    parser.add_argument("--lookahead", type=int, default=6,
                        help="Candles to look ahead (6 = 30min for 5m data)")
    parser.add_argument("--threshold", type=float, default=0.005,
                        help="Min return for UP label (0.005 = 0.5%%)")
    parser.add_argument("--full", action="store_true",
                        help="Full hyperparameter search (slower)")
    parser.add_argument("--half-life", type=float, default=45,
                        help="Decay half-life in days (default: 45). "
                             "Recent data weighted higher. Use 0 to disable.")
    args = parser.parse_args()

    # Convert 0 to None (disable decay)
    half_life = args.half_life if args.half_life > 0 else None

    print("=" * 60)
    print("ML MODEL TRAINING")
    print("=" * 60)

    # Check features exist
    if not Path(args.features).exists():
        print(f"❌ Features file not found: {args.features}")
        print("   Run 'python scripts/generate_features.py' first.")
        sys.exit(1)

    print(f"\nSettings:")
    print(f"  Features file: {args.features}")
    print(f"  Lookahead: {args.lookahead} candles ({args.lookahead * 5} minutes)")
    print(f"  Threshold: {args.threshold * 100:.1f}%")
    print(f"  Mode: {'Full search' if args.full else 'Fast search'}")
    print(f"  Feature count: {len(FEATURE_COLUMNS)}")
    if half_life:
        print(f"  Decay half-life: {half_life} days (recent data weighted higher)")
    else:
        print(f"  Decay: disabled (equal weights)")

    # Show data split info
    print("\n" + "-" * 60)
    print("Preparing data...")

    train_df, test_df, train_weights = prepare_training_data(
        features_path=args.features,
        lookahead=args.lookahead,
        threshold=args.threshold,
        half_life_days=half_life,
    )

    if train_weights is not None:
        print(f"\n  Decay weights: min={train_weights.min():.4f}, max={train_weights.max():.4f}, mean={train_weights.mean():.4f}")

    print(f"\nData split:")
    print(f"  Training samples: {len(train_df):,}")
    print(f"  Test samples: {len(test_df):,}")
    print(f"  Training period: {train_df['timestamp'].min()} to {train_df['timestamp'].max()}")
    print(f"  Test period: {test_df['timestamp'].min()} to {test_df['timestamp'].max()}")

    # Class distribution
    print(f"\nClass distribution:")
    print(f"  Training - UP: {train_df['target'].sum():,} ({train_df['target'].mean()*100:.1f}%)")
    print(f"  Training - DOWN: {(train_df['target']==0).sum():,} ({(1-train_df['target'].mean())*100:.1f}%)")
    print(f"  Test - UP: {test_df['target'].sum():,} ({test_df['target'].mean()*100:.1f}%)")
    print(f"  Test - DOWN: {(test_df['target']==0).sum():,} ({(1-test_df['target'].mean())*100:.1f}%)")

    print("\n" + "-" * 60)
    print("Training model...")
    print("-" * 60 + "\n")

    try:
        results = train_and_save(
            features_path=args.features,
            lookahead=args.lookahead,
            threshold=args.threshold,
            fast=not args.full,
            half_life_days=half_life,
        )

        # Show confusion matrix
        cm = results["metrics"]["confusion_matrix"]
        print(f"\nConfusion Matrix:")
        print(f"                Predicted")
        print(f"               DOWN    UP")
        print(f"  Actual DOWN  {cm[0][0]:5}  {cm[0][1]:5}")
        print(f"  Actual UP    {cm[1][0]:5}  {cm[1][1]:5}")

        print("\n" + "=" * 60)
        print("Training complete! Model ready for inference.")
        print("=" * 60)

    except KeyboardInterrupt:
        print("\n\nTraining interrupted.")
        sys.exit(1)


if __name__ == "__main__":
    main()
