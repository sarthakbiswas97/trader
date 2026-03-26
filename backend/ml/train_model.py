"""
XGBoost model training pipeline.
Trains a classifier to predict price direction with SHAP explainability.
"""

import json
from datetime import datetime
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.model_selection import TimeSeriesSplit, GridSearchCV
from sklearn.metrics import (
    accuracy_score,
    precision_score,
    recall_score,
    f1_score,
    roc_auc_score,
    classification_report,
    confusion_matrix
)

from backend.core.logger import get_logger
from backend.services.feature_engine import FEATURE_COLUMNS

logger = get_logger(__name__)

MODEL_DIR = Path(__file__).parent / "models"
MODEL_DIR.mkdir(parents=True, exist_ok=True)


class ModelTrainer:
    """
    XGBoost model trainer with hyperparameter tuning and SHAP.
    """

    # Default hyperparameter grid
    PARAM_GRID = {
        "max_depth": [3, 4, 5],
        "learning_rate": [0.01, 0.05, 0.1],
        "n_estimators": [100, 150, 200],
        "min_child_weight": [1, 3, 5],
        "subsample": [0.8, 0.9],
        "colsample_bytree": [0.8, 0.9],
    }

    # Faster grid for quick training
    PARAM_GRID_FAST = {
        "max_depth": [4, 5],
        "learning_rate": [0.05, 0.1],
        "n_estimators": [100, 150],
        "min_child_weight": [1, 3],
    }

    def __init__(self, feature_columns: list[str] = None):
        self.feature_columns = feature_columns or FEATURE_COLUMNS
        self.model = None
        self.best_params = None
        self.metrics = None

    def train(
        self,
        train_df: pd.DataFrame,
        test_df: pd.DataFrame,
        fast: bool = True,
        cv_splits: int = 3,
        sample_weights: np.ndarray = None,
    ) -> dict:
        """
        Train XGBoost model with hyperparameter tuning.

        Args:
            train_df: Training data with features and 'target' column
            test_df: Test data for evaluation
            fast: Use smaller param grid for faster training
            cv_splits: Number of cross-validation splits
            sample_weights: Optional decay weights for training samples
                - Higher weights = more influence on model
                - Recent samples should have higher weights

        Returns:
            Dict with model, metrics, and best params
        """
        logger.info("Starting model training...")

        X_train = train_df[self.feature_columns].values
        y_train = train_df["target"].values
        X_test = test_df[self.feature_columns].values
        y_test = test_df["target"].values

        # Store weights for later use
        self.sample_weights = sample_weights

        logger.info(
            f"Training data",
            samples=len(X_train),
            features=len(self.feature_columns),
            positive_pct=f"{y_train.mean()*100:.1f}%",
            decay_weighted=sample_weights is not None,
        )

        # Base model
        base_model = xgb.XGBClassifier(
            objective="binary:logistic",
            eval_metric="logloss",
            use_label_encoder=False,
            random_state=42,
            n_jobs=-1
        )

        # Hyperparameter tuning with TimeSeriesSplit
        param_grid = self.PARAM_GRID_FAST if fast else self.PARAM_GRID
        tscv = TimeSeriesSplit(n_splits=cv_splits)

        logger.info(f"Running GridSearchCV with {cv_splits} splits...")

        grid_search = GridSearchCV(
            base_model,
            param_grid,
            cv=tscv,
            scoring="f1",
            n_jobs=-1,
            verbose=1
        )

        # Fit with sample weights if provided
        fit_params = {}
        if sample_weights is not None:
            fit_params["sample_weight"] = sample_weights
            logger.info("Using decay-weighted training")

        grid_search.fit(X_train, y_train, **fit_params)

        self.best_params = grid_search.best_params_
        logger.info(f"Best params: {self.best_params}")

        # Train final model with early stopping
        self.model = xgb.XGBClassifier(
            **self.best_params,
            objective="binary:logistic",
            eval_metric="logloss",
            use_label_encoder=False,
            random_state=42,
            n_jobs=-1
        )

        # Fit with early stopping on test set (with weights if provided)
        self.model.fit(
            X_train, y_train,
            sample_weight=sample_weights,
            eval_set=[(X_test, y_test)],
            verbose=False
        )

        # Evaluate
        self.metrics = self._evaluate(X_test, y_test)

        logger.info(
            "Training complete",
            accuracy=f"{self.metrics['accuracy']:.3f}",
            precision=f"{self.metrics['precision']:.3f}",
            recall=f"{self.metrics['recall']:.3f}",
            f1=f"{self.metrics['f1']:.3f}",
            auc=f"{self.metrics['auc']:.3f}"
        )

        return {
            "model": self.model,
            "best_params": self.best_params,
            "metrics": self.metrics,
            "feature_columns": self.feature_columns
        }

    def _evaluate(self, X_test: np.ndarray, y_test: np.ndarray) -> dict:
        """Evaluate model on test set."""
        y_pred = self.model.predict(X_test)
        y_prob = self.model.predict_proba(X_test)[:, 1]

        return {
            "accuracy": accuracy_score(y_test, y_pred),
            "precision": precision_score(y_test, y_pred, zero_division=0),
            "recall": recall_score(y_test, y_pred, zero_division=0),
            "f1": f1_score(y_test, y_pred, zero_division=0),
            "auc": roc_auc_score(y_test, y_prob),
            "confusion_matrix": confusion_matrix(y_test, y_pred).tolist(),
            "classification_report": classification_report(y_test, y_pred, output_dict=True)
        }

    def get_feature_importance(self) -> dict[str, float]:
        """Get feature importance from trained model."""
        if self.model is None:
            return {}

        importance = self.model.feature_importances_
        return dict(zip(self.feature_columns, importance))

    def save(self, path: str = None) -> str:
        """
        Save model bundle (model + metadata).

        Args:
            path: Optional path, defaults to models/model_bundle.joblib

        Returns:
            Path to saved model
        """
        if self.model is None:
            raise ValueError("No model to save. Train first.")

        if path is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            path = MODEL_DIR / f"model_{timestamp}.joblib"
        else:
            path = Path(path)

        bundle = {
            "model": self.model,
            "feature_columns": self.feature_columns,
            "best_params": self.best_params,
            "metrics": self.metrics,
            "feature_importance": self.get_feature_importance(),
            "trained_at": datetime.now().isoformat()
        }

        joblib.dump(bundle, path)
        logger.info(f"Model saved to {path}")

        # Also save as latest
        latest_path = MODEL_DIR / "model_latest.joblib"
        joblib.dump(bundle, latest_path)

        return str(path)

    @classmethod
    def load(cls, path: str = None) -> "ModelTrainer":
        """
        Load trained model from file.

        Args:
            path: Path to model file, defaults to latest

        Returns:
            ModelTrainer instance with loaded model
        """
        if path is None:
            path = MODEL_DIR / "model_latest.joblib"
        else:
            path = Path(path)

        if not path.exists():
            raise FileNotFoundError(f"Model not found: {path}")

        bundle = joblib.load(path)

        trainer = cls(feature_columns=bundle["feature_columns"])
        trainer.model = bundle["model"]
        trainer.best_params = bundle["best_params"]
        trainer.metrics = bundle["metrics"]

        logger.info(f"Model loaded from {path}")
        return trainer


def train_and_save(
    features_path: str = "",
    lookahead: int = 6,
    threshold: float = 0.005,
    fast: bool = True,
    half_life_days: float = None,
) -> dict:
    """
    Complete training pipeline: load data, train, save.

    Args:
        features_path: Path to features CSV
        lookahead: Candles to look ahead
        threshold: Min return for positive label
        fast: Use fast param grid
        half_life_days: Decay half-life for sample weighting
            - None: no decay (equal weights)
            - 30: aggressive (focus on recent month)
            - 45: moderate (recommended for intraday)
            - 60: gentle (more historical context)

    Returns:
        Training results dict
    """
    from backend.ml.labeling import prepare_training_data, DEFAULT_FEATURES_PATH

    if not features_path:
        features_path = DEFAULT_FEATURES_PATH

    # Prepare data with optional decay weights
    train_df, test_df, train_weights = prepare_training_data(
        features_path=features_path,
        lookahead=lookahead,
        threshold=threshold,
        half_life_days=half_life_days,
    )

    # Train with weights
    trainer = ModelTrainer()
    results = trainer.train(
        train_df,
        test_df,
        fast=fast,
        sample_weights=train_weights,
    )

    # Save
    model_path = trainer.save()
    results["model_path"] = model_path

    # Store decay config in results
    results["half_life_days"] = half_life_days
    results["decay_enabled"] = half_life_days is not None

    # Print summary
    print("\n" + "=" * 60)
    print("MODEL TRAINING COMPLETE")
    print("=" * 60)

    if half_life_days:
        print(f"\nDecay Weighting: half-life = {half_life_days} days")
        print(f"  (Recent data weighted higher than older data)")
    else:
        print(f"\nDecay Weighting: disabled (equal weights)")

    print(f"\nMetrics:")
    print(f"  Accuracy:  {results['metrics']['accuracy']:.3f}")
    print(f"  Precision: {results['metrics']['precision']:.3f}")
    print(f"  Recall:    {results['metrics']['recall']:.3f}")
    print(f"  F1 Score:  {results['metrics']['f1']:.3f}")
    print(f"  AUC:       {results['metrics']['auc']:.3f}")

    print(f"\nFeature Importance (Top 10):")
    importance = trainer.get_feature_importance()
    sorted_imp = sorted(importance.items(), key=lambda x: x[1], reverse=True)
    for name, imp in sorted_imp[:10]:
        print(f"  {name:25} {imp:.4f}")

    print(f"\nModel saved to: {model_path}")

    return results
