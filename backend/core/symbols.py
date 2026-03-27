"""
NIFTY 50 stock universe — single source of truth.

All modules import from here. No duplicate symbol lists elsewhere.
"""

NIFTY_50 = [
    "RELIANCE",
    "TCS",
    "HDFCBANK",
    "INFY",
    "ICICIBANK",
    "HINDUNILVR",
    "SBIN",
    "BHARTIARTL",
    "ITC",
    "KOTAKBANK",
    "LT",
    "AXISBANK",
    "BAJFINANCE",
    "ASIANPAINT",
    "MARUTI",
    "TITAN",
    "SUNPHARMA",
    "ULTRACEMCO",
    "NESTLEIND",
    "WIPRO",
    "HCLTECH",
    "POWERGRID",
    "NTPC",
    "TECHM",
    "M&M",
    "BAJAJFINSV",
    "ONGC",
    "ADANIENT",
    "ADANIPORTS",
    "COALINDIA",
    "JSWSTEEL",
    "TATASTEEL",
    "GRASIM",
    "INDUSINDBK",
    "BRITANNIA",
    "CIPLA",
    "DRREDDY",
    "DIVISLAB",
    "EICHERMOT",
    "HEROMOTOCO",
    "BPCL",
    "APOLLOHOSP",
    "SBILIFE",
    "TATACONSUM",
    "HINDALCO",
    "BAJAJ-AUTO",
    "SHRIRAMFIN",
    "TRENT",
]

# Count for validation
assert len(NIFTY_50) == 48, f"Expected 48 symbols, got {len(NIFTY_50)}"
