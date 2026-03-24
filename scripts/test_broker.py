#!/usr/bin/env python3
"""
Test script to verify broker connection and basic functionality.
Run this to ensure everything is set up correctly.

Usage:
    python scripts/test_broker.py
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from backend.broker import get_broker, Order, OrderSide, OrderType
from backend.config import settings
from backend.core.logger import setup_logging, get_logger

# Setup logging
setup_logging()
logger = get_logger(__name__)


def test_authentication():
    """Test broker authentication."""
    print("\n" + "=" * 60)
    print("TEST: Authentication")
    print("=" * 60)

    broker = get_broker()
    print(f"Trading Mode: {settings.trading_mode}")
    print(f"Broker Type: {type(broker).__name__}")

    try:
        broker.authenticate()
        print("✅ Authentication successful!")
        return broker
    except Exception as e:
        print(f"❌ Authentication failed: {e}")
        return None


def test_get_profile(broker):
    """Test getting user profile."""
    print("\n" + "=" * 60)
    print("TEST: Get Profile")
    print("=" * 60)

    try:
        profile = broker.get_profile()
        print("✅ Profile retrieved:")
        for key, value in profile.items():
            print(f"   {key}: {value}")
    except Exception as e:
        print(f"❌ Failed to get profile: {e}")


def test_get_margin(broker):
    """Test getting margin info."""
    print("\n" + "=" * 60)
    print("TEST: Get Margin")
    print("=" * 60)

    try:
        margin = broker.get_margin()
        print("✅ Margin info retrieved:")
        print(f"   Available Cash: ₹{margin.available_cash:,.2f}")
        print(f"   Used Margin: ₹{margin.used_margin:,.2f}")
        print(f"   Total Balance: ₹{margin.total_balance:,.2f}")
    except Exception as e:
        print(f"❌ Failed to get margin: {e}")


def test_get_ltp(broker):
    """Test getting LTP for stocks."""
    print("\n" + "=" * 60)
    print("TEST: Get LTP")
    print("=" * 60)

    symbols = ["RELIANCE", "TCS", "INFY"]

    try:
        ltp = broker.get_ltp(symbols)
        print("✅ LTP retrieved:")
        for symbol, price in ltp.items():
            print(f"   {symbol}: ₹{price:,.2f}")
    except Exception as e:
        print(f"❌ Failed to get LTP: {e}")


def test_get_positions(broker):
    """Test getting positions."""
    print("\n" + "=" * 60)
    print("TEST: Get Positions")
    print("=" * 60)

    try:
        positions = broker.get_positions()
        print(f"✅ Positions retrieved: {len(positions)} position(s)")
        for pos in positions:
            print(f"   {pos.symbol}: {pos.quantity} @ ₹{pos.avg_price:.2f}")
            print(f"      Current: ₹{pos.current_price:.2f}, P&L: ₹{pos.pnl:.2f} ({pos.pnl_percent:.2f}%)")
    except Exception as e:
        print(f"❌ Failed to get positions: {e}")


def test_paper_trading(broker):
    """Test paper trading (only if in paper mode)."""
    if settings.trading_mode != "paper":
        print("\n⚠️  Skipping paper trading test (not in paper mode)")
        return

    print("\n" + "=" * 60)
    print("TEST: Paper Trading Simulation")
    print("=" * 60)

    try:
        # Get initial state
        initial_margin = broker.get_margin()
        print(f"Initial capital: ₹{initial_margin.available_cash:,.2f}")

        # Place a buy order
        buy_order = Order(
            symbol="RELIANCE",
            quantity=5,
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
        )

        print(f"\nPlacing BUY order: {buy_order.quantity} x {buy_order.symbol}")
        buy_response = broker.place_order(buy_order)
        print(f"   Order ID: {buy_response.order_id}")
        print(f"   Status: {buy_response.status.value}")
        print(f"   Price: ₹{buy_response.executed_price:,.2f}" if buy_response.executed_price else "")

        # Check positions
        positions = broker.get_positions()
        if positions:
            pos = positions[0]
            print(f"\nPosition opened: {pos.symbol}")
            print(f"   Quantity: {pos.quantity}")
            print(f"   Avg Price: ₹{pos.avg_price:,.2f}")

        # Check margin after buy
        margin_after_buy = broker.get_margin()
        print(f"\nCapital after buy: ₹{margin_after_buy.available_cash:,.2f}")

        # Place a sell order
        sell_order = Order(
            symbol="RELIANCE",
            quantity=5,
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
        )

        print(f"\nPlacing SELL order: {sell_order.quantity} x {sell_order.symbol}")
        sell_response = broker.place_order(sell_order)
        print(f"   Order ID: {sell_response.order_id}")
        print(f"   Status: {sell_response.status.value}")
        print(f"   Message: {sell_response.message}")

        # Check final state
        final_margin = broker.get_margin()
        print(f"\nFinal capital: ₹{final_margin.available_cash:,.2f}")

        # Get summary
        if hasattr(broker, 'get_summary'):
            summary = broker.get_summary()
            print("\nPaper Trading Summary:")
            print(f"   Total Trades: {summary['total_trades']}")
            print(f"   Realized P&L: ₹{summary['realized_pnl']:,.2f}")
            print(f"   Win Rate: {summary['win_rate']:.1f}%")

        print("\n✅ Paper trading simulation complete!")

    except Exception as e:
        print(f"❌ Paper trading test failed: {e}")
        import traceback
        traceback.print_exc()


def main():
    """Run all tests."""
    print("\n" + "=" * 60)
    print("AUTONOMOUS TRADING AGENT - BROKER TEST")
    print("=" * 60)
    print(f"Environment: {settings.environment}")
    print(f"Trading Mode: {settings.trading_mode}")
    print(f"Paper Capital: ₹{settings.paper_trading_capital:,.2f}")

    # Run tests
    broker = test_authentication()

    if broker is None:
        print("\n❌ Cannot continue without authentication")
        sys.exit(1)

    test_get_profile(broker)
    test_get_margin(broker)
    test_get_ltp(broker)
    test_get_positions(broker)
    test_paper_trading(broker)

    print("\n" + "=" * 60)
    print("ALL TESTS COMPLETE")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
