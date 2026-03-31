"""
Run regime-aware backtest comparison.

Usage:
    python -m backend.scripts.backtest_regime
    python -m backend.scripts.backtest_regime --strategy momentum
    python -m backend.scripts.backtest_regime --compare
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from backend.strategies.midcap_momentum.backtest import (
    run_regime_backtest,
    compare_strategies,
)


def main():
    parser = argparse.ArgumentParser(description="Regime-aware backtest")
    parser.add_argument(
        "--strategy",
        choices=["reversal", "momentum"],
        default="reversal",
        help="Strategy to test",
    )
    parser.add_argument(
        "--universe",
        choices=["nifty50", "midcap", "nifty100"],
        default="nifty50",
        help="Stock universe",
    )
    parser.add_argument("--holding", type=int, default=5, help="Holding period days")
    parser.add_argument("--top-n", type=int, default=10, help="Number of stocks to pick")
    parser.add_argument("--compare", action="store_true", help="Compare momentum vs reversal")
    args = parser.parse_args()

    if args.compare:
        compare_strategies(holding_days=args.holding, top_n=args.top_n)
    else:
        run_regime_backtest(
            strategy=args.strategy,
            universe=args.universe,
            holding_days=args.holding,
            top_n=args.top_n,
        )


if __name__ == "__main__":
    main()
