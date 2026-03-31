"""
Reversal scoring — shared ranking logic.

Used by both multi-engine (live) and backtests.
Single source of truth for how stocks are ranked.
"""

import pandas as pd

from backend.services.historical_data import HistoricalDataService


def compute_reversal_scores(
    symbols: list[str],
    prices: dict[str, float],
    ds: HistoricalDataService | None = None,
) -> pd.DataFrame:
    """
    Rank stocks by reversal score (biggest losers ranked highest).

    Args:
        symbols: Stock universe to rank
        prices: Current LTP for each symbol
        ds: HistoricalDataService instance (created if None)

    Returns:
        DataFrame with columns: ret_5d, ret_10d, ret_21d, price, score
        Indexed by symbol, sorted by score descending (most oversold first).
        Empty DataFrame if insufficient data.
    """
    if ds is None:
        ds = HistoricalDataService()

    raw_scores = {}
    for symbol in symbols:
        df = ds.load_candles(symbol, "daily")
        if df.empty or len(df) < 25:
            continue

        close = df["close"]
        current = prices.get(symbol, close.iloc[-1])

        if len(close) >= 21 and close.iloc[-5] > 0:
            raw_scores[symbol] = {
                "ret_5d": (current - close.iloc[-5]) / close.iloc[-5],
                "ret_10d": (current - close.iloc[-10]) / close.iloc[-10] if close.iloc[-10] > 0 else 0,
                "ret_21d": (current - close.iloc[-21]) / close.iloc[-21] if close.iloc[-21] > 0 else 0,
                "price": current,
            }

    if len(raw_scores) < 5:
        return pd.DataFrame()

    score_df = pd.DataFrame(raw_scores).T

    # Reversal ranking: biggest losers get highest score
    # ascending=False → lowest return → highest percentile rank
    score_df["score"] = (
        score_df["ret_5d"].rank(ascending=False, pct=True)
        + score_df["ret_10d"].rank(ascending=False, pct=True)
        + score_df["ret_21d"].rank(ascending=False, pct=True)
    ) / 3

    return score_df.sort_values("score", ascending=False)
