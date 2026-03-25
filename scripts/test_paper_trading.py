#!/usr/bin/env python3
"""
Test paper trading system.

Usage:
    python scripts/test_paper_trading.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.broker.paper import PaperBroker
from backend.broker.base import Order, OrderSide, OrderType, ProductType
from backend.broker.session import load_access_token
from backend.config import settings
from backend.ml.inference import PredictionService, Prediction
from backend.services.feature_engine import FeatureVector
from backend.services.risk_guardian import RiskGuardian
from backend.services.position_manager import PositionManager
from backend.services.stock_ranker import StockRanker
from backend.services.trade_executor import TradeExecutor
from datetime import datetime


def test_paper_trading():
    print("=" * 60)
    print("PAPER TRADING SYSTEM TEST")
    print("=" * 60)

    # Initialize paper broker
    print("\n1. Initializing Paper Broker...")
    access_token = load_access_token()

    broker = PaperBroker(
        initial_capital=100000,
        kite_api_key=settings.kite_api_key,
        kite_api_secret=settings.kite_api_secret,
    )

    if access_token:
        broker.authenticate(access_token=access_token)
        print(f"   Connected to Zerodha for real market data ✓")
    else:
        broker.authenticate()
        print(f"   Running with mock prices (no Zerodha connection)")

    margin = broker.get_margin()
    print(f"   Initial capital: ₹{margin.available_cash:,.2f}")

    # Test getting market data
    print("\n2. Testing Market Data...")
    test_symbols = ["RELIANCE", "INFY", "TCS"]
    prices = broker.get_ltp(test_symbols)
    for symbol, price in prices.items():
        print(f"   {symbol}: ₹{price:,.2f}")

    # Test order placement
    print("\n3. Testing Order Placement...")
    symbol = "RELIANCE"
    quantity = 10
    price = prices.get(symbol, 1000)

    order = Order(
        symbol=symbol,
        quantity=quantity,
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        product=ProductType.MIS,
    )

    response = broker.place_order(order)
    print(f"   Order ID: {response.order_id}")
    print(f"   Status: {response.status.value}")
    print(f"   Executed price: ₹{response.executed_price:,.2f}")

    # Check positions
    print("\n4. Checking Positions...")
    positions = broker.get_positions()
    for pos in positions:
        print(f"   {pos.symbol}: {pos.quantity} @ ₹{pos.avg_price:,.2f}")
        print(f"   Current: ₹{pos.current_price:,.2f}, P&L: ₹{pos.pnl:,.2f}")

    # Test risk guardian
    print("\n5. Testing Risk Guardian...")
    risk = RiskGuardian(broker)

    # Create a mock prediction
    mock_prediction = Prediction(
        symbol=symbol,
        timestamp=datetime.now(),
        direction="UP",
        probability=0.65,
        confidence=0.3,
        top_features=[("daily_trend", 0.15)],
    )

    check = risk.validate_entry(symbol, mock_prediction, margin.available_cash)
    print(f"   Risk check passed: {check.passed}")
    print(f"   Max allocation: ₹{check.max_allocation:,.2f}")
    print(f"   Checks: {check.checks_performed}")

    # Test position manager
    print("\n6. Testing Position Manager...")
    pm = PositionManager(broker)
    pm.sync_with_broker()
    print(f"   Open positions: {len(pm.get_all_positions())}")
    summary = pm.get_summary()
    print(f"   Total invested: ₹{summary['total_invested']:,.2f}")

    # Test selling
    print("\n7. Testing Sell Order...")
    sell_order = Order(
        symbol=symbol,
        quantity=quantity,
        side=OrderSide.SELL,
        order_type=OrderType.MARKET,
        product=ProductType.MIS,
    )

    sell_response = broker.place_order(sell_order)
    print(f"   Sell Order ID: {sell_response.order_id}")
    print(f"   Status: {sell_response.status.value}")
    print(f"   P&L: {sell_response.message}")

    # Final summary
    print("\n" + "=" * 60)
    print("FINAL SUMMARY")
    print("=" * 60)
    summary = broker.get_summary()
    print(f"   Initial capital: ₹{summary['initial_capital']:,.2f}")
    print(f"   Current capital: ₹{summary['current_capital']:,.2f}")
    print(f"   Realized P&L: ₹{summary['realized_pnl']:,.2f}")
    print(f"   Unrealized P&L: ₹{summary['unrealized_pnl']:,.2f}")
    print(f"   Total P&L: ₹{summary['total_pnl']:,.2f}")
    print(f"   Total trades: {summary['total_trades']}")
    print(f"   Win rate: {summary['win_rate']:.1f}%")

    print("\n✅ All tests passed!")


def test_ml_inference():
    print("\n" + "=" * 60)
    print("ML INFERENCE TEST")
    print("=" * 60)

    try:
        print("\n1. Loading prediction service...")
        service = PredictionService()
        print("   Model loaded ✓")

        print("\n2. Testing prediction with mock features...")
        # Create a mock feature vector
        features = FeatureVector(
            symbol="RELIANCE",
            timestamp=datetime.now(),
            rsi=45.0,
            macd=0.001,
            macd_signal=0.0005,
            macd_histogram=0.0005,
            ema_ratio=1.01,
            volatility=0.015,
            volume_spike=1.2,
            momentum=0.005,
            bollinger_position=0.3,
            adx=25.0,
            atr=0.012,
            volatility_regime=0.8,
            price_acceleration=0.002,
            range_position=0.6,
            hourly_trend=1,
            daily_trend=1,
            daily_range_position=0.55,
        )

        prediction = service.predict(features)
        print(f"   Symbol: {prediction.symbol}")
        print(f"   Direction: {prediction.direction}")
        print(f"   Probability: {prediction.probability:.3f}")
        print(f"   Confidence: {prediction.confidence:.3f}")
        print(f"   Should trade: {prediction.should_trade}")
        print(f"   Top features: {prediction.top_features[:3]}")

        print("\n✅ ML inference test passed!")

    except FileNotFoundError as e:
        print(f"\n⚠️  Model not found. Run 'python scripts/train.py' first.")
        print(f"   Error: {e}")


if __name__ == "__main__":
    test_paper_trading()
    test_ml_inference()
