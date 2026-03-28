"""
ML Setup Scorer — Predicts probability of breakout follow-through.

Trained on historical setups to score: "Will TP hit before SL?"
Used as a ranking/filtering layer on top of rule-based detection.
"""

from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import (
    accuracy_score,
    precision_score,
    recall_score,
    f1_score,
    roc_auc_score,
    classification_report,
)

from backend.core.logger import get_logger
from backend.strategies.breakout.dataset import DATASET_PATH, SETUP_FEATURE_COLS

logger = get_logger(__name__)

_MODEL_DIR = Path(__file__).parent.parent.parent / "ml" / "models"
SCORER_PATH = _MODEL_DIR / "setup_scorer.joblib"


def train_scorer(dataset_path: str = None) -> dict:
    """
    Train the setup scoring model.

    Args:
        dataset_path: Path to setup_dataset.csv

    Returns:
        Training results dict
    """
    path = Path(dataset_path) if dataset_path else DATASET_PATH

    if not path.exists():
        raise FileNotFoundError(f"Dataset not found: {path}. Run dataset.build_dataset() first.")

    df = pd.read_csv(path)
    print(f"\nLoaded {len(df)} setups from {path}")

    # Features and target
    X = df[SETUP_FEATURE_COLS].values
    y = df["outcome"].values

    # Handle NaN
    X = np.nan_to_num(X, nan=0.0)

    # Time-based split (80/20)
    split = int(len(df) * 0.8)
    X_train, X_test = X[:split], X[split:]
    y_train, y_test = y[:split], y[split:]

    print(f"  Train: {len(X_train)} | Test: {len(X_test)}")
    print(f"  Train win rate: {y_train.mean()*100:.1f}%")
    print(f"  Test win rate: {y_test.mean()*100:.1f}%")

    # Handle class imbalance
    neg = (y_train == 0).sum()
    pos = (y_train == 1).sum()
    scale_pos_weight = neg / pos if pos > 0 else 1.0

    # Train
    model = xgb.XGBClassifier(
        max_depth=3,
        learning_rate=0.1,
        n_estimators=100,
        min_child_weight=5,
        scale_pos_weight=scale_pos_weight,
        objective="binary:logistic",
        eval_metric="logloss",
        random_state=42,
        n_jobs=-1,
    )

    model.fit(X_train, y_train, eval_set=[(X_test, y_test)], verbose=False)

    # Evaluate
    y_pred = model.predict(X_test)
    y_prob = model.predict_proba(X_test)[:, 1]

    metrics = {
        "accuracy": accuracy_score(y_test, y_pred),
        "precision": precision_score(y_test, y_pred, zero_division=0),
        "recall": recall_score(y_test, y_pred, zero_division=0),
        "f1": f1_score(y_test, y_pred, zero_division=0),
        "auc": roc_auc_score(y_test, y_prob) if len(np.unique(y_test)) > 1 else 0,
    }

    print(f"\n  Accuracy:  {metrics['accuracy']:.3f}")
    print(f"  Precision: {metrics['precision']:.3f}")
    print(f"  Recall:    {metrics['recall']:.3f}")
    print(f"  F1:        {metrics['f1']:.3f}")
    print(f"  AUC:       {metrics['auc']:.3f}")

    # Feature importance
    importance = dict(zip(SETUP_FEATURE_COLS, model.feature_importances_))
    sorted_imp = sorted(importance.items(), key=lambda x: x[1], reverse=True)

    print(f"\n  Feature Importance:")
    for name, imp in sorted_imp:
        print(f"    {name:<25} {imp:.4f}")

    # Score distribution on test set
    print(f"\n  Score distribution (test):")
    for thresh in [0.3, 0.4, 0.5, 0.6, 0.7]:
        above = y_prob >= thresh
        if above.sum() > 0:
            win_rate = y_test[above].mean() * 100
            print(f"    Score >= {thresh:.1f}: {above.sum()} setups, {win_rate:.0f}% win rate")

    # Save
    _MODEL_DIR.mkdir(parents=True, exist_ok=True)
    bundle = {
        "model": model,
        "features": SETUP_FEATURE_COLS,
        "metrics": metrics,
    }
    joblib.dump(bundle, SCORER_PATH)
    print(f"\n  Scorer saved to {SCORER_PATH}")

    return {"model": model, "metrics": metrics, "importance": sorted_imp}


class SetupScorer:
    """
    Score breakout setups using trained ML model.

    Usage:
        scorer = SetupScorer()
        score = scorer.score(features_dict)
    """

    def __init__(self):
        if not SCORER_PATH.exists():
            raise FileNotFoundError(
                f"Scorer model not found at {SCORER_PATH}. "
                "Run train_scorer() first."
            )

        bundle = joblib.load(SCORER_PATH)
        self.model = bundle["model"]
        self.features = bundle["features"]
        logger.info("SetupScorer loaded")

    def score(self, features: dict) -> float:
        """
        Score a single setup.

        Args:
            features: Dict with keys matching SETUP_FEATURE_COLS

        Returns:
            Probability of TP hitting before SL (0-1)
        """
        X = np.array([[features.get(f, 0) for f in self.features]])
        X = np.nan_to_num(X, nan=0.0)
        return float(self.model.predict_proba(X)[0, 1])

    def score_batch(self, features_list: list[dict]) -> list[float]:
        """Score multiple setups."""
        return [self.score(f) for f in features_list]
