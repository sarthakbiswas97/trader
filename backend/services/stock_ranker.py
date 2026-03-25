"""
Stock Ranker - Rank stocks by ML signal quality for trading.
Filters and sorts prediction candidates for entry.
"""

from dataclasses import dataclass
from typing import Any

from backend.core.logger import get_logger
from backend.ml.inference import Prediction

logger = get_logger(__name__)


@dataclass
class RankedStock:
    """A stock ranked by signal quality."""
    symbol: str
    prediction: Prediction
    score: float
    rank: int
    scoring_details: dict[str, float]

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "direction": self.prediction.direction,
            "probability": self.prediction.probability,
            "confidence": self.prediction.confidence,
            "score": self.score,
            "rank": self.rank,
            "scoring_details": self.scoring_details,
            "top_features": self.prediction.top_features,
        }


class StockRanker:
    """
    Rank stocks by signal quality for trading.
    Filters predictions and scores them for entry priority.
    """

    def __init__(
        self,
        min_confidence: float = 0.6,
        min_probability: float = 0.55,
        max_stocks: int = 5,
    ):
        """
        Args:
            min_confidence: Minimum prediction confidence (0-1)
            min_probability: Minimum probability for UP direction
            max_stocks: Maximum number of stocks to return
        """
        self.min_confidence = min_confidence
        self.min_probability = min_probability
        self.max_stocks = max_stocks

        logger.info(
            "StockRanker initialized",
            min_confidence=min_confidence,
            min_probability=min_probability,
            max_stocks=max_stocks,
        )

    def rank(
        self,
        predictions: dict[str, Prediction],
        exclude_symbols: list[str] = None,
    ) -> list[RankedStock]:
        """
        Rank stocks by signal quality.

        Args:
            predictions: Dict mapping symbol to Prediction
            exclude_symbols: Symbols to exclude (e.g., already holding)

        Returns:
            List of RankedStock sorted by score (best first)
        """
        exclude_symbols = exclude_symbols or []
        candidates = []

        for symbol, pred in predictions.items():
            # Skip excluded symbols
            if symbol in exclude_symbols:
                continue

            # Filter criteria
            if not self._passes_filters(pred):
                continue

            # Calculate score
            score, details = self._calculate_score(pred)

            candidates.append(RankedStock(
                symbol=symbol,
                prediction=pred,
                score=score,
                rank=0,  # Will be set after sorting
                scoring_details=details,
            ))

        # Sort by score descending
        candidates.sort(key=lambda x: x.score, reverse=True)

        # Assign ranks
        for i, candidate in enumerate(candidates):
            candidate.rank = i + 1

        # Limit to max stocks
        top_candidates = candidates[:self.max_stocks]

        logger.info(
            "Stock ranking complete",
            total_predictions=len(predictions),
            candidates_after_filter=len(candidates),
            returned=len(top_candidates),
        )

        return top_candidates

    def _passes_filters(self, pred: Prediction) -> bool:
        """Check if prediction passes all filters."""
        # Only consider UP predictions
        if pred.direction != "UP":
            return False

        # Minimum confidence
        if pred.confidence < self.min_confidence:
            return False

        # Minimum probability
        if pred.probability < self.min_probability:
            return False

        return True

    def _calculate_score(self, pred: Prediction) -> tuple[float, dict[str, float]]:
        """
        Calculate signal quality score.

        Returns:
            Tuple of (total_score, scoring_details)
        """
        details = {}

        # Base score from probability (0-40 points)
        # prob of 0.55 -> 0, prob of 0.75 -> 40
        prob_score = (pred.probability - 0.55) / 0.2 * 40
        prob_score = max(0, min(40, prob_score))
        details["probability_score"] = prob_score

        # Confidence score (0-40 points)
        # confidence of 0.1 -> 0, confidence of 0.5 -> 40
        conf_score = (pred.confidence - 0.1) / 0.4 * 40
        conf_score = max(0, min(40, conf_score))
        details["confidence_score"] = conf_score

        # Feature alignment score (0-20 points)
        # Based on top contributing features
        feature_score = self._calculate_feature_score(pred)
        details["feature_score"] = feature_score

        total = prob_score + conf_score + feature_score
        details["total"] = total

        return total, details

    def _calculate_feature_score(self, pred: Prediction) -> float:
        """
        Calculate score based on feature contributions.
        Bonus for trend alignment and momentum features.
        """
        score = 10.0  # Base score

        if not pred.top_features:
            return score

        # Bonus for trend features in top 5
        trend_features = {"daily_trend", "hourly_trend", "momentum"}
        for name, _ in pred.top_features[:5]:
            if name in trend_features:
                score += 2.0

        return min(20, score)

    def get_top_stock(
        self,
        predictions: dict[str, Prediction],
        exclude_symbols: list[str] = None,
    ) -> RankedStock | None:
        """
        Get the single best stock to trade.

        Args:
            predictions: Dict mapping symbol to Prediction
            exclude_symbols: Symbols to exclude

        Returns:
            Best RankedStock or None if no candidates
        """
        ranked = self.rank(predictions, exclude_symbols)
        return ranked[0] if ranked else None

    def filter_by_confidence(
        self,
        predictions: dict[str, Prediction],
        min_confidence: float = None,
    ) -> dict[str, Prediction]:
        """
        Filter predictions by confidence threshold.

        Args:
            predictions: All predictions
            min_confidence: Override minimum confidence

        Returns:
            Filtered predictions dict
        """
        threshold = min_confidence or self.min_confidence
        return {
            symbol: pred
            for symbol, pred in predictions.items()
            if pred.confidence >= threshold
        }
