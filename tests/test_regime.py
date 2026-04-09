"""
Unit tests for the regime classifier.

Pure-function tests — no DB, no network. Verifies the score → regime mapping,
the daily-override path, and the 2-day persistence requirement.
"""

from __future__ import annotations

import pytest

from backend.strategies.regime import Regime, RegimeClassifier


@pytest.fixture
def classifier():
    return RegimeClassifier()


# =============================================================================
# Daily override
# =============================================================================


def test_daily_override_forces_weak_on_big_intraday_drop(classifier):
    regime = classifier.classify(
        nifty_close=22_000,
        nifty_dma_50=21_500,
        nifty_ret_5d=0.02,
        nifty_ret_1d=-0.01,  # -1% today, below -0.5% override threshold
        breadth_pct=0.6,
    )
    assert regime is Regime.WEAK


def test_no_override_when_intraday_drop_small(classifier):
    regime = classifier.classify(
        nifty_close=22_000,
        nifty_dma_50=21_500,
        nifty_ret_5d=0.02,
        nifty_ret_1d=-0.001,  # -0.1%, above threshold
        breadth_pct=0.6,
    )
    assert regime is not Regime.WEAK or regime == Regime.NEUTRAL


# =============================================================================
# Persistence: regime should not switch on a single day's signal
# =============================================================================


def test_bull_signal_does_not_immediately_switch_to_bull(classifier):
    # Starting in NEUTRAL. Single bullish day should NOT promote to BULL.
    regime = classifier.classify(
        nifty_close=22_000,
        nifty_dma_50=21_500,    # bullish trend (+1)
        nifty_ret_5d=0.02,      # bullish momentum (+1)
        nifty_ret_1d=0.005,     # no override
        breadth_pct=0.7,        # bullish breadth (+1)
    )
    assert regime is Regime.NEUTRAL  # persistence not yet met
    assert classifier._pending_regime is Regime.BULL
    assert classifier._pending_days == 1


def test_bull_signal_promotes_after_two_days(classifier):
    bullish_kwargs = dict(
        nifty_close=22_000,
        nifty_dma_50=21_500,
        nifty_ret_5d=0.02,
        nifty_ret_1d=0.005,
        breadth_pct=0.7,
    )
    classifier.classify(**bullish_kwargs)  # day 1 — pending
    regime = classifier.classify(**bullish_kwargs)  # day 2 — switch
    assert regime is Regime.BULL


def test_pending_resets_when_signal_flips(classifier):
    classifier.classify(
        nifty_close=22_000, nifty_dma_50=21_500, nifty_ret_5d=0.02,
        nifty_ret_1d=0.005, breadth_pct=0.7,
    )  # pending BULL
    assert classifier._pending_regime is Regime.BULL

    classifier.classify(
        nifty_close=22_000, nifty_dma_50=22_500, nifty_ret_5d=-0.02,
        nifty_ret_1d=0.001, breadth_pct=0.3,
    )  # bearish day, NEUTRAL or WEAK
    assert classifier._pending_regime is not Regime.BULL


# =============================================================================
# Reset
# =============================================================================


def test_reset_clears_state(classifier):
    classifier._current_regime = Regime.BULL
    classifier._pending_regime = Regime.WEAK
    classifier._pending_days = 1
    classifier.reset()
    assert classifier.current_regime is Regime.NEUTRAL
    assert classifier._pending_regime is None
    assert classifier._pending_days == 0


def test_status_shape(classifier):
    status = classifier.get_status()
    assert set(status.keys()) == {"regime", "pending", "pending_days"}
    assert status["regime"] == Regime.NEUTRAL.value
