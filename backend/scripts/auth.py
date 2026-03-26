#!/usr/bin/env python3
"""
One-click Zerodha authentication.

Usage:
    python scripts/auth.py

What happens:
1. Opens Zerodha login in your browser
2. You login with your Zerodha credentials + TOTP
3. Zerodha redirects to localhost:5000
4. Script catches the request_token automatically
5. Exchanges it for access_token
6. Saves access_token to .kite_session file
7. You're authenticated for the day!
"""

import json
import sys
import webbrowser
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from backend.config import settings

SESSION_FILE = Path(__file__).parent.parent.parent / ".kite_session"


class CallbackHandler(BaseHTTPRequestHandler):
    """Handles the OAuth callback from Zerodha."""

    access_token = None
    user_data = None

    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        if "request_token" in params:
            request_token = params["request_token"][0]
            print(f"\n✅ Got request_token: {request_token[:20]}...")

            # Exchange for access_token
            try:
                from kiteconnect import KiteConnect

                kite = KiteConnect(api_key=settings.kite_api_key)
                data = kite.generate_session(
                    request_token=request_token,
                    api_secret=settings.kite_api_secret
                )

                CallbackHandler.access_token = data["access_token"]
                CallbackHandler.user_data = data

                # Success response
                self.send_response(200)
                self.send_header("Content-type", "text/html")
                self.end_headers()

                html = f"""
                <html>
                <head>
                    <title>Authentication Successful</title>
                    <style>
                        body {{ font-family: -apple-system, sans-serif; text-align: center; padding: 50px; }}
                        .success {{ color: #22c55e; font-size: 48px; }}
                        .info {{ color: #666; margin: 20px 0; }}
                    </style>
                </head>
                <body>
                    <div class="success">✓</div>
                    <h1>Authentication Successful!</h1>
                    <p class="info">Welcome, {data.get('user_name', 'Trader')}</p>
                    <p class="info">User ID: {data.get('user_id')}</p>
                    <p class="info">You can close this tab and return to the terminal.</p>
                </body>
                </html>
                """
                self.wfile.write(html.encode())

            except Exception as e:
                print(f"\n❌ Token exchange failed: {e}")
                print(f"   API Key: {settings.kite_api_key[:10]}...")
                print(f"   Request Token: {request_token[:20]}...")

                self.send_response(500)
                self.send_header("Content-type", "text/html")
                self.end_headers()
                error_html = f"""
                <html>
                <head><title>Authentication Failed</title></head>
                <body style="font-family: sans-serif; text-align: center; padding: 50px;">
                    <h1 style="color: red;">Authentication Failed</h1>
                    <p>Error: {e}</p>
                    <p>Please try again. Check terminal for details.</p>
                </body>
                </html>
                """
                self.wfile.write(error_html.encode())
        else:
            self.send_response(400)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(b"<h1>Missing request_token</h1>")

    def log_message(self, format, *args):
        pass  # Suppress default logging


def save_session(access_token: str, user_data: dict):
    """Save session to file."""
    session = {
        "access_token": access_token,
        "user_id": user_data.get("user_id"),
        "user_name": user_data.get("user_name"),
        "email": user_data.get("email"),
        "created_at": datetime.now().isoformat(),
        "expires_at": "06:00 AM next day"
    }

    SESSION_FILE.write_text(json.dumps(session, indent=2))
    print(f"💾 Session saved to {SESSION_FILE.name}")


def load_session() -> dict | None:
    """Load existing session if valid."""
    if not SESSION_FILE.exists():
        return None

    try:
        session = json.loads(SESSION_FILE.read_text())
        created = datetime.fromisoformat(session["created_at"])

        # Check if session is from today and before 6 AM cutoff
        now = datetime.now()

        # Session expires at 6 AM
        if created.date() == now.date() and now.hour < 6:
            return session
        if created.date() == now.date() and created.hour >= 6:
            return session
        if (now - created).total_seconds() < 12 * 3600:  # Less than 12 hours old
            return session

        return None
    except:
        return None


def verify_session(access_token: str) -> bool:
    """Verify if access_token is still valid."""
    try:
        from kiteconnect import KiteConnect

        kite = KiteConnect(api_key=settings.kite_api_key)
        kite.set_access_token(access_token)
        kite.profile()  # Will raise if token is invalid
        return True
    except:
        return False


def main():
    print("=" * 50)
    print("ZERODHA KITE AUTHENTICATION")
    print("=" * 50)

    # Check for existing valid session
    existing = load_session()
    if existing:
        print(f"\n📋 Found existing session for {existing.get('user_name', 'Unknown')}")
        print(f"   Created: {existing['created_at']}")

        if verify_session(existing["access_token"]):
            print("   Status: ✅ Valid")
            print(f"\n🔑 Access Token: {existing['access_token'][:50]}...")
            print("\nYou're already authenticated! No action needed.")
            return
        else:
            print("   Status: ❌ Expired")
            print("\nNeed to re-authenticate...")

    # Start local server
    PORT = 5000
    server = HTTPServer(("127.0.0.1", PORT), CallbackHandler)

    # Build login URL
    login_url = f"https://kite.zerodha.com/connect/login?v=3&api_key={settings.kite_api_key}"

    print(f"\n1️⃣  Opening browser for Zerodha login...")
    print(f"   URL: {login_url[:60]}...")
    print(f"\n2️⃣  Waiting for callback on http://127.0.0.1:{PORT}")
    print("\n⏳ Please login in the browser window...")
    print("   (Press Ctrl+C to cancel)\n")

    # Open browser
    webbrowser.open(login_url)

    # Wait for single callback
    try:
        server.handle_request()  # Handles one request then continues

        if CallbackHandler.access_token:
            print(f"\n✅ Authentication successful!")
            print(f"   User: {CallbackHandler.user_data.get('user_name')}")
            print(f"   ID: {CallbackHandler.user_data.get('user_id')}")

            # Save session
            save_session(CallbackHandler.access_token, CallbackHandler.user_data)

            print(f"\n🔑 Access Token (valid until 6 AM tomorrow):")
            print(f"   {CallbackHandler.access_token}")

            print("\n" + "=" * 50)
            print("You're all set! The trading bot can now use this token.")
            print("=" * 50)
        else:
            print("\n❌ Authentication failed - no token received")

    except KeyboardInterrupt:
        print("\n\n❌ Cancelled by user")
        sys.exit(1)
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
