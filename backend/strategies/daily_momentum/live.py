"""
Daily Reversal — Pseudo Trading Engine.

Runs the validated reversal strategy on live market data
without placing real orders. Simulates execution with
realistic slippage and costs.

Usage:
    from backend.strategies.daily_momentum.live import ReversalEngine
    engine = ReversalEngine(kite)
    engine.run_daily()  # Call each morning after 9:30 AM
"""

import json
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from backend.core.logger import get_logger
from backend.core.symbols import NIFTY_100

logger = get_logger(__name__)

_DATA_DIR = Path(__file__).parent.parent.parent / "data"
_LOG_DIR = _DATA_DIR / "pseudo_trading"
_LOG_DIR.mkdir(parents=True, exist_ok=True)

PORTFOLIO_FILE = _LOG_DIR / "portfolio.json"
TRADE_LOG_FILE = _LOG_DIR / "trades.json"
DAILY_LOG_FILE = _LOG_DIR / "daily_log.json"


class ReversalEngine:
    """
    Pseudo trading engine for daily reversal strategy.

    Each morning:
      1. Fetch latest prices for all stocks
      2. Compute reversal score (rank by 5d+10d+21d past returns)
      3. Check kill switch (rolling WR and IC)
      4. If active: select top 10 losers
      5. Simulate entry with slippage
      6. Check exits for positions held 5+ days
      7. Log everything
    """

    def __init__(
        self,
        kite=None,
        capital: float = 100000.0,
        top_n: int = 10,
        hold_days: int = 5,
        slippage_pct: float = 0.002,     # 0.2% slippage
        cost_per_trade_pct: float = 0.001,  # 0.1% per side
        kill_switch_wr: float = 0.50,
        symbols: list[str] = None,
    ):
        self.kite = kite
        self.initial_capital = capital
        self.capital = capital
        self.top_n = top_n
        self.hold_days = hold_days
        self.slippage_pct = slippage_pct
        self.cost_per_side = cost_per_trade_pct
        self.kill_switch_wr = kill_switch_wr
        self.symbols = symbols or NIFTY_100

        # State
        self.positions: list[dict] = []   # Active positions (batches)
        self.trade_history: list[dict] = []
        self.daily_log: list[dict] = []
        self.kill_switch_active = False

        # Load state from disk
        self._load_state()

        logger.info(
            "ReversalEngine initialized",
            capital=self.capital,
            positions=len(self.positions),
            trades=len(self.trade_history),
        )

    # =========================================================================
    # Core Logic
    # =========================================================================

    def run_daily(self) -> dict:
        """
        Run the daily reversal cycle.

        Call this each trading day after 9:30 AM.

        Returns:
            Dict with today's actions and status
        """
        today = date.today()
        logger.info(f"Running daily cycle for {today}")

        result = {
            "date": str(today),
            "action": "none",
            "new_picks": [],
            "exits": [],
            "kill_switch": False,
            "portfolio_value": self.capital,
        }

        # 1. Fetch current prices
        prices = self._fetch_prices()
        if not prices:
            logger.error("Failed to fetch prices")
            result["action"] = "error_no_prices"
            return result

        # 2. Check exits for mature positions (held >= hold_days)
        exits = self._check_exits(prices, today)
        result["exits"] = exits

        # 3. Check market regime gate
        market_weak, market_reason = self._check_market_regime(prices)
        result["market_weak"] = market_weak
        result["market_reason"] = market_reason

        # 4. Check kill switch
        self.kill_switch_active = self._check_kill_switch()
        result["kill_switch"] = self.kill_switch_active

        if market_weak:
            logger.warning(f"Market regime WEAK — skipping entries ({market_reason})")
            result["action"] = f"market_weak: {market_reason}"
        elif self.kill_switch_active:
            logger.warning("Kill switch ACTIVE — skipping new entries")
            result["action"] = "kill_switch_active"
        else:
            # 4. Compute reversal scores and pick stocks
            picks = self._compute_picks(prices)
            result["new_picks"] = picks

            if picks:
                # 5. Simulate entry
                self._enter_positions(picks, prices, today)
                result["action"] = f"entered_{len(picks)}_stocks"
            else:
                result["action"] = "no_qualifying_picks"

        # 6. Update portfolio value
        result["portfolio_value"] = self._compute_portfolio_value(prices)

        # 7. Log daily state
        self._log_daily(today, result, prices)

        # 8. Save state
        self._save_state()

        # Print summary
        self._print_summary(result)

        return result

    def _fetch_prices(self) -> dict[str, float]:
        """Fetch current LTP for all symbols."""
        if self.kite is None:
            logger.warning("No Kite client — using saved daily data")
            return self._get_prices_from_saved_data()

        try:
            # Batch LTP fetch
            instruments = [f"NSE:{s}" for s in self.symbols]
            # Kite LTP accepts up to 1000 instruments
            ltp_data = self.kite.ltp(instruments)
            prices = {}
            for inst, data in ltp_data.items():
                symbol = inst.replace("NSE:", "")
                prices[symbol] = data["last_price"]
            return prices
        except Exception as e:
            logger.error(f"Failed to fetch LTP: {e}")
            return {}

    def _get_prices_from_saved_data(self) -> dict[str, float]:
        """Fallback: get latest prices from saved daily CSVs."""
        from backend.services.historical_data import HistoricalDataService
        ds = HistoricalDataService()
        prices = {}
        for symbol in self.symbols:
            df = ds.load_candles(symbol, "1d")
            if not df.empty:
                prices[symbol] = float(df.iloc[-1]["close"])
        return prices

    def _compute_picks(self, prices: dict[str, float]) -> list[dict]:
        """Compute reversal scores and return top N losers."""
        from backend.services.historical_data import HistoricalDataService
        ds = HistoricalDataService()

        # Need historical closes for momentum calculation
        scores = {}
        for symbol in self.symbols:
            df = ds.load_candles(symbol, "1d")
            if df.empty or len(df) < 25:
                continue

            close = df["close"]
            current = prices.get(symbol, close.iloc[-1])

            # Compute returns using saved data + current price
            if len(close) >= 21:
                ret_5d = (current - close.iloc[-5]) / close.iloc[-5] if close.iloc[-5] > 0 else 0
                ret_10d = (current - close.iloc[-10]) / close.iloc[-10] if close.iloc[-10] > 0 else 0
                ret_21d = (current - close.iloc[-21]) / close.iloc[-21] if close.iloc[-21] > 0 else 0

                scores[symbol] = {
                    "ret_5d": ret_5d,
                    "ret_10d": ret_10d,
                    "ret_21d": ret_21d,
                    "price": current,
                }

        if len(scores) < self.top_n:
            return []

        # Rank: worst performers get highest score (reversal = buy losers)
        # ascending=False means lowest return → highest rank (percentile near 1.0)
        score_df = pd.DataFrame(scores).T
        rank = (score_df["ret_5d"].rank(ascending=False, pct=True) +
                score_df["ret_10d"].rank(ascending=False, pct=True) +
                score_df["ret_21d"].rank(ascending=False, pct=True)) / 3

        # Top N (highest rank = biggest losers)
        top = rank.sort_values(ascending=False).head(self.top_n)

        # Skip stocks we already hold
        held_symbols = {p["symbol"] for batch in self.positions for p in batch["stocks"]}

        picks = []
        for symbol in top.index:
            if symbol in held_symbols:
                continue
            picks.append({
                "symbol": symbol,
                "score": float(rank[symbol]),
                "ret_5d": float(scores[symbol]["ret_5d"]),
                "ret_10d": float(scores[symbol]["ret_10d"]),
                "ret_21d": float(scores[symbol]["ret_21d"]),
                "price": scores[symbol]["price"],
            })

        return picks[:self.top_n]

    def _enter_positions(self, picks: list[dict], prices: dict, today: date) -> None:
        """Simulate entering positions for new picks."""
        per_stock_capital = self.capital * 0.05  # 5% per stock

        batch = {
            "entry_date": str(today),
            "exit_date": str(today + timedelta(days=self.hold_days + 2)),  # Approximate
            "stocks": [],
        }

        for pick in picks:
            price = pick["price"]
            # Apply slippage (buy at worse price)
            entry_price = price * (1 + self.slippage_pct)
            quantity = int(per_stock_capital / entry_price)
            if quantity <= 0:
                continue

            cost = entry_price * quantity * self.cost_per_side

            batch["stocks"].append({
                "symbol": pick["symbol"],
                "quantity": quantity,
                "entry_price": entry_price,
                "entry_cost": cost,
                "score": pick["score"],
                "ret_5d": pick["ret_5d"],
            })

        if batch["stocks"]:
            self.positions.append(batch)
            logger.info(f"Entered {len(batch['stocks'])} positions")

    def _check_exits(self, prices: dict, today: date) -> list[dict]:
        """Check and exit positions held for >= hold_days."""
        exits = []
        remaining = []

        for batch in self.positions:
            entry_date = datetime.strptime(batch["entry_date"], "%Y-%m-%d").date()
            days_held = (today - entry_date).days

            # Count only trading days (rough: subtract weekends)
            trading_days = days_held - (days_held // 7) * 2

            if trading_days >= self.hold_days:
                # Exit this batch
                for stock in batch["stocks"]:
                    current_price = prices.get(stock["symbol"], stock["entry_price"])
                    exit_price = current_price * (1 - self.slippage_pct)  # Sell at worse price
                    exit_cost = exit_price * stock["quantity"] * self.cost_per_side

                    gross_pnl = (exit_price - stock["entry_price"]) * stock["quantity"]
                    total_cost = stock["entry_cost"] + exit_cost
                    net_pnl = gross_pnl - total_cost

                    self.capital += net_pnl

                    trade = {
                        "symbol": stock["symbol"],
                        "entry_date": batch["entry_date"],
                        "exit_date": str(today),
                        "entry_price": stock["entry_price"],
                        "exit_price": exit_price,
                        "quantity": stock["quantity"],
                        "gross_pnl": gross_pnl,
                        "costs": total_cost,
                        "net_pnl": net_pnl,
                        "win": net_pnl > 0,
                    }

                    self.trade_history.append(trade)
                    exits.append(trade)

                    logger.info(
                        f"Exited {stock['symbol']}: "
                        f"{'WIN' if net_pnl > 0 else 'LOSS'} "
                        f"₹{net_pnl:,.0f}"
                    )
            else:
                remaining.append(batch)

        self.positions = remaining
        return exits

    def _check_market_regime(self, prices: dict) -> tuple[bool, str]:
        """
        Check if market regime supports trading.

        Returns:
            (is_weak, reason)
        """
        # 1. NIFTY check: is market falling today?
        if self.kite:
            try:
                nifty = self.kite.ohlc(["NSE:NIFTY 50"])
                n = nifty.get("NSE:NIFTY 50", {})
                ltp = n.get("last_price", 0)
                prev_close = n.get("ohlc", {}).get("close", ltp)

                if prev_close > 0:
                    nifty_change = (ltp - prev_close) / prev_close
                    if nifty_change < -0.005:  # NIFTY down > 0.5%
                        return True, f"NIFTY down {nifty_change*100:.1f}%"
            except Exception as e:
                logger.warning(f"Failed to check NIFTY: {e}")

        # 2. Breadth check: are most stocks falling?
        if prices:
            from backend.services.historical_data import HistoricalDataService
            ds = HistoricalDataService()

            falling = 0
            total = 0
            for symbol, current_price in list(prices.items())[:50]:
                df = ds.load_candles(symbol, "1d")
                if df.empty:
                    continue
                prev_close = df.iloc[-1]["close"]
                if prev_close > 0:
                    total += 1
                    if current_price < prev_close:
                        falling += 1

            if total > 20:
                breadth = falling / total
                if breadth > 0.70:  # >70% stocks falling
                    return True, f"Breadth weak: {falling}/{total} ({breadth:.0%}) stocks falling"

        # 3. NIFTY 5-day trend: check if in sustained decline
        nifty_path = _DATA_DIR / "index" / "NIFTY50_daily.csv"
        if nifty_path.exists():
            nifty_df = pd.read_csv(nifty_path)
            if len(nifty_df) >= 5:
                close = nifty_df["close"]
                ret_5d = (close.iloc[-1] - close.iloc[-5]) / close.iloc[-5]
                if ret_5d < -0.03:  # NIFTY down > 3% in 5 days
                    return True, f"NIFTY 5-day trend: {ret_5d*100:.1f}%"

        return False, "market OK"

    def _check_kill_switch(self) -> bool:
        """Check if kill switch should activate."""
        if len(self.trade_history) < 20:
            return False  # Not enough data

        recent = self.trade_history[-20:]
        wr = sum(1 for t in recent if t["win"]) / len(recent)

        if wr < self.kill_switch_wr:
            logger.warning(f"Kill switch: WR={wr:.0%} < {self.kill_switch_wr:.0%}")
            return True

        return False

    def _compute_portfolio_value(self, prices: dict) -> float:
        """Compute total portfolio value including open positions."""
        open_value = 0
        for batch in self.positions:
            for stock in batch["stocks"]:
                current = prices.get(stock["symbol"], stock["entry_price"])
                open_value += current * stock["quantity"]

        return self.capital + open_value

    # =========================================================================
    # Logging
    # =========================================================================

    def _log_daily(self, today: date, result: dict, prices: dict) -> None:
        """Log daily state."""
        recent_trades = self.trade_history[-20:] if self.trade_history else []
        wr = sum(1 for t in recent_trades if t["win"]) / len(recent_trades) if recent_trades else 0

        entry = {
            "date": str(today),
            "capital": self.capital,
            "portfolio_value": result["portfolio_value"],
            "open_positions": sum(len(b["stocks"]) for b in self.positions),
            "total_trades": len(self.trade_history),
            "rolling_wr_20": wr,
            "kill_switch": self.kill_switch_active,
            "action": result["action"],
            "new_picks": [p["symbol"] for p in result.get("new_picks", [])],
            "exits": [e["symbol"] for e in result.get("exits", [])],
        }

        self.daily_log.append(entry)

    def _print_summary(self, result: dict) -> None:
        """Print daily summary."""
        pnl = self.capital - self.initial_capital
        total_trades = len(self.trade_history)
        wins = sum(1 for t in self.trade_history if t["win"])
        wr = wins / total_trades * 100 if total_trades > 0 else 0

        print(f"\n{'='*50}")
        print(f"DAILY REVERSAL — {result['date']}")
        print(f"{'='*50}")
        print(f"  Action: {result['action']}")
        print(f"  Market: {'WEAK — ' + result.get('market_reason', '') if result.get('market_weak') else 'OK'}")
        print(f"  Kill Switch: {'ACTIVE' if result['kill_switch'] else 'OK'}")
        print(f"  Capital: ₹{self.capital:,.0f}")
        print(f"  Portfolio: ₹{result['portfolio_value']:,.0f}")
        print(f"  P&L: ₹{pnl:,.0f} ({pnl/self.initial_capital*100:+.1f}%)")
        print(f"  Trades: {total_trades} (WR: {wr:.0f}%)")
        print(f"  Open Batches: {len(self.positions)}")

        if result.get("new_picks"):
            print(f"\n  New Picks:")
            for p in result["new_picks"][:5]:
                print(f"    {p['symbol']:>12} | 5d={p['ret_5d']*100:+.1f}% | Score={p['score']:.2f}")

        if result.get("exits"):
            print(f"\n  Exits:")
            for e in result["exits"][:5]:
                marker = "WIN" if e["net_pnl"] > 0 else "LOSS"
                print(f"    {e['symbol']:>12} | ₹{e['net_pnl']:+,.0f} | {marker}")

    # =========================================================================
    # State Persistence
    # =========================================================================

    def _save_state(self) -> None:
        """Save state to disk."""
        state = {
            "capital": self.capital,
            "positions": self.positions,
        }
        PORTFOLIO_FILE.write_text(json.dumps(state, indent=2, default=str))

        if self.trade_history:
            TRADE_LOG_FILE.write_text(json.dumps(self.trade_history, indent=2, default=str))

        if self.daily_log:
            DAILY_LOG_FILE.write_text(json.dumps(self.daily_log, indent=2, default=str))

    def _load_state(self) -> None:
        """Load state from disk."""
        if PORTFOLIO_FILE.exists():
            try:
                state = json.loads(PORTFOLIO_FILE.read_text())
                self.capital = state.get("capital", self.initial_capital)
                self.positions = state.get("positions", [])
            except Exception:
                pass

        if TRADE_LOG_FILE.exists():
            try:
                self.trade_history = json.loads(TRADE_LOG_FILE.read_text())
            except Exception:
                pass

        if DAILY_LOG_FILE.exists():
            try:
                self.daily_log = json.loads(DAILY_LOG_FILE.read_text())
            except Exception:
                pass

    def reset(self) -> None:
        """Reset all state (for fresh start)."""
        self.capital = self.initial_capital
        self.positions = []
        self.trade_history = []
        self.daily_log = []
        self.kill_switch_active = False

        # Delete files
        for f in [PORTFOLIO_FILE, TRADE_LOG_FILE, DAILY_LOG_FILE]:
            if f.exists():
                f.unlink()

        logger.info("Engine reset")

    def get_status(self) -> dict:
        """Get current engine status for dashboard."""
        pnl = self.capital - self.initial_capital
        total = len(self.trade_history)
        wins = sum(1 for t in self.trade_history if t["win"])

        return {
            "capital": self.capital,
            "pnl": pnl,
            "pnl_pct": pnl / self.initial_capital * 100,
            "total_trades": total,
            "win_rate": wins / total * 100 if total > 0 else 0,
            "open_positions": sum(len(b["stocks"]) for b in self.positions),
            "kill_switch_active": self.kill_switch_active,
            "positions": self.positions,
            "recent_trades": self.trade_history[-10:] if self.trade_history else [],
        }
