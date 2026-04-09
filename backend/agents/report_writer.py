"""
Shared report writer for ops agents.

Writes structured markdown reports to backend/data/ops_reports/{category}/{date}.md.
Idempotent: re-running the same agent overwrites the day's report.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

REPORTS_ROOT = Path(__file__).parent.parent / "data" / "ops_reports"


def report_path(category: str, day: date) -> Path:
    """Return the file path for a report (does not create the file)."""
    return REPORTS_ROOT / category / f"{day.isoformat()}.md"


def write_report(category: str, day: date, content: str) -> Path:
    """
    Write a markdown report for the given category and date.

    Args:
        category: Subdirectory name (e.g., "morning", "post_market", "monitor").
        day: The date the report is for.
        content: Full markdown body.

    Returns:
        Absolute path of the written file.
    """
    path = report_path(category, day)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def write_alert(category: str, name: str, day: date, content: str) -> Path:
    """
    Write a named alert file (e.g., AUTH_NEEDED) inside a category directory.

    Args:
        category: Subdirectory name.
        name: Alert filename prefix (e.g., "AUTH_NEEDED").
        day: The date the alert is for.
        content: Markdown body.

    Returns:
        Absolute path of the written file.
    """
    path = REPORTS_ROOT / category / f"{name}_{day.isoformat()}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path
