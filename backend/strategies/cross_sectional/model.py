"""
LightGBM Model for Cross-Sectional Return Prediction.

Predicts 30-min forward relative returns.
Uses shallow trees + high regularization to avoid overfitting.
Evaluated by Information Coefficient (Spearman rank correlation).
"""

from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import lightgbm as lgb
from scipy.stats import spearmanr
from sklearn.metrics import mean_squared_error

from backend.core.logger import get_logger
from backend.strategies.cross_sectional.features import FEATURE_COLUMNS

logger = get_logger(__name__)

_MODEL_DIR = Path(__file__).parent.parent.parent / "ml" / "models"
MODEL_PATH = _MODEL_DIR / "cross_sectional_lgbm.joblib"


def train_model(
    dataset_path: str = None,
    train_ratio: float = 0.7,
) -> dict:
    """
    Train LightGBM on cross-sectional dataset.

    Uses time-based split, evaluates by Information Coefficient.

    Returns:
        Dict with model, metrics, feature importance
    """
    from backend.strategies.cross_sectional.dataset import DATASET_PATH

    path = Path(dataset_path) if dataset_path else DATASET_PATH

    if not path.exists():
        raise FileNotFoundError(f"Dataset not found: {path}")

    df = pd.read_csv(path)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    print(f"\nLoaded {len(df):,} rows from {path}")

    # Features with statistically significant IC
    feature_cols = [
        "atr_pct", "is_first_hour", "minute_of_day", "volatility_20",
        "day_of_week", "market_adx", "range_pos_20", "ret_10",
        "momentum_10", "dist_from_day_high", "vol_spike", "vwap_distance",
        "boll_pos", "ema_ratio", "nifty_ret_5", "rsi", "ret_1",
    ]

    # Time-based split
    df = df.sort_values("timestamp")
    split_idx = int(len(df) * train_ratio)

    train = df.iloc[:split_idx]
    test = df.iloc[split_idx:]

    X_train = train[feature_cols].values
    y_train = train["target"].values
    X_test = test[feature_cols].values
    y_test = test["target"].values

    print(f"  Train: {len(train):,} rows ({train['timestamp'].min().date()} → {train['timestamp'].max().date()})")
    print(f"  Test:  {len(test):,} rows ({test['timestamp'].min().date()} → {test['timestamp'].max().date()})")

    # Replace NaN/inf
    X_train = np.nan_to_num(X_train, nan=0.0, posinf=0.0, neginf=0.0)
    X_test = np.nan_to_num(X_test, nan=0.0, posinf=0.0, neginf=0.0)

    params = {
        "objective": "regression",
        "metric": "rmse",
        "num_leaves": 16,
        "learning_rate": 0.03,
        "feature_fraction": 0.7,
        "bagging_fraction": 0.7,
        "bagging_freq": 5,
        "min_data_in_leaf": 500,
        "lambda_l1": 0.1,
        "lambda_l2": 1.0,
        "verbose": -1,
        "n_jobs": -1,
        "seed": 42,
    }

    train_set = lgb.Dataset(X_train, y_train, feature_name=feature_cols)
    valid_set = lgb.Dataset(X_test, y_test, feature_name=feature_cols, reference=train_set)

    model = lgb.train(
        params,
        train_set,
        num_boost_round=300,
        valid_sets=[valid_set],
        callbacks=[lgb.log_evaluation(100)],
    )

    # Evaluate
    preds_test = model.predict(X_test)
    preds_train = model.predict(X_train)

    # Information Coefficient (Spearman rank correlation)
    ic_test, _ = spearmanr(preds_test, y_test)
    ic_train, _ = spearmanr(preds_train, y_train)

    # RMSE
    rmse_test = np.sqrt(mean_squared_error(y_test, preds_test))

    # Daily IC: compute IC per day for stability
    test_df = test.copy()
    test_df["pred"] = preds_test
    test_df["date"] = test_df["timestamp"].dt.date

    daily_ics = []
    for day, group in test_df.groupby("date"):
        if len(group) >= 10:
            ic, _ = spearmanr(group["pred"], group["target"])
            if not np.isnan(ic):
                daily_ics.append(ic)

    mean_daily_ic = np.mean(daily_ics) if daily_ics else 0
    ic_hit_rate = (np.array(daily_ics) > 0).mean() * 100 if daily_ics else 0

    # Decile analysis: do top predictions actually outperform?
    test_df["pred_decile"] = pd.qcut(test_df["pred"], 10, labels=False, duplicates="drop")
    decile_returns = test_df.groupby("pred_decile")["target"].mean()

    print(f"\n  Metrics:")
    print(f"    IC (test):      {ic_test:.4f}")
    print(f"    IC (train):     {ic_train:.4f}")
    print(f"    Daily IC mean:  {mean_daily_ic:.4f}")
    print(f"    IC hit rate:    {ic_hit_rate:.0f}% (days with positive IC)")
    print(f"    RMSE (test):    {rmse_test:.6f}")

    print(f"\n  Return by prediction decile (test):")
    print(f"    {'Decile':<8} {'Mean Return':>12}")
    for decile in sorted(decile_returns.index):
        ret = decile_returns[decile]
        marker = "←TOP" if decile == decile_returns.index.max() else ("←BOT" if decile == decile_returns.index.min() else "")
        print(f"    {decile:<8} {ret*100:>11.4f}% {marker}")

    spread = decile_returns.iloc[-1] - decile_returns.iloc[0]
    print(f"\n    Top-Bottom spread: {spread*100:.4f}%")

    # Feature importance
    importance = dict(zip(feature_cols, model.feature_importance(importance_type="gain")))
    sorted_imp = sorted(importance.items(), key=lambda x: x[1], reverse=True)

    print(f"\n  Feature Importance (gain):")
    for name, imp in sorted_imp[:15]:
        print(f"    {name:<25} {imp:.0f}")

    # Save
    _MODEL_DIR.mkdir(parents=True, exist_ok=True)
    bundle = {
        "model": model,
        "features": feature_cols,
        "params": params,
        "metrics": {
            "ic_test": ic_test,
            "ic_train": ic_train,
            "daily_ic_mean": mean_daily_ic,
            "ic_hit_rate": ic_hit_rate,
            "rmse": rmse_test,
            "spread": spread,
        },
    }
    joblib.dump(bundle, MODEL_PATH)
    print(f"\n  Model saved to: {MODEL_PATH}")

    return bundle


class ReturnPredictor:
    """Load and use trained LightGBM model."""

    def __init__(self):
        if not MODEL_PATH.exists():
            raise FileNotFoundError(f"Model not found: {MODEL_PATH}")

        bundle = joblib.load(MODEL_PATH)
        self.model = bundle["model"]
        self.features = bundle["features"]
        logger.info("ReturnPredictor loaded")

    def predict(self, features: dict) -> float:
        """Predict forward return for a single stock."""
        X = np.array([[features.get(f, 0) for f in self.features]])
        X = np.nan_to_num(X, nan=0.0)
        return float(self.model.predict(X)[0])

    def predict_batch(self, features_list: list[dict]) -> list[float]:
        """Predict for multiple stocks."""
        X = np.array([[f.get(col, 0) for col in self.features] for f in features_list])
        X = np.nan_to_num(X, nan=0.0)
        return self.model.predict(X).tolist()
