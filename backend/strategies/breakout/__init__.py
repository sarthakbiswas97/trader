"""
Breakout Strategy — Detect and trade price breakouts.

Two setup types:
  1. Opening Breakout: PDH/PDL break in first 15 minutes
  2. Intraday Breakout: Consolidation range break after 9:30
"""

from backend.strategies.breakout.detector import BreakoutDetector, Setup
from backend.strategies.breakout.filters import filter_setups
from backend.strategies.breakout.ranker import rank_setups

__all__ = ["BreakoutDetector", "Setup", "filter_setups", "rank_setups"]
