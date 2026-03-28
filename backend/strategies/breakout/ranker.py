"""
Setup Ranker — Score and rank filtered setups.

Phase 1: Rule-based scoring (current)
Phase 2: ML-based ranking (future — predict which breakouts follow through)
"""

from backend.strategies.breakout.detector import Setup
from backend.core.logger import get_logger

logger = get_logger(__name__)


def rank_setups(
    setups: list[Setup],
    max_trades: int = 5,
) -> list[Setup]:
    """
    Rank setups by quality and return top N.

    Scoring factors:
      - Volume ratio (higher = more conviction)
      - Candle strength (stronger body = more conviction)
      - Consolidation tightness (tighter = better breakout)
      - Setup type (opening breakouts get slight priority — higher vol)

    Args:
        setups: Filtered setups
        max_trades: Maximum number to select

    Returns:
        Top N setups, sorted best-first
    """
    if not setups:
        return []

    # Score each setup
    scored = []
    for setup in setups:
        score = setup.score

        # Bonus for opening setups (tend to have more follow-through)
        if setup.setup_type == "opening":
            score *= 1.1

        # Bonus for very high volume (2x+ avg)
        if setup.volume_ratio >= 2.0:
            score *= 1.15

        scored.append((score, setup))

    # Sort by score descending
    scored.sort(key=lambda x: x[0], reverse=True)

    # Take top N
    top = [setup for _, setup in scored[:max_trades]]

    if top:
        logger.info(
            "Setups ranked",
            total=len(setups),
            selected=len(top),
            top=f"{top[0].symbol} ({top[0].direction}, score={top[0].score:.0f})",
        )

    return top
