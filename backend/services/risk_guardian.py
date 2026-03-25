"""
Risk Guardian - Hard risk limits that cannot be bypassed.
Protects capital through position limits, exposure limits, and circuit breakers.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
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
from backend.utils.time_utils import now_ist, is_market_open, can_place_new_entry

logger = get_logger(__name__)


@dataclass
class RiskConfig:
    """Risk management configuration."""
    max_position_pct: float = 0.05      # 5% of capital per position
    max_total_exposure: float = 0.20    # 20% total exposure
    max_daily_loss_pct: float = 0.03    # 3% daily loss limit
    max_drawdown_pct: float = 0.10      # 10% drawdown halt
    trade_cooldown_secs: int = 60       # 60s between trades
    max_trades_per_day: int = 20        # Max trades per day
    min_confidence: float = 0.6         # Min prediction confidence


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
    Acts as the last line of defense before any trade execution.
    """

    def __init__(
        self,
        broker: Broker,
        config: RiskConfig = None,
    ):
        self.broker = broker
        self.config = config or RiskConfig(
            max_position_pct=settings.max_position_pct,
            max_total_exposure=settings.max_total_exposure,
            max_daily_loss_pct=settings.max_daily_loss_pct,
            max_drawdown_pct=settings.max_drawdown_pct,
            trade_cooldown_secs=settings.trade_cooldown_secs,
            max_trades_per_day=settings.max_trades_per_day,
        )

        self.circuit_breaker_triggered = False
        self.circuit_breaker_reason = ""
        self.daily_pnl = 0.0
        self.peak_capital = 0.0
        self.trades_today = 0
        self.last_trade_time: datetime | None = None
        self.trading_day: datetime.date | None = None

        logger.info("RiskGuardian initialized", config=self.config)

    def _reset_daily_counters(self) -> None:
        """Reset daily counters at the start of each trading day."""
        today = now_ist().date()
        if self.trading_day != today:
            self.trading_day = today
            self.trades_today = 0
            self.daily_pnl = 0.0
            self.circuit_breaker_triggered = False
            self.circuit_breaker_reason = ""
            logger.info("Daily counters reset", date=today)

    def _get_total_capital(self) -> float:
        """Get total capital (available + invested)."""
        margin = self.broker.get_margin()
        positions = self.broker.get_positions()
        invested = sum(p.invested_value for p in positions)
        return margin.available_cash + invested

    def _get_current_exposure(self) -> float:
        """Get current exposure as fraction of total capital."""
        positions = self.broker.get_positions()
        invested = sum(p.invested_value for p in positions)
        total = self._get_total_capital()
        return invested / total if total > 0 else 0.0

    def _check_circuit_breaker(self) -> bool:
        """Check if circuit breaker is triggered."""
        return not self.circuit_breaker_triggered

    def _check_market_hours(self) -> bool:
        """Check if market is open and accepting new entries."""
        return can_place_new_entry()

    def _check_daily_loss(self) -> bool:
        """Check if daily loss limit is exceeded."""
        total = self._get_total_capital()
        if total <= 0:
            return False
        loss_pct = abs(min(self.daily_pnl, 0)) / total
        return loss_pct < self.config.max_daily_loss_pct

    def _check_drawdown(self) -> bool:
        """Check if drawdown limit is exceeded."""
        total = self._get_total_capital()
        if self.peak_capital <= 0:
            self.peak_capital = total
            return True

        self.peak_capital = max(self.peak_capital, total)
        drawdown = (self.peak_capital - total) / self.peak_capital
        return drawdown < self.config.max_drawdown_pct

    def _check_total_exposure(self) -> bool:
        """Check if total exposure limit is exceeded."""
        exposure = self._get_current_exposure()
        return exposure < self.config.max_total_exposure

    def _check_trade_cooldown(self) -> bool:
        """Check if enough time has passed since last trade."""
        if self.last_trade_time is None:
            return True
        elapsed = (now_ist() - self.last_trade_time).total_seconds()
        return elapsed >= self.config.trade_cooldown_secs

    def _check_trade_count(self) -> bool:
        """Check if max trades per day is exceeded."""
        return self.trades_today < self.config.max_trades_per_day

    def _check_confidence(self, prediction: Prediction) -> bool:
        """Check if prediction confidence meets minimum threshold."""
        return prediction.confidence >= self.config.min_confidence

    def validate_entry(
        self,
        symbol: str,
        prediction: Prediction,
        capital: float,
    ) -> RiskCheckResult:
        """
        Run all risk checks before entry.

        Args:
            symbol: Trading symbol
            prediction: ML prediction for the symbol
            capital: Available capital

        Returns:
            RiskCheckResult with pass/fail and details
        """
        self._reset_daily_counters()

        checks = {
            "circuit_breaker": self._check_circuit_breaker(),
            "market_hours": self._check_market_hours(),
            "daily_loss": self._check_daily_loss(),
            "drawdown": self._check_drawdown(),
            "exposure": self._check_total_exposure(),
            "cooldown": self._check_trade_cooldown(),
            "trade_count": self._check_trade_count(),
            "confidence": self._check_confidence(prediction),
        }

        failed = [k for k, v in checks.items() if not v]

        if failed:
            reason = f"Failed: {', '.join(failed)}"
            logger.warning(
                "Risk check failed",
                symbol=symbol,
                failed_checks=failed,
            )
            return RiskCheckResult(
                passed=False,
                reason=reason,
                max_allocation=0,
                risk_score=0,
                checks_performed=checks,
            )

        # Calculate max allocation based on volatility and position limits
        max_alloc = self._calculate_max_allocation(symbol, capital)

        # Calculate risk score (0-1, higher = riskier)
        risk_score = self._calculate_risk_score()

        logger.info(
            "Risk check passed",
            symbol=symbol,
            max_allocation=max_alloc,
            risk_score=risk_score,
        )

        return RiskCheckResult(
            passed=True,
            reason="All checks passed",
            max_allocation=max_alloc,
            risk_score=risk_score,
            checks_performed=checks,
        )

    def _calculate_max_allocation(self, symbol: str, capital: float) -> float:
        """
        Calculate maximum allocation for a position.
        Uses position limit and remaining exposure capacity.
        """
        # Max per position
        max_per_position = capital * self.config.max_position_pct

        # Remaining exposure capacity
        current_exposure = self._get_current_exposure()
        remaining_exposure = self.config.max_total_exposure - current_exposure
        max_from_exposure = capital * remaining_exposure

        return min(max_per_position, max_from_exposure)

    def _calculate_risk_score(self) -> float:
        """
        Calculate current risk score (0-1).
        Higher score = more risk taken.
        """
        exposure_score = self._get_current_exposure() / self.config.max_total_exposure
        trade_score = self.trades_today / self.config.max_trades_per_day

        total = self._get_total_capital()
        loss_score = abs(min(self.daily_pnl, 0)) / (total * self.config.max_daily_loss_pct) if total > 0 else 0

        # Weighted average
        return (exposure_score * 0.4 + trade_score * 0.3 + loss_score * 0.3)

    def check_exit_conditions(self, position: Position) -> tuple[bool, str]:
        """
        Check if a position should be exited.

        Args:
            position: Current position to check

        Returns:
            Tuple of (should_exit, reason)
        """
        # 1. Stop-loss (2% default)
        stop_loss_pct = -2.0
        if position.pnl_percent <= stop_loss_pct:
            return True, "stop_loss"

        # 2. Take profit (2% default)
        take_profit_pct = 2.0
        if position.pnl_percent >= take_profit_pct:
            return True, "take_profit"

        # 3. End of day (square off MIS positions)
        if not can_place_new_entry():
            return True, "market_close"

        # 4. Circuit breaker triggered
        if self.circuit_breaker_triggered:
            return True, "circuit_breaker"

        return False, ""

    def record_trade(self, pnl: float = 0.0) -> None:
        """Record a trade for tracking."""
        self._reset_daily_counters()
        self.trades_today += 1
        self.daily_pnl += pnl
        self.last_trade_time = now_ist()

        # Check if we should trigger circuit breaker
        self._check_and_trigger_circuit_breaker()

        logger.info(
            "Trade recorded",
            trades_today=self.trades_today,
            daily_pnl=self.daily_pnl,
        )

    def _check_and_trigger_circuit_breaker(self) -> None:
        """Check conditions and trigger circuit breaker if needed."""
        total = self._get_total_capital()

        # Daily loss limit
        if total > 0:
            loss_pct = abs(min(self.daily_pnl, 0)) / total
            if loss_pct >= self.config.max_daily_loss_pct:
                self._trigger_circuit_breaker(
                    f"Daily loss limit exceeded: {loss_pct*100:.1f}%"
                )
                return

        # Drawdown limit
        if self.peak_capital > 0:
            drawdown = (self.peak_capital - total) / self.peak_capital
            if drawdown >= self.config.max_drawdown_pct:
                self._trigger_circuit_breaker(
                    f"Drawdown limit exceeded: {drawdown*100:.1f}%"
                )
                return

    def _trigger_circuit_breaker(self, reason: str) -> None:
        """Trigger the circuit breaker and halt trading."""
        self.circuit_breaker_triggered = True
        self.circuit_breaker_reason = reason
        logger.error("Circuit breaker triggered", reason=reason)

    def reset_circuit_breaker(self) -> None:
        """Manually reset the circuit breaker (use with caution)."""
        self.circuit_breaker_triggered = False
        self.circuit_breaker_reason = ""
        logger.warning("Circuit breaker manually reset")

    def get_status(self) -> dict[str, Any]:
        """Get current risk status."""
        return {
            "circuit_breaker_triggered": self.circuit_breaker_triggered,
            "circuit_breaker_reason": self.circuit_breaker_reason,
            "trades_today": self.trades_today,
            "max_trades": self.config.max_trades_per_day,
            "daily_pnl": self.daily_pnl,
            "daily_loss_limit": self.config.max_daily_loss_pct * self._get_total_capital(),
            "current_exposure": self._get_current_exposure(),
            "max_exposure": self.config.max_total_exposure,
            "risk_score": self._calculate_risk_score(),
        }
