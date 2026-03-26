#!/usr/bin/env python3
"""
Run the trading bot.

Usage:
    python scripts/run_bot.py              # Paper trading mode
    python scripts/run_bot.py --live       # Live trading (use with caution!)
    python scripts/run_bot.py --symbols RELIANCE TCS INFY
"""

import argparse
import asyncio
import signal
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from backend.broker.paper import PaperBroker
from backend.broker.session import load_access_token
from backend.config import settings
from backend.services.execution_engine import create_engine
from backend.services.historical_data import HistoricalDataService
from backend.services.feature_engine import FeatureEngine
from backend.ml.inference import PredictionService
from backend.services.stock_ranker import StockRanker
from datetime import datetime, timedelta
from backend.utils.time_utils import now_ist


async def run_test_cycle(engine, broker):
    """Run a single test cycle bypassing market hours check."""
    print("\n" + "-" * 60)
    print("TEST CYCLE - Fetching data and generating predictions...")
    print("-" * 60 + "\n")

    # Use a smaller set of symbols for testing
    test_symbols = engine.symbols[:10]  # First 10 symbols
    print(f"Testing with {len(test_symbols)} symbols: {', '.join(test_symbols[:5])}...")

    # Fetch features and generate predictions
    predictions = {}
    data_service = HistoricalDataService()
    data_service.set_kite(broker._kite)
    feature_engine = FeatureEngine(data_service=data_service)
    prediction_service = engine.prediction_service

    print("\nFetching candles and computing features...")
    for symbol in test_symbols:
        try:
            # Fetch recent 5-min candles
            end_date = now_ist()
            start_date = end_date - timedelta(days=5)  # 5 days of data

            df_5m = data_service.fetch_candles(
                symbol=symbol,
                interval="5m",
                start_date=start_date,
                end_date=end_date,
            )

            if df_5m.empty or len(df_5m) < 100:
                print(f"  {symbol}: Insufficient data ({len(df_5m)} rows)")
                continue

            # Compute features
            features = feature_engine.get_latest_features(symbol, df_5m)
            if features is None:
                print(f"  {symbol}: Failed to compute features")
                continue

            # Generate prediction
            pred = prediction_service.predict(features)
            predictions[symbol] = pred

            direction_icon = "🟢" if pred.direction == "UP" else "🔴"
            print(f"  {symbol}: {direction_icon} {pred.direction} "
                  f"(prob={pred.probability:.1%}, conf={pred.confidence:.1%})")

        except Exception as e:
            print(f"  {symbol}: Error - {e}")

    # Show summary
    print("\n" + "-" * 60)
    print("PREDICTION SUMMARY")
    print("-" * 60)

    up_signals = [(s, p) for s, p in predictions.items() if p.direction == "UP"]
    down_signals = [(s, p) for s, p in predictions.items() if p.direction == "DOWN"]

    print(f"\nTotal predictions: {len(predictions)}")
    print(f"  UP signals: {len(up_signals)}")
    print(f"  DOWN signals: {len(down_signals)}")

    # Rank UP signals
    if up_signals:
        print("\nTop UP signals (would BUY):")
        ranker = StockRanker(min_confidence=0.05, min_probability=0.52, max_stocks=5)
        ranked = ranker.rank(predictions)
        for stock in ranked:
            print(f"  {stock.rank}. {stock.symbol}: "
                  f"prob={stock.prediction.probability:.1%}, "
                  f"conf={stock.prediction.confidence:.1%}, "
                  f"score={stock.score:.1f}")

    # Simulate a paper trade
    if ranked:
        print("\n" + "-" * 60)
        print("SIMULATED PAPER TRADE")
        print("-" * 60)

        best = ranked[0]
        ltp = broker.get_ltp([best.symbol])
        price = ltp.get(best.symbol, 0)

        # Calculate position size (5% of capital)
        margin = broker.get_margin()
        max_allocation = margin.available_cash * 0.05
        quantity = int(max_allocation / price) if price > 0 else 0

        if quantity > 0:
            from backend.broker.base import Order, OrderSide, OrderType, ProductType
            order = Order(
                symbol=best.symbol,
                quantity=quantity,
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                product=ProductType.MIS,
            )

            print(f"\nPlacing paper BUY order:")
            print(f"  Symbol: {best.symbol}")
            print(f"  Quantity: {quantity}")
            print(f"  Price: ₹{price:,.2f}")
            print(f"  Value: ₹{quantity * price:,.2f}")
            print(f"  Reason: ML Signal (prob={best.prediction.probability:.1%})")

            response = broker.place_order(order)
            print(f"\n  Order Status: {response.status.value}")
            print(f"  Order ID: {response.order_id}")

            # Check positions
            print("\nCurrent Positions:")
            for pos in broker.get_positions():
                print(f"  {pos.symbol}: {pos.quantity} @ ₹{pos.avg_price:,.2f} "
                      f"(P&L: ₹{pos.pnl:,.2f})")

    # Final summary
    print("\n" + "=" * 60)
    print("TEST CYCLE COMPLETE")
    print("=" * 60)
    summary = broker.get_summary()
    print(f"\nCapital: ₹{summary['current_capital']:,.2f}")
    print(f"Positions: {summary['open_positions']}")
    print(f"Unrealized P&L: ₹{summary['unrealized_pnl']:,.2f}")


def main():
    parser = argparse.ArgumentParser(description="Run the trading bot")
    parser.add_argument(
        "--live",
        action="store_true",
        help="Enable live trading (default: paper trading)",
    )
    parser.add_argument(
        "--symbols",
        nargs="+",
        help="Specific symbols to trade",
    )
    parser.add_argument(
        "--capital",
        type=float,
        default=100000,
        help="Initial capital for paper trading (default: 100000)",
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="Test mode - run one cycle immediately (ignores market hours)",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("AUTONOMOUS TRADING BOT")
    print("=" * 60)

    # Determine trading mode
    mode = "live" if args.live else "paper"
    print(f"\nMode: {mode.upper()}")

    if mode == "live":
        print("\n⚠️  WARNING: Live trading is enabled!")
        print("    Real money will be used for trades.")
        confirm = input("    Type 'YES' to confirm: ")
        if confirm != "YES":
            print("Aborted.")
            sys.exit(1)

    # Load access token
    access_token = load_access_token()
    if not access_token:
        print("\n❌ No access token found.")
        print("   Run 'python scripts/auth.py' first to authenticate.")
        sys.exit(1)

    print(f"   Access token: ...{access_token[-8:]}")

    # Create broker
    if mode == "paper":
        broker = PaperBroker(
            initial_capital=args.capital,
            kite_api_key=settings.kite_api_key,
            kite_api_secret=settings.kite_api_secret,
        )
        broker.authenticate(access_token=access_token)
        print(f"   Paper capital: ₹{args.capital:,.0f}")
    else:
        from backend.broker.zerodha import ZerodhaBroker
        broker = ZerodhaBroker(
            api_key=settings.kite_api_key,
            api_secret=settings.kite_api_secret,
        )
        broker.authenticate(access_token=access_token)

    # Get profile
    profile = broker.get_profile()
    print(f"   Profile: {profile}")

    # Determine symbols
    symbols = args.symbols
    if not symbols:
        # Default to a subset of NIFTY 50 for testing
        symbols = [
            "RELIANCE", "INFY", "TCS", "HDFCBANK", "ICICIBANK",
            "SBIN", "BHARTIARTL", "ITC", "KOTAKBANK", "LT",
            "HINDUNILVR", "AXISBANK", "BAJFINANCE", "ASIANPAINT", "MARUTI",
        ]

    print(f"\nSymbols: {len(symbols)}")
    for s in symbols[:5]:
        print(f"   - {s}")
    if len(symbols) > 5:
        print(f"   ... and {len(symbols) - 5} more")

    # Create engine
    print("\n" + "-" * 60)
    print("Initializing trading engine...")

    engine = create_engine(broker=broker, symbols=symbols)

    print("   Feature engine: ✓")
    print("   Prediction service: ✓")
    print("   Risk guardian: ✓")
    print("   Trade executor: ✓")

    # Setup signal handlers
    def handle_shutdown(sig, frame):
        print("\n\nShutdown signal received...")
        engine.stop()

        # Square off all positions on shutdown
        if input("Square off all positions? (y/n): ").lower() == "y":
            results = engine.square_off_all()
            print(f"Squared off {len(results)} positions")

        sys.exit(0)

    signal.signal(signal.SIGINT, handle_shutdown)
    signal.signal(signal.SIGTERM, handle_shutdown)

    # Run the engine
    print("\n" + "=" * 60)
    if args.test:
        print("Running TEST MODE - single cycle")
    else:
        print("Starting execution loop...")
    print("=" * 60)
    print("\nPress Ctrl+C to stop\n")

    try:
        if args.test:
            # Run single test cycle
            asyncio.run(run_test_cycle(engine, broker))
        else:
            asyncio.run(engine.run())
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
    finally:
        # Print final summary
        status = engine.get_status()
        print("\n" + "=" * 60)
        print("FINAL STATUS")
        print("=" * 60)
        print(f"\nCycles completed: {status['cycle_count']}")
        print(f"\nPositions: {status['positions']['open_positions']}")
        print(f"Unrealized P&L: ₹{status['positions']['unrealized_pnl']:,.2f}")
        print(f"\nRisk status:")
        print(f"   Trades today: {status['risk']['trades_today']}")
        print(f"   Daily P&L: ₹{status['risk']['daily_pnl']:,.2f}")
        print(f"   Circuit breaker: {'TRIGGERED' if status['risk']['circuit_breaker_triggered'] else 'OK'}")

        if mode == "paper":
            summary = broker.get_summary()
            print(f"\nPaper Trading Summary:")
            print(f"   Initial capital: ₹{summary['initial_capital']:,.2f}")
            print(f"   Current capital: ₹{summary['current_capital']:,.2f}")
            print(f"   Total P&L: ₹{summary['total_pnl']:,.2f}")
            print(f"   Win rate: {summary['win_rate']:.1f}%")


if __name__ == "__main__":
    main()
