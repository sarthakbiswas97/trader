#!/usr/bin/env python3
"""Test Zerodha Kite Connect authentication."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from dotenv import load_dotenv
load_dotenv()

from backend.config import settings

print(f"API Key: {settings.kite_api_key}")
print(f"API Secret: {settings.kite_api_secret[:8]}...")

from kiteconnect import KiteConnect

kite = KiteConnect(api_key=settings.kite_api_key)

print(f"\n1. Login URL:")
print(f"   {kite.login_url()}")

print("\n2. After login, you'll be redirected to your callback URL with request_token")
print("   Example: http://127.0.0.1:5000/callback?request_token=xxx&action=login&status=success")

request_token = input("\nEnter request_token (or press Enter to skip): ").strip()

if request_token:
    try:
        data = kite.generate_session(
            request_token=request_token,
            api_secret=settings.kite_api_secret
        )
        print(f"\n✅ Session created!")
        print(f"Access Token: {data['access_token']}")
        print(f"User ID: {data['user_id']}")
        print(f"Email: {data.get('email', 'N/A')}")

        kite.set_access_token(data['access_token'])

        print("\n--- Testing API ---")

        profile = kite.profile()
        print(f"✅ Profile: {profile.get('user_name')}")

        margins = kite.margins(segment="equity")
        print(f"✅ Available Cash: ₹{margins.get('available', {}).get('cash', 0):,.2f}")

        ltp = kite.ltp(["NSE:RELIANCE"])
        print(f"✅ RELIANCE LTP: ₹{ltp['NSE:RELIANCE']['last_price']:,.2f}")

        print(f"\n🔑 Save this access token for today's session:")
        print(f"   {data['access_token']}")

    except Exception as e:
        print(f"\n❌ Error: {e}")
else:
    print("\nSkipped authentication test.")
