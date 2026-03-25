"""
Session management for Kite Connect.
Handles loading/saving access tokens.
"""

import json
from datetime import datetime
from pathlib import Path

SESSION_FILE = Path(__file__).parent.parent.parent / ".kite_session"


def load_access_token() -> str | None:
    """
    Load access token from saved session.
    Returns None if no valid session exists.
    """
    if not SESSION_FILE.exists():
        return None

    try:
        session = json.loads(SESSION_FILE.read_text())
        access_token = session.get("access_token")

        if not access_token:
            return None

        # Basic staleness check (session created today or recently)
        created = datetime.fromisoformat(session["created_at"])
        now = datetime.now()

        # Expired if created before 6 AM yesterday
        hours_old = (now - created).total_seconds() / 3600
        if hours_old > 24:
            return None

        return access_token

    except Exception:
        return None


def save_access_token(access_token: str, user_data: dict = None):
    """Save access token to session file."""
    session = {
        "access_token": access_token,
        "created_at": datetime.now().isoformat(),
    }

    if user_data:
        session.update({
            "user_id": user_data.get("user_id"),
            "user_name": user_data.get("user_name"),
            "email": user_data.get("email"),
        })

    SESSION_FILE.write_text(json.dumps(session, indent=2))


def clear_session():
    """Clear saved session."""
    if SESSION_FILE.exists():
        SESSION_FILE.unlink()


def load_session() -> dict | None:
    """
    Load full session data.
    Returns None if no session exists.
    """
    if not SESSION_FILE.exists():
        return None

    try:
        return json.loads(SESSION_FILE.read_text())
    except Exception:
        return None
