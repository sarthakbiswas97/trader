"""
Unit tests for RiskGuardian — the safety-critical layer.

Focuses on the math + state machine. Anything that depends on real market
hours is patched. The goal is to lock the contract: position limits, circuit
breakers, exit conditions, exposure tracking.
"""

from __future__ import annotations

import pytest

from backend.broker.base import Position, ProductType
from backend.services.risk_guardian import RiskConfig, RiskGuardian


@pytest.fixture
def guardian(fake_broker):
    return RiskGuardian(fake_broker, config=RiskConfig())


@pytest.fixture
def force_market_open(monkeypatch):
    """Pretend the market is open for validate_entry tests."""
    monkeypatch.setattr(
        "backend.services.risk_guardian.can_place_new_entry",
        lambda: True,
    )


# =============================================================================
# Exposure tracking
# =============================================================================


def test_long_exposure_with_no_positions_is_zero(guardian, fake_broker):
    assert guardian._get_long_exposure() == 0.0
    assert guardian._get_short_exposure() == 0.0
    assert guardian._get_total_exposure() == 0.0


def test_long_exposure_after_adding_long_position(guardian, fake_broker):
    fake_broker.add_position("RELIANCE", quantity=10, avg_price=2_000)  # ₹20k invested
    # Total capital: 100k cash + 20k invested = 120k. Exposure = 20k / 120k.
    expected = 20_000 / 120_000
    assert guardian._get_long_exposure() == pytest.approx(expected, rel=1e-6)
    assert guardian._get_short_exposure() == 0.0


def test_short_exposure_after_adding_short_position(guardian, fake_broker):
    fake_broker.add_position("RELIANCE", quantity=-10, avg_price=2_000)
    # invested_value of a short is negative, _get_short_exposure abs()es it
    assert guardian._get_short_exposure() > 0
    assert guardian._get_long_exposure() == 0.0


# =============================================================================
# Max allocation
# =============================================================================


def test_long_max_allocation_capped_at_per_position_pct(guardian):
    # Long max = 5% of 100k = 5000
    alloc = guardian._calculate_max_allocation(capital=100_000, is_short=False)
    assert alloc == pytest.approx(5_000, rel=1e-6)


def test_short_max_allocation_uses_short_position_pct(guardian):
    # Short max = 3% of 100k = 3000
    alloc = guardian._calculate_max_allocation(capital=100_000, is_short=True)
    assert alloc == pytest.approx(3_000, rel=1e-6)


# =============================================================================
# Exit conditions — long
# =============================================================================


def _long_position(symbol="RELIANCE", avg=100.0, current=100.0) -> Position:
    return Position(
        symbol=symbol,
        quantity=10,
        avg_price=avg,
        current_price=current,
        product=ProductType.MIS,
    )


def test_long_hits_fixed_stop_loss(guardian):
    # Default long_stop_loss_pct = 5% → -5% pnl_percent triggers
    pos = _long_position(avg=100, current=94)  # -6%
    should_exit, reason = guardian.check_exit_conditions(pos, is_short=False)
    assert should_exit is True
    assert reason == "stop_loss_hard"


def test_long_hits_fixed_take_profit(guardian):
    pos = _long_position(avg=100, current=105)  # +5%, > 4% TP
    should_exit, reason = guardian.check_exit_conditions(pos, is_short=False)
    assert should_exit is True
    assert reason == "take_profit_hard"


def test_long_within_band_does_not_exit(guardian):
    pos = _long_position(avg=100, current=102)  # +2%
    should_exit, _ = guardian.check_exit_conditions(pos, is_short=False)
    assert should_exit is False


def test_long_exits_on_circuit_breaker(guardian):
    guardian.circuit_breaker_triggered = True
    pos = _long_position(avg=100, current=101)  # neutral
    should_exit, reason = guardian.check_exit_conditions(pos, is_short=False)
    assert should_exit is True
    assert reason == "circuit_breaker"


# =============================================================================
# Circuit breaker
# =============================================================================


def test_circuit_breaker_triggers_on_daily_loss(guardian, fake_broker):
    # Capital ~100k, max_daily_loss_pct = 3% → 3000 is the trigger
    guardian.peak_capital = fake_broker._cash
    guardian.record_trade(pnl=-3_500)
    assert guardian.circuit_breaker_triggered is True
    assert "Daily loss" in guardian.circuit_breaker_reason


def test_circuit_breaker_does_not_trigger_below_threshold(guardian):
    guardian.record_trade(pnl=-500)
    assert guardian.circuit_breaker_triggered is False


def test_get_status_shape(guardian):
    status = guardian.get_status()
    expected_keys = {
        "circuit_breaker_triggered",
        "circuit_breaker_reason",
        "trades_today",
        "max_trades",
        "daily_pnl",
        "daily_loss_limit",
        "long_exposure",
        "max_long_exposure",
        "short_exposure",
        "max_short_exposure",
        "total_exposure",
        "max_total_exposure",
        "risk_score",
        "shorting_enabled",
    }
    assert expected_keys.issubset(status.keys())


# =============================================================================
# validate_entry — guarded by market hours patch
# =============================================================================


def test_validate_entry_blocks_when_circuit_breaker_active(
    guardian, sample_prediction, force_market_open
):
    from backend.utils.time_utils import now_ist
    # Pre-set trading_day so _reset_daily_counters doesn't wipe our flag
    guardian.trading_day = now_ist().date()
    guardian.circuit_breaker_triggered = True
    result = guardian.validate_entry("RELIANCE", sample_prediction, capital=100_000)
    assert result.passed is False
    assert "circuit_breaker" in result.checks_performed
    assert result.checks_performed["circuit_breaker"] is False


def test_validate_entry_blocks_low_confidence(guardian, sample_prediction, force_market_open):
    sample_prediction.confidence = 0.05  # below min_confidence (0.20)
    result = guardian.validate_entry("RELIANCE", sample_prediction, capital=100_000)
    assert result.passed is False


def test_validate_entry_blocks_short_when_disabled(guardian, sample_prediction, force_market_open):
    guardian.config.shorting_enabled = False
    result = guardian.validate_entry(
        "RELIANCE", sample_prediction, capital=100_000, is_short=True
    )
    assert result.passed is False
    assert "Shorting is disabled" in result.reason


def test_validate_entry_passes_clean_long(guardian, sample_prediction, force_market_open):
    result = guardian.validate_entry("RELIANCE", sample_prediction, capital=100_000)
    assert result.passed is True
    assert result.max_allocation > 0
