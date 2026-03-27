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
    direction: str  # "UP", "DOWN", or "NEUTRAL"
    probability: float  # 0-1, probability of the predicted direction
    confidence: float  # 0-1, how confident (max class prob - second best)
    prob_up: float = 0.0  # Probability of UP class
    prob_down: float = 0.0  # Probability of DOWN class
    prob_neutral: float = 0.0  # Probability of NEUTRAL class
    top_features: list[tuple[str, float]] = None  # Top contributing features

    def __post_init__(self):
        if self.top_features is None:
            self.top_features = []

    @property
    def should_trade(self) -> bool:
        """Returns True if confidence is high enough to trade."""
        return self.confidence >= 0.2  # 20% confidence threshold

    @property
    def is_long_signal(self) -> bool:
        """Returns True if this is a tradeable BUY signal."""
        return self.direction == "UP" and self.should_trade

    @property
    def is_short_signal(self) -> bool:
        """Returns True if this is a tradeable SHORT signal."""
        return self.direction == "DOWN" and self.should_trade

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "direction": self.direction,
            "probability": self.probability,
            "confidence": self.confidence,
            "prob_up": self.prob_up,
            "prob_down": self.prob_down,
            "prob_neutral": self.prob_neutral,
            "should_trade": self.should_trade,
            "is_long_signal": self.is_long_signal,
            "is_short_signal": self.is_short_signal,
            "top_features": self.top_features,
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
        self.num_classes = self.trainer.num_classes
        logger.info("PredictionService initialized", num_classes=self.num_classes)

    def predict(self, features: FeatureVector) -> Prediction:
        """
        Generate prediction from feature vector.

        Args:
            features: FeatureVector from FeatureEngine

        Returns:
            Prediction with direction, probability, and explanation
        """
        X = features.to_array().reshape(1, -1)
        probs = self.model.predict_proba(X)[0]

        if self.num_classes == 3:
            # 3-class: DOWN=0, NEUTRAL=1, UP=2
            prob_down, prob_neutral, prob_up = float(probs[0]), float(probs[1]), float(probs[2])
            max_idx = int(np.argmax(probs))
            direction = ["DOWN", "NEUTRAL", "UP"][max_idx]
            probability = float(probs[max_idx])
            sorted_probs = sorted(probs, reverse=True)
            confidence = float(sorted_probs[0] - sorted_probs[1])
        else:
            # 2-class model → interpret as 3 directions using thresholds
            prob_up = float(probs[1])
            prob_down = float(probs[0])
            prob_neutral = 0.0

            if prob_up >= 0.6:
                direction = "UP"
                probability = prob_up
            elif prob_up <= 0.4:
                direction = "DOWN"
                probability = prob_down
            else:
                direction = "NEUTRAL"
                probability = 1.0 - abs(prob_up - 0.5) * 2  # Higher when closer to 0.5

            confidence = abs(prob_up - 0.5) * 2

        # Feature contributions
        top_features = self._get_top_features(features)

        return Prediction(
            symbol=features.symbol,
            timestamp=features.timestamp,
            direction=direction,
            probability=probability,
            confidence=confidence,
            prob_up=float(prob_up),
            prob_down=float(prob_down),
            prob_neutral=float(prob_neutral),
            top_features=top_features,
        )

    def _get_top_features(self, features: FeatureVector) -> list[tuple[str, float]]:
        """Get top contributing features for a prediction."""
        feature_importance = self.trainer.get_feature_importance()
        feature_values = dict(zip(self.feature_columns, features.to_array()))

        contributions = []
        for name, importance in feature_importance.items():
            value = feature_values.get(name, 0)
            contribution = importance * abs(value) if isinstance(value, (int, float)) else 0
            contributions.append((name, float(contribution)))

        return sorted(contributions, key=lambda x: x[1], reverse=True)[:5]

    def predict_batch(self, features_list: list[FeatureVector]) -> list[Prediction]:
        """Generate predictions for multiple feature vectors."""
        return [self.predict(f) for f in features_list]
