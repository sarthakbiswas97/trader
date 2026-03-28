"""
Setup Filters — Remove low-quality setups before ranking.

Filters are strict, rule-based checks that remove obvious bad trades.
"""

from backend.strategies.breakout.detector import Setup
from backend.core.logger import get_logger

logger = get_logger(__name__)

# Minimum score thresholds
MIN_OPENING_SCORE = 20
MIN_INTRADAY_SCORE = 25

# Maximum setups to pass through (prevent overtrading)
MAX_SETUPS_PER_SCAN = 10


def filter_setups(
    setups: list[Setup],
    already_traded_today: set[str] = None,
    held_symbols: set[str] = None,
) -> list[Setup]:
    """
    Filter out low-quality setups.

    Args:
        setups: Raw detected setups
        already_traded_today: Symbols already traded today (max 1 per stock)
        held_symbols: Symbols with open positions

    Returns:
        Filtered list of high-quality setups
    """
    already_traded_today = already_traded_today or set()
    held_symbols = held_symbols or set()

    filtered = []

    for setup in setups:
        # Skip if already traded this stock today
        if setup.symbol in already_traded_today:
            continue

        # Skip if already holding this stock
        if setup.symbol in held_symbols:
            continue

        # Minimum score threshold
        min_score = MIN_OPENING_SCORE if setup.setup_type == "opening" else MIN_INTRADAY_SCORE
        if setup.score < min_score:
            continue

        # Volume must be meaningful
        if setup.volume_ratio < 1.3:
            continue

        # Candle must show conviction
        if setup.candle_strength < 0.5:
            continue

        filtered.append(setup)

    # Sort by score and limit
    filtered.sort(key=lambda s: s.score, reverse=True)
    filtered = filtered[:MAX_SETUPS_PER_SCAN]

    if filtered:
        logger.info(
            "Setups filtered",
            input=len(setups),
            output=len(filtered),
            top_symbol=filtered[0].symbol if filtered else None,
        )

    return filtered
