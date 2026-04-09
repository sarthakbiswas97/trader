"""
Live monitor agent — invoked every 5 min during market hours by /loop.

Polls bot status, risk state, and recent cycles. Returns a structured JSON
result the calling Claude agent can act on.

Alerts surfaced (any of these set healthy=False):
  - bot_not_running         Bot stopped unexpectedly
  - circuit_breaker_active  Risk guardian tripped
  - daily_loss_breach       Daily P&L below the alert threshold
  - stale_cycles            Last execution cycle older than threshold
  - status_unreachable      One of the API endpoints failed

Usage:
    python -m backend.agents.live_monitor [--base-url URL] [--loss-alert-pct 2.0]
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

DEFAULT_BASE_URL = "http://localhost:8000"
DEFAULT_TIMEOUT = 5.0
STALE_CYCLE_MINUTES = 10
DEFAULT_LOSS_ALERT_PCT = 2.0


@dataclass
class MonitorResult:
    healthy: bool
    alerts: list[str] = field(default_factory=list)
    snapshot: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(asdict(self), default=str)


def _get(client: httpx.Client, path: str) -> dict[str, Any] | None:
    try:
        r = client.get(path)
        r.raise_for_status()
        return r.json()
    except httpx.HTTPError:
        return None


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _is_stale(last_cycle_iso: str | None, now: datetime, max_age_min: int) -> bool:
    last = _parse_iso(last_cycle_iso)
    if last is None:
        return False
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    return (now - last) > timedelta(minutes=max_age_min)


def run_monitor(
    base_url: str = DEFAULT_BASE_URL,
    loss_alert_pct: float = DEFAULT_LOSS_ALERT_PCT,
    now: datetime | None = None,
) -> MonitorResult:
    """Run a single monitor pass."""
    result = MonitorResult(healthy=True)
    now = now or datetime.now(timezone.utc)

    with httpx.Client(base_url=base_url, timeout=DEFAULT_TIMEOUT) as client:
        bot = _get(client, "/api/v1/bot/status")
        if bot is None:
            result.healthy = False
            result.alerts.append("status_unreachable:bot")
            return result
        result.snapshot["bot"] = bot

        if bot.get("status") != "running":
            result.healthy = False
            result.alerts.append("bot_not_running")

        if _is_stale(bot.get("last_cycle"), now, STALE_CYCLE_MINUTES):
            result.healthy = False
            result.alerts.append("stale_cycles")

        risk = _get(client, "/api/v1/bot/risk")
        if risk is None:
            # Risk endpoint requires bot started — only treat as alert if bot is running
            if bot.get("status") == "running":
                result.healthy = False
                result.alerts.append("status_unreachable:risk")
        else:
            result.snapshot["risk"] = risk

            if risk.get("circuit_breaker_triggered"):
                result.healthy = False
                result.alerts.append("circuit_breaker_active")

            daily_pnl = float(risk.get("daily_pnl") or 0.0)
            daily_loss_limit = float(risk.get("daily_loss_limit") or 0.0)
            if daily_loss_limit > 0:
                loss_pct = abs(min(daily_pnl, 0.0)) / daily_loss_limit * 3.0  # daily_loss_limit is 3% of capital
                if loss_pct * 100 >= loss_alert_pct:
                    result.healthy = False
                    result.alerts.append(f"daily_loss_breach:{loss_pct*100:.2f}%")

    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--loss-alert-pct", type=float, default=DEFAULT_LOSS_ALERT_PCT)
    args = parser.parse_args()

    try:
        result = run_monitor(base_url=args.base_url, loss_alert_pct=args.loss_alert_pct)
    except Exception as exc:
        print(json.dumps({"healthy": False, "alerts": [f"unexpected:{exc}"], "snapshot": {}}))
        return 2

    print(result.to_json())
    return 0


if __name__ == "__main__":
    sys.exit(main())
