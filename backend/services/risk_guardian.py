"""
Risk Guardian - Hard risk limits that cannot be bypassed.
Protects capital through position limits, exposure limits, and circuit breakers.
Supports separate limits for long and short positions.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from backend.broker.base import Broker, Position
from backend.config import settings
from backend.core.exceptions import (
    CircuitBreakerTriggeredError,
    RiskLimitExceededError,
    TradingHaltedError,
)
from backend.core.logger import get_logger
from backend.ml.inference import Prediction
from backend.utils.time_utils import now_ist, can_place_new_entry

logger = get_logger(__name__)


@dataclass
class RiskConfig:
    """Risk management configuration — swing trading (multi-day holds).

    Stop-loss is ATR-based (dynamic per stock), not fixed %.
    Positions can be held for up to 7 trading days.
    No intraday force-exit — positions carry overnight (CNC).
    """

    # Long position limits
    max_long_position_pct: float = 0.05     # 5% of capital per long position
    max_long_exposure: float = 0.40         # 40% total long exposure (wider for swing)

    # Short position limits (tighter)
    max_short_position_pct: float = 0.03    # 3% of capital per short position
    max_short_exposure: float = 0.20        # 20% total short exposure

    # Combined limits
    max_total_exposure: float = 0.50        # 50% combined (swing needs room)

    # ATR-based stop-loss (multipliers, not fixed %)
    long_sl_atr_mult: float = 2.0           # SL = entry - ATR × 2
    short_sl_atr_mult: float = 2.0          # SL = entry + ATR × 2
    # Fallback fixed % if ATR unavailable
    long_stop_loss_pct: float = 0.05        # -5% hard SL fallback
    short_stop_loss_pct: float = 0.04       # -4% hard SL fallback

    # Take-profit: mean reversion target (EMA bounce)
    long_tp_atr_mult: float = 1.5           # TP = entry + ATR × 1.5
    short_tp_atr_mult: float = 1.5          # TP = entry - ATR × 1.5
    long_take_profit_pct: float = 0.04      # 4% hard TP fallback
    short_take_profit_pct: float = 0.04     # 4% hard TP fallback

    # Hold time limits (trading days, not minutes)
    max_hold_days: int = 7                  # 7 trading days max
    # Keep minutes for backward compat but set very high
    long_max_hold_minutes: float = 99999
    short_max_hold_minutes: float = 99999

    # General limits
    max_daily_loss_pct: float = 0.03        # 3% daily loss → circuit breaker
    max_drawdown_pct: float = 0.10          # 10% drawdown → halt
    trade_cooldown_secs: int = 60           # 60s between trades
    max_trades_per_day: int = 10            # Lower for swing (fewer trades)
    min_confidence: float = 0.20            # Min 20% confidence to trade

    # Feature toggle
    shorting_enabled: bool = True           # Can be toggled from frontend


@dataclass
class RiskCheckResult:
    """Result of a risk validation check."""
    passed: bool
    reason: str
    max_allocation: float = 0.0
    risk_score: float = 0.0
    checks_performed: dict = field(default_factory=dict)


class RiskGuardian:
    """
    Hard risk limits that cannot be bypassed.
    Supports separate limits for long and short positions.
    """

    def __init__(self, broker: Broker, config: RiskConfig = None):
        self.broker = broker
        self.config = config or RiskConfig()

        self.circuit_breaker_triggered = False
        self.circuit_breaker_reason = ""
        self.daily_pnl = 0.0
        self.peak_capital = 0.0
        self.trades_today = 0
        self.last_trade_time: datetime | None = None
        self.trading_day: datetime.date | None = None

        logger.info("RiskGuardian initialized")

    # =========================================================================
    # Internal helpers
    # =========================================================================

    def _reset_daily_counters(self) -> None:
        today = now_ist().date()
        if self.trading_day != today:
            self.trading_day = today
            self.trades_today = 0
            self.daily_pnl = 0.0
            self.circuit_breaker_triggered = False
            self.circuit_breaker_reason = ""
            logger.info("Daily counters reset", date=today)

    def _get_total_capital(self) -> float:
        margin = self.broker.get_margin()
        positions = self.broker.get_positions()
        invested = sum(abs(p.invested_value) for p in positions)
        return margin.available_cash + invested

    def _get_long_exposure(self) -> float:
        """Get long exposure as fraction of total capital."""
        positions = self.broker.get_positions()
        long_value = sum(p.invested_value for p in positions if p.quantity > 0)
        total = self._get_total_capital()
        return long_value / total if total > 0 else 0.0

    def _get_short_exposure(self) -> float:
        """Get short exposure as fraction of total capital."""
        positions = self.broker.get_positions()
        short_value = sum(abs(p.invested_value) for p in positions if p.quantity < 0)
        total = self._get_total_capital()
        return short_value / total if total > 0 else 0.0

    def _get_total_exposure(self) -> float:
        return self._get_long_exposure() + self._get_short_exposure()

    # =========================================================================
    # Validation
    # =========================================================================

    def validate_entry(
        self,
        symbol: str,
        prediction: Prediction,
        capital: float,
        is_short: bool = False,
    ) -> RiskCheckResult:
        """
        Run all risk checks before entry.

        Args:
            symbol: Trading symbol
            prediction: ML prediction
            capital: Available capital
            is_short: True for short entry, False for long entry
        """
        self._reset_daily_counters()

        side = "SHORT" if is_short else "LONG"

        # Check shorting toggle
        if is_short and not self.config.shorting_enabled:
            return RiskCheckResult(
                passed=False,
                reason="Shorting is disabled",
                checks_performed={"shorting_enabled": False},
            )

        checks = {
            "circuit_breaker": not self.circuit_breaker_triggered,
            "market_hours": can_place_new_entry(),
            "daily_loss": self._check_daily_loss(),
            "drawdown": self._check_drawdown(),
            "cooldown": self._check_trade_cooldown(),
            "trade_count": self.trades_today < self.config.max_trades_per_day,
            "confidence": prediction.confidence >= self.config.min_confidence,
        }

        # Direction-specific exposure check
        if is_short:
            checks["short_exposure"] = self._get_short_exposure() < self.config.max_short_exposure
        else:
            checks["long_exposure"] = self._get_long_exposure() < self.config.max_long_exposure

        checks["total_exposure"] = self._get_total_exposure() < self.config.max_total_exposure

        failed = [k for k, v in checks.items() if not v]

        if failed:
            reason = f"{side} failed: {', '.join(failed)}"
            logger.warning("Risk check failed", symbol=symbol, side=side, failed_checks=failed)
            return RiskCheckResult(
                passed=False,
                reason=reason,
                max_allocation=0,
                risk_score=0,
                checks_performed=checks,
            )

        max_alloc = self._calculate_max_allocation(capital, is_short)
        risk_score = self._calculate_risk_score()

        logger.info("Risk check passed", symbol=symbol, side=side, max_allocation=max_alloc)

        return RiskCheckResult(
            passed=True,
            reason=f"{side} checks passed",
            max_allocation=max_alloc,
            risk_score=risk_score,
            checks_performed=checks,
        )

    def _calculate_max_allocation(self, capital: float, is_short: bool) -> float:
        """Calculate max allocation based on direction-specific limits."""
        if is_short:
            max_per_position = capital * self.config.max_short_position_pct
            remaining = self.config.max_short_exposure - self._get_short_exposure()
        else:
            max_per_position = capital * self.config.max_long_position_pct
            remaining = self.config.max_long_exposure - self._get_long_exposure()

        # Also check total exposure remaining
        total_remaining = self.config.max_total_exposure - self._get_total_exposure()
        max_from_exposure = capital * min(remaining, total_remaining)

        return max(0, min(max_per_position, max_from_exposure))

    # =========================================================================
    # Exit conditions
    # =========================================================================

    def check_exit_conditions(
        self,
        position: Position,
        is_short: bool = False,
        holding_minutes: float = 0,
        managed_position: "ManagedPosition | None" = None,
    ) -> tuple[bool, str]:
        """
        Check if a position should be exited (swing mode).

        Uses ATR-based dynamic SL/TP set at entry time (stored on ManagedPosition).
        Falls back to fixed % if ATR prices aren't available.
        Does NOT force-exit at market close — positions carry overnight.

        Args:
            position: Current broker position (has current_price, pnl_percent)
            is_short: Whether this is a short position
            holding_minutes: How long position has been held
            managed_position: ManagedPosition with SL/TP prices from entry
        """
        current_price = position.current_price

        # 1. ATR-based stop-loss (dynamic, set at entry)
        if managed_position and managed_position.stop_loss_price:
            if is_short:
                if current_price >= managed_position.stop_loss_price:
                    return True, "stop_loss_atr"
            else:
                if current_price <= managed_position.stop_loss_price:
                    return True, "stop_loss_atr"

        # 2. Fallback fixed % stop-loss
        pnl_pct = position.pnl_percent
        stop_loss_pct = (self.config.short_stop_loss_pct if is_short else self.config.long_stop_loss_pct) * 100
        if pnl_pct <= -stop_loss_pct:
            return True, "stop_loss_hard"

        # 3. ATR-based take-profit target
        if managed_position and managed_position.target_price:
            if is_short:
                if current_price <= managed_position.target_price:
                    return True, "take_profit_atr"
            else:
                if current_price >= managed_position.target_price:
                    return True, "take_profit_atr"

        # 4. Fallback fixed % take-profit
        tp_pct = (self.config.short_take_profit_pct if is_short else self.config.long_take_profit_pct) * 100
        if pnl_pct >= tp_pct:
            return True, "take_profit_hard"

        # 5. Max hold days (convert minutes to trading days: ~375 min per day)
        holding_days = holding_minutes / 375
        if holding_days >= self.config.max_hold_days:
            return True, "max_hold_days"

        # 6. Circuit breaker — emergency exit
        if self.circuit_breaker_triggered:
            return True, "circuit_breaker"

        # NOTE: No market_close force-exit. Swing positions carry overnight.

        return False, ""

    # =========================================================================
    # Trade recording and circuit breaker
    # =========================================================================

    def record_trade(self, pnl: float = 0.0) -> None:
        self._reset_daily_counters()
        self.trades_today += 1
        self.daily_pnl += pnl
        self.last_trade_time = now_ist()
        self._check_and_trigger_circuit_breaker()

        logger.info("Trade recorded", trades_today=self.trades_today, daily_pnl=self.daily_pnl)

    def _check_daily_loss(self) -> bool:
        total = self._get_total_capital()
        if total <= 0:
            return False
        loss_pct = abs(min(self.daily_pnl, 0)) / total
        return loss_pct < self.config.max_daily_loss_pct

    def _check_drawdown(self) -> bool:
        total = self._get_total_capital()
        if self.peak_capital <= 0:
            self.peak_capital = total
            return True
        self.peak_capital = max(self.peak_capital, total)
        drawdown = (self.peak_capital - total) / self.peak_capital
        return drawdown < self.config.max_drawdown_pct

    def _check_trade_cooldown(self) -> bool:
        if self.last_trade_time is None:
            return True
        elapsed = (now_ist() - self.last_trade_time).total_seconds()
        return elapsed >= self.config.trade_cooldown_secs

    def _check_and_trigger_circuit_breaker(self) -> None:
        total = self._get_total_capital()
        if total > 0:
            loss_pct = abs(min(self.daily_pnl, 0)) / total
            if loss_pct >= self.config.max_daily_loss_pct:
                self._trigger_circuit_breaker(f"Daily loss limit: {loss_pct*100:.1f}%")
                return

        if self.peak_capital > 0:
            drawdown = (self.peak_capital - total) / self.peak_capital
            if drawdown >= self.config.max_drawdown_pct:
                self._trigger_circuit_breaker(f"Drawdown limit: {drawdown*100:.1f}%")

    def _trigger_circuit_breaker(self, reason: str) -> None:
        self.circuit_breaker_triggered = True
        self.circuit_breaker_reason = reason
        logger.error("Circuit breaker triggered", reason=reason)

    def _calculate_risk_score(self) -> float:
        total_exp = self._get_total_exposure()
        max_exp = self.config.max_total_exposure
        exposure_score = total_exp / max_exp if max_exp > 0 else 0
        trade_score = self.trades_today / self.config.max_trades_per_day
        total = self._get_total_capital()
        loss_score = abs(min(self.daily_pnl, 0)) / (total * self.config.max_daily_loss_pct) if total > 0 else 0
        return exposure_score * 0.4 + trade_score * 0.3 + loss_score * 0.3

    # =========================================================================
    # Status
    # =========================================================================

    def set_shorting_enabled(self, enabled: bool) -> None:
        self.config.shorting_enabled = enabled
        logger.info("Shorting toggled", enabled=enabled)

    def reset_circuit_breaker(self) -> None:
        self.circuit_breaker_triggered = False
        self.circuit_breaker_reason = ""
        logger.warning("Circuit breaker manually reset")

    def get_status(self) -> dict[str, Any]:
        return {
            "circuit_breaker_triggered": self.circuit_breaker_triggered,
            "circuit_breaker_reason": self.circuit_breaker_reason,
            "trades_today": self.trades_today,
            "max_trades": self.config.max_trades_per_day,
            "daily_pnl": self.daily_pnl,
            "daily_loss_limit": self.config.max_daily_loss_pct * self._get_total_capital(),
            "long_exposure": self._get_long_exposure(),
            "max_long_exposure": self.config.max_long_exposure,
            "short_exposure": self._get_short_exposure(),
            "max_short_exposure": self.config.max_short_exposure,
            "total_exposure": self._get_total_exposure(),
            "max_total_exposure": self.config.max_total_exposure,
            "risk_score": self._calculate_risk_score(),
            "shorting_enabled": self.config.shorting_enabled,
        }
