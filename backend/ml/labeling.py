"""
Label generation for ML training.
Creates target variable based on future price movement.
Includes time decay weighting for recent data emphasis.
"""

from pathlib import Path

import pandas as pd
import numpy as np

from backend.core.logger import get_logger

logger = get_logger(__name__)

_BACKEND_DIR = Path(__file__).parent.parent
DEFAULT_FEATURES_PATH = str(_BACKEND_DIR / "data" / "training" / "features.csv")


def exponential_decay_weights(
    timestamps: pd.Series,
    half_life_days: float = 30.0,
    min_weight: float = 0.01,
) -> np.ndarray:
    """
    Calculate exponential decay weights based on sample age.

    Recent samples get higher weights, older samples get lower weights.
    This helps the model focus on recent market dynamics.

    Args:
        timestamps: Series of datetime timestamps
        half_life_days: Days until weight drops to 50%
            - 30 days: aggressive decay (recent focus)
            - 45 days: moderate decay (balanced)
            - 60 days: gentle decay (more history)
        min_weight: Minimum weight to prevent zero weights

    Returns:
        Array of weights (0 to 1)

    Example weights with half_life=30:
        - Today: 1.0
        - 30 days ago: 0.5
        - 60 days ago: 0.25
        - 90 days ago: 0.125
    """
    timestamps = pd.to_datetime(timestamps)
    max_time = timestamps.max()

    # Calculate age in days
    age_days = (max_time - timestamps).dt.total_seconds() / 86400

    # Decay rate from half-life: λ = ln(2) / half_life
    decay_rate = np.log(2) / half_life_days

    # Exponential decay: w = e^(-λ * age)
    weights = np.exp(-decay_rate * age_days)

    # Apply minimum weight
    weights = np.maximum(weights, min_weight)

    logger.info(
        "Decay weights calculated",
        half_life_days=half_life_days,
        min_weight=f"{weights.min():.4f}",
        max_weight=f"{weights.max():.4f}",
        mean_weight=f"{weights.mean():.4f}",
    )

    return weights


def create_labels(
    df: pd.DataFrame,
    lookahead: int = 6,
    threshold: float = 0.005,
    price_col: str = "close",
    num_classes: int = 3,
) -> pd.DataFrame:
    """
    Create classification labels based on future price movement.

    Args:
        df: DataFrame with OHLCV + features
        lookahead: Number of candles to look ahead (6 = 30 min for 5-min data)
        threshold: Minimum price change for UP/DOWN (0.5% = 0.005)
        price_col: Column to use for price
        num_classes: 2 for binary (UP/DOWN), 3 for UP/NEUTRAL/DOWN

    Returns:
        DataFrame with 'target' column:
            3-class: 0 = DOWN, 1 = NEUTRAL, 2 = UP
            2-class: 0 = DOWN/FLAT, 1 = UP
    """
    df = df.copy()

    # Calculate future return
    future_price = df[price_col].shift(-lookahead)
    current_price = df[price_col]
    future_return = (future_price - current_price) / current_price

    df["future_return"] = future_return

    if num_classes == 3:
        # 3-class: DOWN (0), NEUTRAL (1), UP (2)
        conditions = [
            future_return <= -threshold,  # DOWN: drops >= threshold
            future_return >= threshold,   # UP: rises >= threshold
        ]
        choices = [0, 2]
        df["target"] = np.select(conditions, choices, default=1)  # default = NEUTRAL

        # Drop rows where we can't compute future return
        df = df.dropna(subset=["future_return"])

        up_count = (df["target"] == 2).sum()
        neutral_count = (df["target"] == 1).sum()
        down_count = (df["target"] == 0).sum()
        total = len(df)

        logger.info(
            "Created 3-class labels",
            total=total,
            up=f"{up_count} ({up_count/total*100:.1f}%)",
            neutral=f"{neutral_count} ({neutral_count/total*100:.1f}%)",
            down=f"{down_count} ({down_count/total*100:.1f}%)",
        )
    else:
        # 2-class: DOWN/FLAT (0), UP (1) — original behavior
        df["target"] = (future_return >= threshold).astype(int)
        df = df.dropna(subset=["target"])

        logger.info(
            "Created 2-class labels",
            total=len(df),
            positive=int(df["target"].sum()),
            negative=int((df["target"] == 0).sum()),
            pct_positive=f"{df['target'].mean()*100:.1f}%",
        )

    return df


def create_regression_labels(
    df: pd.DataFrame,
    lookahead: int = 6,
    price_col: str = "close"
) -> pd.DataFrame:
    """
    Create regression labels (future return) instead of binary.
    """
    df = df.copy()

    future_price = df[price_col].shift(-lookahead)
    current_price = df[price_col]
    df["target"] = (future_price - current_price) / current_price

    df = df.dropna(subset=["target"])

    logger.info(
        f"Created regression labels",
        total=len(df),
        mean_return=f"{df['target'].mean()*100:.3f}%",
        std_return=f"{df['target'].std()*100:.3f}%"
    )

    return df


def prepare_training_data(
    features_path: str = DEFAULT_FEATURES_PATH,
    lookahead: int = 6,
    threshold: float = 0.005,
    train_ratio: float = 0.8,
    half_life_days: float = None,
    num_classes: int = 3,
) -> tuple[pd.DataFrame, pd.DataFrame, np.ndarray | None]:
    """
    Load features and prepare train/test splits.
    Uses time-based split (no data leakage).

    Args:
        features_path: Path to features CSV
        lookahead: Candles to look ahead for label
        threshold: Min return for positive label
        train_ratio: Fraction of data for training
        half_life_days: If set, calculate decay weights for training data
        num_classes: 2 for binary, 3 for UP/NEUTRAL/DOWN

    Returns:
        (train_df, test_df, train_weights)
        train_weights is None if half_life_days is not set
    """
    logger.info(f"Loading features from {features_path}")
    df = pd.read_csv(features_path)
    df["timestamp"] = pd.to_datetime(df["timestamp"])

    # Sort by timestamp to ensure proper time-based split
    df = df.sort_values("timestamp").reset_index(drop=True)

    # Create labels
    df = create_labels(df, lookahead=lookahead, threshold=threshold, num_classes=num_classes)

    # Time-based split
    split_idx = int(len(df) * train_ratio)
    train_df = df.iloc[:split_idx].copy()
    test_df = df.iloc[split_idx:].copy()

    # Calculate decay weights for training data
    train_weights = None
    if half_life_days is not None:
        train_weights = exponential_decay_weights(
            train_df["timestamp"],
            half_life_days=half_life_days,
        )
        logger.info(
            "Decay weighting enabled",
            half_life_days=half_life_days,
            oldest_weight=f"{train_weights.min():.4f}",
            newest_weight=f"{train_weights.max():.4f}",
        )

    logger.info(
        f"Data split",
        train_rows=len(train_df),
        test_rows=len(test_df),
        train_end=train_df["timestamp"].max(),
        test_start=test_df["timestamp"].min(),
        decay_enabled=half_life_days is not None,
    )

    return train_df, test_df, train_weights
