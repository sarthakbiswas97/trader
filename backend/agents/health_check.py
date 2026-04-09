"""
Morning health check agent.

Invoked by the scheduled Claude agent at ~9:00 AM IST. Verifies the trader's
operational state and takes safe actions to bring the system online:

  1. Auth status — if Kite session expired, write AUTH_NEEDED alert and STOP.
     (Auth requires user's Kite mobile app — never automated.)
  2. API health — verify the backend is responding.
  3. Pipeline (data) — if stale, trigger refresh and wait for completion.
  4. Bot — if not running and prerequisites met, start it.

Output:
    Prints a single JSON line to stdout with structured status. Exits 0 even
    on auth-required (the alert file is the signal). Exits non-zero only on
    unexpected errors (which the calling agent will surface).

Usage:
    python -m backend.agents.health_check [--base-url URL]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any

import httpx

from backend.agents.report_writer import write_alert

DEFAULT_BASE_URL = "http://localhost:8000"
DEFAULT_TIMEOUT = 10.0
PIPELINE_POLL_SECS = 5
PIPELINE_MAX_POLLS = 60  # 5 min total


@dataclass
class HealthResult:
    ok: bool
    auth_required: bool
    issues: list[str] = field(default_factory=list)
    actions_taken: list[str] = field(default_factory=list)
    components: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(asdict(self), default=str)


def _get(client: httpx.Client, path: str) -> dict[str, Any] | None:
    try:
        r = client.get(path)
        r.raise_for_status()
        return r.json()
    except httpx.HTTPError:
        return None


def _post(client: httpx.Client, path: str, json_body: dict | None = None) -> dict[str, Any] | None:
    try:
        r = client.post(path, json=json_body or {})
        r.raise_for_status()
        return r.json()
    except httpx.HTTPError:
        return None


def _wait_for_pipeline(client: httpx.Client) -> tuple[bool, str]:
    """Poll /bot/prepare/status until pipeline finishes or times out."""
    for _ in range(PIPELINE_MAX_POLLS):
        status = _get(client, "/api/v1/bot/prepare/status")
        if status is None:
            return False, "pipeline_status_unreachable"
        if status.get("error"):
            return False, f"pipeline_error: {status['error']}"
        if status.get("completed") or not status.get("running"):
            return True, status.get("current_step", "done")
        time.sleep(PIPELINE_POLL_SECS)
    return False, "pipeline_timeout"


def run_health_check(base_url: str = DEFAULT_BASE_URL) -> HealthResult:
    """Run the morning health check end-to-end."""
    result = HealthResult(ok=True, auth_required=False)
    today = date.today()

    with httpx.Client(base_url=base_url, timeout=DEFAULT_TIMEOUT) as client:
        # 1. API liveness
        live = _get(client, "/api/v1/health/live")
        if live is None:
            result.ok = False
            result.issues.append("api_unreachable")
            return result

        # 2. Auth status — if expired, write alert and stop here
        auth = _get(client, "/api/v1/auth/status")
        if auth is None:
            result.ok = False
            result.issues.append("auth_endpoint_unreachable")
            return result

        result.components["auth"] = auth

        if not auth.get("session_valid"):
            result.ok = False
            result.auth_required = True
            result.issues.append("kite_session_expired")
            alert_path = write_alert(
                category="morning",
                name="AUTH_NEEDED",
                day=today,
                content=(
                    f"# AUTH NEEDED — {today.isoformat()}\n\n"
                    "Kite session is expired. The morning health check stopped here.\n\n"
                    "**This is a manual step.** Zerodha 2FA requires a code from the "
                    "Kite mobile app and cannot be automated.\n\n"
                    "## To fix:\n\n"
                    "```bash\n"
                    "make auth          # local\n"
                    "make deploy-auth   # VPS\n"
                    "```\n\n"
                    "After auth completes, the next scheduled run will pick up automatically.\n"
                ),
            )
            result.actions_taken.append(f"wrote_alert:{alert_path}")
            return result

        # 3. Full health (broker, model, bot)
        health = _get(client, "/api/v1/health")
        if health is None:
            result.ok = False
            result.issues.append("health_endpoint_unreachable")
            return result

        result.components["health"] = health
        components = health.get("components", {})

        if not components.get("model_available"):
            result.ok = False
            result.issues.append("model_missing")

        if not components.get("broker_authenticated"):
            result.ok = False
            result.issues.append("broker_not_connected")

        # 4. Pipeline (data) — refresh if needed
        pipeline = _get(client, "/api/v1/bot/prepare/status")
        if pipeline is None:
            result.issues.append("pipeline_status_unreachable")
        else:
            result.components["pipeline"] = pipeline
            needs_refresh = not pipeline.get("completed") and not pipeline.get("running")
            if needs_refresh:
                trigger = _post(client, "/api/v1/bot/prepare", {})
                if trigger is None:
                    result.ok = False
                    result.issues.append("pipeline_trigger_failed")
                else:
                    result.actions_taken.append("triggered_pipeline")
                    ok, detail = _wait_for_pipeline(client)
                    if not ok:
                        result.ok = False
                        result.issues.append(detail)
                    else:
                        result.actions_taken.append(f"pipeline_complete:{detail}")

        # 5. Bot status — start if not running and prerequisites met
        bot = _get(client, "/api/v1/bot/status")
        if bot is None:
            result.issues.append("bot_status_unreachable")
        else:
            result.components["bot"] = bot
            if bot.get("status") != "running" and result.ok:
                start = _post(client, "/api/v1/bot/start", {})
                if start is None:
                    result.ok = False
                    result.issues.append("bot_start_failed")
                else:
                    result.actions_taken.append("bot_started")

    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    args = parser.parse_args()

    try:
        result = run_health_check(base_url=args.base_url)
    except Exception as exc:
        # Unexpected: surface non-zero so the calling agent investigates
        print(json.dumps({"ok": False, "auth_required": False, "issues": [f"unexpected:{exc}"]}))
        return 2

    print(result.to_json())
    return 0


if __name__ == "__main__":
    sys.exit(main())
