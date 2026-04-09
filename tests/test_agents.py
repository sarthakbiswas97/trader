"""
Unit tests for the ops agents (health_check, live_monitor, post_market_report).

Mocks the HTTP layer with httpx.MockTransport so tests are hermetic and fast.
The post_market_report tests use an in-memory SQLite session via monkey-patching.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

from backend.agents import health_check, live_monitor, report_writer


# =============================================================================
# Helpers
# =============================================================================


def _route_transport(routes: dict[tuple[str, str], dict]) -> httpx.MockTransport:
    """Build a MockTransport that returns canned responses for (method, path) pairs."""
    def handler(request: httpx.Request) -> httpx.Response:
        key = (request.method, request.url.path)
        if key not in routes:
            return httpx.Response(404, json={"detail": f"unrouted {key}"})
        spec = routes[key]
        return httpx.Response(spec.get("status", 200), json=spec.get("body", {}))

    return httpx.MockTransport(handler)


@pytest.fixture
def patch_httpx_client(monkeypatch):
    """Replace httpx.Client with one that uses a MockTransport for the test."""
    holder = {"transport": None}

    real_client_init = httpx.Client.__init__

    def _patched_init(self, *args, **kwargs):
        kwargs.setdefault("transport", holder["transport"])
        real_client_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.Client, "__init__", _patched_init)
    return holder


# =============================================================================
# report_writer
# =============================================================================


def test_write_report_creates_directory_and_file(tmp_path, monkeypatch):
    monkeypatch.setattr(report_writer, "REPORTS_ROOT", tmp_path)
    path = report_writer.write_report("post_market", date(2026, 4, 9), "# hello")
    assert path.exists()
    assert path.read_text() == "# hello"
    assert path.parent.name == "post_market"


def test_write_alert_uses_named_filename(tmp_path, monkeypatch):
    monkeypatch.setattr(report_writer, "REPORTS_ROOT", tmp_path)
    path = report_writer.write_alert("morning", "AUTH_NEEDED", date(2026, 4, 9), "go auth")
    assert path.name == "AUTH_NEEDED_2026-04-09.md"


# =============================================================================
# health_check
# =============================================================================


def test_health_check_writes_alert_when_session_expired(tmp_path, monkeypatch, patch_httpx_client):
    monkeypatch.setattr(report_writer, "REPORTS_ROOT", tmp_path)
    monkeypatch.setattr(health_check, "write_alert", report_writer.write_alert)

    routes = {
        ("GET", "/api/v1/health/live"): {"body": {"status": "ok"}},
        ("GET", "/api/v1/auth/status"): {
            "body": {"authenticated": False, "session_valid": False}
        },
    }
    patch_httpx_client["transport"] = _route_transport(routes)

    result = health_check.run_health_check(base_url="http://test")

    assert result.ok is False
    assert result.auth_required is True
    assert "kite_session_expired" in result.issues
    # alert file written
    alerts = list((tmp_path / "morning").glob("AUTH_NEEDED_*.md"))
    assert len(alerts) == 1


def test_health_check_starts_bot_when_idle(monkeypatch, patch_httpx_client):
    routes = {
        ("GET", "/api/v1/health/live"): {"body": {"status": "ok"}},
        ("GET", "/api/v1/auth/status"): {
            "body": {"authenticated": True, "session_valid": True}
        },
        ("GET", "/api/v1/health"): {
            "body": {
                "status": "healthy",
                "components": {
                    "api": True,
                    "model_available": True,
                    "broker_authenticated": True,
                    "bot_running": False,
                },
            }
        },
        ("GET", "/api/v1/bot/prepare/status"): {
            "body": {"running": False, "completed": True, "current_step": "done"}
        },
        ("GET", "/api/v1/bot/status"): {"body": {"status": "stopped"}},
        ("POST", "/api/v1/bot/start"): {
            "body": {"success": True, "message": "started", "status": "running"}
        },
    }
    patch_httpx_client["transport"] = _route_transport(routes)

    result = health_check.run_health_check(base_url="http://test")

    assert result.ok is True
    assert result.auth_required is False
    assert "bot_started" in result.actions_taken


def test_health_check_reports_unreachable_api(patch_httpx_client):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    patch_httpx_client["transport"] = httpx.MockTransport(handler)
    result = health_check.run_health_check(base_url="http://test")
    assert result.ok is False
    assert "api_unreachable" in result.issues


# =============================================================================
# live_monitor
# =============================================================================


def test_monitor_healthy_when_bot_running_and_no_alerts(patch_httpx_client):
    now = datetime(2026, 4, 9, 12, 0, tzinfo=timezone.utc)
    routes = {
        ("GET", "/api/v1/bot/status"): {
            "body": {
                "status": "running",
                "last_cycle": (now - timedelta(minutes=2)).isoformat(),
                "cycle_count": 17,
            }
        },
        ("GET", "/api/v1/bot/risk"): {
            "body": {
                "circuit_breaker_triggered": False,
                "daily_pnl": 0.0,
                "daily_loss_limit": 3000.0,
            }
        },
    }
    patch_httpx_client["transport"] = _route_transport(routes)

    result = live_monitor.run_monitor(base_url="http://test", now=now)

    assert result.healthy is True
    assert result.alerts == []


def test_monitor_flags_bot_not_running(patch_httpx_client):
    routes = {
        ("GET", "/api/v1/bot/status"): {"body": {"status": "stopped"}},
    }
    patch_httpx_client["transport"] = _route_transport(routes)

    result = live_monitor.run_monitor(base_url="http://test")
    assert result.healthy is False
    assert "bot_not_running" in result.alerts


def test_monitor_flags_circuit_breaker(patch_httpx_client):
    now = datetime(2026, 4, 9, 12, 0, tzinfo=timezone.utc)
    routes = {
        ("GET", "/api/v1/bot/status"): {
            "body": {
                "status": "running",
                "last_cycle": now.isoformat(),
            }
        },
        ("GET", "/api/v1/bot/risk"): {
            "body": {
                "circuit_breaker_triggered": True,
                "daily_pnl": -3500.0,
                "daily_loss_limit": 3000.0,
            }
        },
    }
    patch_httpx_client["transport"] = _route_transport(routes)

    result = live_monitor.run_monitor(base_url="http://test", now=now)
    assert result.healthy is False
    assert "circuit_breaker_active" in result.alerts


def test_monitor_flags_stale_cycles(patch_httpx_client):
    now = datetime(2026, 4, 9, 12, 0, tzinfo=timezone.utc)
    last = now - timedelta(minutes=30)
    routes = {
        ("GET", "/api/v1/bot/status"): {
            "body": {
                "status": "running",
                "last_cycle": last.isoformat(),
            }
        },
        ("GET", "/api/v1/bot/risk"): {
            "body": {
                "circuit_breaker_triggered": False,
                "daily_pnl": 0.0,
                "daily_loss_limit": 3000.0,
            }
        },
    }
    patch_httpx_client["transport"] = _route_transport(routes)

    result = live_monitor.run_monitor(base_url="http://test", now=now)
    assert result.healthy is False
    assert "stale_cycles" in result.alerts
