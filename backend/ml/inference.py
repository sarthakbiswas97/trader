"""
Model inference service for real-time predictions.
"""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np

from backend.core.logger import get_logger
from backend.ml.train_model import ModelTrainer
from backend.services.feature_engine import FeatureVector, FEATURE_COLUMNS

logger = get_logger(__name__)


@dataclass
class Prediction:
    """Prediction result with confidence and explanation."""
    symbol: str
    timestamp: datetime
    direction: str  # "UP" or "DOWN"
    probability: float  # 0-1, probability of UP
    confidence: float  # 0-1, how confident (distance from 0.5)
    top_features: list[tuple[str, float]]  # Top contributing features

    @property
    def should_trade(self) -> bool:
        """Returns True if confidence is high enough to trade."""
        return self.confidence >= 0.1  # 60% threshold (0.5 + 0.1 = 0.6)

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "direction": self.direction,
            "probability": self.probability,
            "confidence": self.confidence,
            "should_trade": self.should_trade,
            "top_features": self.top_features
        }


class PredictionService:
    """
    Real-time prediction service using trained XGBoost model.
    """

    def __init__(self, model_path: str = None):
        """
        Initialize prediction service.

        Args:
            model_path: Path to model file, loads latest if None
        """
        self.trainer = ModelTrainer.load(model_path)
        self.model = self.trainer.model
        self.feature_columns = self.trainer.feature_columns
        logger.info("PredictionService initialized")

    def predict(self, features: FeatureVector) -> Prediction:
        """
        Generate prediction from feature vector.

        Args:
            features: FeatureVector from FeatureEngine

        Returns:
            Prediction with direction, probability, and explanation
        """
        # Convert to array
        X = features.to_array().reshape(1, -1)

        # Get probability
        prob_up = self.model.predict_proba(X)[0, 1]

        # Determine direction and confidence
        direction = "UP" if prob_up > 0.5 else "DOWN"
        confidence = abs(prob_up - 0.5) * 2  # Scale to 0-1

        # Get feature contributions (simple importance-weighted)
        feature_importance = self.trainer.get_feature_importance()
        feature_values = dict(zip(self.feature_columns, features.to_array()))

        # Calculate contribution scores
        contributions = []
        for name, importance in feature_importance.items():
            value = feature_values.get(name, 0)
            # Normalize contribution
            contribution = importance * abs(value) if isinstance(value, (int, float)) else 0
            contributions.append((name, contribution))

        # Sort by contribution
        top_features = sorted(contributions, key=lambda x: x[1], reverse=True)[:5]

        return Prediction(
            symbol=features.symbol,
            timestamp=features.timestamp,
            direction=direction,
            probability=prob_up,
            confidence=confidence,
            top_features=top_features
        )

    def predict_batch(self, features_list: list[FeatureVector]) -> list[Prediction]:
        """Generate predictions for multiple feature vectors."""
        return [self.predict(f) for f in features_list]

    def predict_from_array(self, X: np.ndarray, symbol: str = "UNKNOWN") -> Prediction:
        """
        Generate prediction from raw feature array.

        Args:
            X: Feature array of shape (17,) or (1, 17)
            symbol: Symbol name for the prediction

        Returns:
            Prediction object
        """
        if X.ndim == 1:
            X = X.reshape(1, -1)

        prob_up = self.model.predict_proba(X)[0, 1]
        direction = "UP" if prob_up > 0.5 else "DOWN"
        confidence = abs(prob_up - 0.5) * 2

        return Prediction(
            symbol=symbol,
            timestamp=datetime.now(),
            direction=direction,
            probability=prob_up,
            confidence=confidence,
            top_features=[]
        )
