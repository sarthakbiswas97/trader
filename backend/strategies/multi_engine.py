"""
Multi-Engine Orchestrator — Regime-Gated Cross-Sectional Reversal System.

One alpha (mean reversion), two universes (large-cap + midcap),
regime-based exposure control.

Capital allocation by regime:
  BULL:    35% large-cap + 40% midcap + 25% cash  (75% deployed)
  NEUTRAL: 45% large-cap + 15% midcap + 40% cash  (60% deployed)
  WEAK:    15% large-cap + 10% midcap + 75% cash  (25% deployed, IC strongest here)

Kill switches:
  - Per-engine: rolling 20-trade win rate < 50%
  - Global: rolling IC < -0.02 (signal decay)
  - Entry filter: skip stocks down > 5% today

Validated performance (5.4-year backtest):
  Large-cap reversal: IC=+0.020, +44% return, Sharpe 0.96
  Midcap reversal:    IC=+0.025, +69% return, Sharpe 0.99
"""

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from backend.core.logger import get_logger
from backend.core.symbols import NIFTY_50, NIFTY_100_EXTRA
from backend.strategies.regime import Regime, RegimeClassifier

logger = get_logger(__name__)

_DATA_DIR = Path(__file__).parent.parent / "data"
_STATE_DIR = _DATA_DIR / "multi_engine"
_STATE_DIR.mkdir(parents=True, exist_ok=True)

STATE_FILE = _STATE_DIR / "state.json"

# Max intraday drop to allow entry — avoids catching panic continuation
MAX_TODAY_DROP = -0.05  # Don't enter if stock is down > 5% today


@dataclass
class EngineConfig:
    name: str
    strategy: str  # "reversal"
    symbols: list[str] = field(default_factory=list)
    top_n: int = 7  # Fix #5: reduced from 10 for higher conviction
    hold_days: int = 5
    slippage_pct: float = 0.002
    cost_per_side: float = 0.001


@dataclass
class EngineState:
    name: str
    capital: float = 0.0
    positions: list = field(default_factory=list)
    trade_history: list = field(default_factory=list)
    active: bool = False


# Regime base targets (center of range for each regime)
REGIME_TARGETS = {
    Regime.BULL: {"total": 0.75, "midcap_share": 0.55, "floor": 0.25, "dd_k": 0.5},
    Regime.NEUTRAL: {"total": 0.60, "midcap_share": 0.25, "floor": 0.15, "dd_k": 0.7},
    Regime.WEAK: {"total": 0.25, "midcap_share": 0.40, "floor": 0.08, "dd_k": 1.0},
}

# Hard limits
MAX_EXPOSURE_CAP = 0.85           # Never exceed 85%
BASE_MIDCAP_CAP = 0.55            # Midcap base cap (adjusted by volatility/DD)


def compute_confidence(
    rolling_ic: float | None = None,
    rolling_wr: float | None = None,
    nifty_ret_5d: float | None = None,
    breadth_pct: float | None = None,
) -> float:
    """
    Compute a confidence score from 0.0 to 1.0.

    This is proto-RL: continuous signal → continuous sizing.

    Components (weighted):
      IC signal strength:   40%  — is our ranking still predictive?
      Win rate:             25%  — are recent trades working?
      Momentum:             20%  — is market trending favorably?
      Breadth:              15%  — are stocks broadly participating?
    """
    scores = []
    weights = []

    # IC component: map from [-0.05, +0.05] → [0, 1]
    if rolling_ic is not None:
        ic_score = max(0, min(1, (rolling_ic + 0.02) / 0.04))  # -0.02 → 0.0, +0.02 → 1.0
        scores.append(ic_score)
        weights.append(0.40)

    # Win rate component: map from [0.3, 0.7] → [0, 1]
    if rolling_wr is not None:
        wr_score = max(0, min(1, (rolling_wr - 0.35) / 0.30))  # 35% → 0.0, 65% → 1.0
        scores.append(wr_score)
        weights.append(0.25)

    # Momentum component: map from [-0.03, +0.03] → [0, 1]
    if nifty_ret_5d is not None:
        mom_score = max(0, min(1, (nifty_ret_5d + 0.015) / 0.03))
        scores.append(mom_score)
        weights.append(0.20)

    # Breadth component: map from [0.3, 0.7] → [0, 1]
    if breadth_pct is not None:
        breadth_score = max(0, min(1, (breadth_pct - 0.35) / 0.30))
        scores.append(breadth_score)
        weights.append(0.15)

    if not scores:
        return 0.5  # No data — neutral confidence

    # Weighted average
    total_weight = sum(weights)
    return sum(s * w for s, w in zip(scores, weights)) / total_weight


def compute_dynamic_allocation(
    regime: Regime,
    rolling_ic: float | None = None,
    rolling_wr: float | None = None,
    nifty_ret_5d: float | None = None,
    breadth_pct: float | None = None,
    current_drawdown_pct: float = 0.0,
    prev_drawdown_pct: float = 0.0,
    prev_ic: float | None = None,
) -> dict[str, float]:
    """
    Continuous confidence-scored capital allocation with regime-aware tuning.

    Process:
      1. Confidence score (0-1) from IC + WR + momentum + breadth
      2. Scale total exposure around regime base
      3. Soft drawdown curve: allocation *= (1 - k * drawdown)
      4. Recovery boost: if DD recovering AND IC improving, +5-10% exposure
      5. Regime-specific floor (BULL 25%, NEUTRAL 15%, WEAK 8%)
      6. Adaptive midcap cap based on drawdown
    """
    target = REGIME_TARGETS[regime]

    # 1. Confidence score (continuous 0-1)
    confidence = compute_confidence(rolling_ic, rolling_wr, nifty_ret_5d, breadth_pct)

    # 2. Scale total exposure: base ± 15% based on confidence
    adjustment = (confidence - 0.5) * 0.30
    total_exposure = target["total"] + adjustment

    # 3. Soft drawdown curve — regime-weighted
    if current_drawdown_pct > 0.03:
        dd_k = target["dd_k"]
        total_exposure *= (1.0 - dd_k * current_drawdown_pct)

    # 4. Recovery boost: DD recovering AND IC improving → lean in faster
    dd_recovering = (
        prev_drawdown_pct > 0.03
        and current_drawdown_pct < prev_drawdown_pct * 0.8  # DD shrunk by 20%+
    )
    ic_improving = (
        rolling_ic is not None
        and prev_ic is not None
        and rolling_ic > prev_ic
        and rolling_ic > 0
    )
    if dd_recovering and ic_improving:
        # Boost 5-10% based on how much DD has recovered
        recovery_ratio = 1.0 - (current_drawdown_pct / max(prev_drawdown_pct, 0.01))
        boost = min(0.10, recovery_ratio * 0.10)  # Max 10% boost
        total_exposure += boost

    # 5. Regime-specific floor and cap
    floor = target["floor"]
    total_exposure = max(floor, min(MAX_EXPOSURE_CAP, total_exposure))

    # 5. Split between largecap and midcap
    midcap_share = target["midcap_share"]

    # Momentum scaling: strong trend → more midcap
    if nifty_ret_5d is not None:
        mom_adj = max(-0.15, min(0.15, nifty_ret_5d * 5))
        midcap_share += mom_adj

    # Adaptive midcap cap: tighten when in drawdown or low confidence
    midcap_cap = BASE_MIDCAP_CAP
    if current_drawdown_pct > 0.05:
        # Reduce midcap cap as DD increases (midcap is more volatile)
        midcap_cap = max(0.25, BASE_MIDCAP_CAP - current_drawdown_pct)
    if confidence < 0.3:
        midcap_cap = min(midcap_cap, 0.35)

    midcap_share = max(0.10, min(midcap_cap, midcap_share))

    midcap_alloc = total_exposure * midcap_share
    largecap_alloc = total_exposure - midcap_alloc
    cash_alloc = 1.0 - total_exposure

    return {
        "largecap": round(max(0, largecap_alloc), 3),
        "midcap": round(max(0, midcap_alloc), 3),
        "cash": round(max(0, cash_alloc), 3),
    }


class MultiEngine:
    """
    Regime-gated cross-sectional reversal system.

    Same alpha (mean reversion) deployed across large-cap and midcap
    universes, with regime-based exposure control.
    """

    def __init__(
        self,
        kite=None,
        total_capital: float = 100000.0,
    ):
        self.kite = kite
        self.total_capital = total_capital

        # Regime classifier (already has 2-day persistence — Fix #3)
        self.regime_classifier = RegimeClassifier()

        # Engine configs — both use reversal
        self.engines = {
            "largecap": EngineConfig(
                name="largecap",
                strategy="reversal",
                symbols=NIFTY_50,
                top_n=7,
                hold_days=5,
            ),
            "midcap": EngineConfig(
                name="midcap",
                strategy="reversal",
                symbols=NIFTY_100_EXTRA,
                top_n=5,
                hold_days=5,
            ),
        }

        # Engine states
        self.engine_states: dict[str, EngineState] = {
            "largecap": EngineState(name="largecap"),
            "midcap": EngineState(name="midcap"),
        }

        # Overall state
        self.current_regime = Regime.NEUTRAL
        self.cash = total_capital
        self.daily_log: list[dict] = []

        # Fix #4: Rolling IC tracker
        self.ic_history: list[dict] = []

        self._load_state()

    def run_daily(self) -> dict:
        """
        Run the daily multi-engine cycle.

        1. Classify regime
        2. Determine capital allocation
        3. Check exits
        4. Compute rolling IC
        5. Enter new positions (with entry filters)
        6. Log everything
        """
        today = date.today()
        logger.info(f"Multi-engine cycle: {today}")

        result = {
            "date": str(today),
            "regime": None,
            "engines": {},
            "portfolio_value": 0,
            "cash": 0,
            "rolling_ic": None,
            "capital_utilization": 0,
        }

        # 1. Classify regime
        regime = self._classify_regime()
        self.current_regime = regime
        result["regime"] = regime.value
        logger.info(f"Regime: {regime.value}")

        # 2. Compute dynamic allocation based on signal health
        rolling_wr = self._compute_rolling_wr()
        nifty_ret_5d = self._get_nifty_5d_return()
        breadth = self._compute_breadth() if self.kite else None
        current_dd = self._compute_current_drawdown()

        # Previous DD and IC for recovery detection
        prev_dd = self.daily_log[-1].get("drawdown_pct", 0) if self.daily_log else 0
        prev_ic = self.ic_history[-2]["ic"] if len(self.ic_history) >= 2 else None

        allocation = compute_dynamic_allocation(
            regime=regime,
            rolling_ic=self.ic_history[-1]["ic"] if self.ic_history else None,
            rolling_wr=rolling_wr,
            nifty_ret_5d=nifty_ret_5d,
            breadth_pct=breadth,
            current_drawdown_pct=current_dd,
            prev_drawdown_pct=prev_dd,
            prev_ic=prev_ic,
        )
        result["allocation"] = {k: v * 100 for k, v in allocation.items()}
        result["confidence"] = compute_confidence(
            self.ic_history[-1]["ic"] if self.ic_history else None,
            rolling_wr, nifty_ret_5d, breadth,
        )
        result["drawdown_pct"] = current_dd

        # 3. Fetch prices for all symbols
        prices = self._fetch_prices()
        if not prices:
            result["error"] = "no_prices"
            return result

        # 4. Fetch today's returns for entry filter
        today_returns = self._fetch_today_returns(prices)

        # 5. Compute rolling IC (Fix #4)
        rolling_ic = self._compute_rolling_ic(prices)
        result["rolling_ic"] = rolling_ic
        ic_kill = rolling_ic is not None and rolling_ic < -0.02

        if ic_kill:
            logger.warning(f"Rolling IC kill switch: IC={rolling_ic:.4f}")

        # 6. Run each engine
        for engine_name, config in self.engines.items():
            engine_alloc = allocation.get(engine_name, 0)
            state = self.engine_states[engine_name]

            engine_result = {
                "allocation_pct": engine_alloc * 100,
                "active": engine_alloc > 0,
                "action": "inactive",
                "picks": [],
                "exits": [],
                "skipped": [],
            }

            # Check exits for ALL engines (even inactive ones)
            exits = self._check_engine_exits(config, state, prices, today)
            engine_result["exits"] = exits

            if engine_alloc > 0 and not ic_kill:
                state.active = True
                target_capital = self.total_capital * engine_alloc

                # Allocate capital if needed
                if state.capital < target_capital * 0.5:
                    additional = min(target_capital - state.capital, self.cash)
                    if additional > 0:
                        state.capital += additional
                        self.cash -= additional

                # Check per-engine kill switch (win rate)
                if self._check_kill_switch(state):
                    engine_result["action"] = "kill_switch_wr"
                else:
                    # Compute picks with entry filter (Fix #2)
                    picks, skipped = self._compute_picks_filtered(
                        config, state, prices, today_returns
                    )
                    engine_result["picks"] = picks
                    engine_result["skipped"] = skipped

                    if picks:
                        self._enter_positions(config, state, picks, prices, today)
                        engine_result["action"] = f"entered_{len(picks)}"
                    else:
                        engine_result["action"] = "no_picks"
            elif ic_kill and engine_alloc > 0:
                state.active = True
                engine_result["action"] = "kill_switch_ic"
            else:
                state.active = False
                engine_result["action"] = "regime_inactive"

                # Return unused capital to cash pool
                if state.capital > 0 and not state.positions:
                    self.cash += state.capital
                    state.capital = 0

            # Engine metrics
            engine_result["capital"] = state.capital
            engine_result["open_positions"] = sum(
                len(b["stocks"]) for b in state.positions
            )
            engine_result["total_trades"] = len(state.trade_history)
            engine_result["pnl"] = self._engine_pnl(state)

            result["engines"][engine_name] = engine_result

        # 7. Compute total portfolio value + capital utilization
        total = self.cash
        invested = 0
        for state in self.engine_states.values():
            total += state.capital
            pos_value = self._open_position_value(state, prices)
            total += pos_value
            invested += pos_value

        result["portfolio_value"] = total
        result["cash"] = self.cash
        result["capital_utilization"] = invested / total * 100 if total > 0 else 0

        # 8. Log and save
        self.daily_log.append(result)
        self._save_state()
        self._print_summary(result)

        # 9. Persist to database (non-blocking — works even if DB is down)
        try:
            from backend.db.persist import persist_daily_cycle
            persist_daily_cycle(
                result=result,
                engine_states={n: s for n, s in self.engine_states.items()},
                regime_info=self.regime_classifier.get_status(),
            )
        except Exception as e:
            logger.warning(f"DB persistence failed (non-critical): {e}")

        return result

    # =========================================================================
    # Regime Classification
    # =========================================================================

    def _classify_regime(self) -> Regime:
        """Classify current market regime using NIFTY data."""
        if self.kite:
            try:
                nifty = self.kite.ohlc(["NSE:NIFTY 50"])
                n = nifty.get("NSE:NIFTY 50", {})
                close = n.get("last_price", 0)
                prev_close = n.get("ohlc", {}).get("close", close)

                if prev_close > 0 and close > 0:
                    ret_1d = (close - prev_close) / prev_close

                    nifty_path = _DATA_DIR / "index" / "NIFTY50_daily.csv"
                    dma_50 = close
                    ret_5d = 0

                    if nifty_path.exists():
                        df = pd.read_csv(nifty_path)
                        if len(df) >= 50:
                            dma_50 = df["close"].tail(50).mean()
                        if len(df) >= 5:
                            ret_5d = (close - df["close"].iloc[-5]) / df["close"].iloc[-5]

                    breadth = self._compute_breadth()

                    return self.regime_classifier.classify(
                        close, dma_50, ret_5d, ret_1d, breadth
                    )
            except Exception as e:
                logger.warning(f"Regime classification failed: {e}")

        # Fallback: use saved data
        nifty_path = _DATA_DIR / "index" / "NIFTY50_daily.csv"
        if nifty_path.exists():
            df = pd.read_csv(nifty_path)
            if len(df) >= 50:
                close = df["close"].iloc[-1]
                dma_50 = df["close"].tail(50).mean()
                ret_5d = (close - df["close"].iloc[-5]) / df["close"].iloc[-5] if len(df) >= 5 else 0
                ret_1d = (close - df["close"].iloc[-2]) / df["close"].iloc[-2] if len(df) >= 2 else 0
                return self.regime_classifier.classify(close, dma_50, ret_5d, ret_1d, 0.5)

        return Regime.NEUTRAL

    def _compute_breadth(self) -> float:
        """Compute market breadth from live data."""
        if not self.kite:
            return 0.5

        try:
            sample = NIFTY_50[:30]
            ohlc = self.kite.ohlc([f"NSE:{s}" for s in sample])

            above = 0
            total = 0
            for s in sample:
                key = f"NSE:{s}"
                if key in ohlc:
                    total += 1
                    curr = ohlc[key].get("last_price", 0)
                    prev = ohlc[key].get("ohlc", {}).get("close", curr)
                    if curr > prev:
                        above += 1

            return above / total if total > 10 else 0.5
        except Exception:
            return 0.5

    # =========================================================================
    # Price Fetching
    # =========================================================================

    def _fetch_prices(self) -> dict[str, float]:
        """Fetch LTP for all symbols across all engines."""
        all_symbols = set()
        for config in self.engines.values():
            all_symbols.update(config.symbols)

        if self.kite:
            try:
                instruments = [f"NSE:{s}" for s in all_symbols]
                ltp_data = self.kite.ltp(instruments)
                return {
                    inst.replace("NSE:", ""): data["last_price"]
                    for inst, data in ltp_data.items()
                }
            except Exception as e:
                logger.error(f"LTP fetch failed: {e}")

        # Fallback: saved data
        from backend.services.historical_data import HistoricalDataService
        ds = HistoricalDataService()
        prices = {}
        for symbol in all_symbols:
            df = ds.load_candles(symbol, "daily")
            if not df.empty:
                prices[symbol] = float(df.iloc[-1]["close"])
        return prices

    def _fetch_today_returns(self, prices: dict) -> dict[str, float]:
        """
        Fix #2: Fetch today's return for each stock.
        Used to filter out stocks crashing > 5% today.
        """
        today_ret = {}

        if self.kite:
            try:
                all_symbols = list(prices.keys())
                ohlc_data = self.kite.ohlc([f"NSE:{s}" for s in all_symbols])
                for s in all_symbols:
                    key = f"NSE:{s}"
                    if key in ohlc_data:
                        curr = ohlc_data[key].get("last_price", 0)
                        prev = ohlc_data[key].get("ohlc", {}).get("close", curr)
                        if prev > 0:
                            today_ret[s] = (curr - prev) / prev
                return today_ret
            except Exception as e:
                logger.warning(f"OHLC fetch for today returns failed: {e}")

        return today_ret

    # =========================================================================
    # Stock Selection (with entry filter)
    # =========================================================================

    def _compute_picks_filtered(
        self,
        config: EngineConfig,
        state: EngineState,
        prices: dict,
        today_returns: dict,
    ) -> tuple[list[dict], list[dict]]:
        """
        Compute stock picks with entry safety filter.

        Skips stocks down > 5% today to avoid panic continuation.

        Returns:
            (picks, skipped) — skipped stocks with reason
        """
        from backend.core.scoring import compute_reversal_scores

        score_df = compute_reversal_scores(config.symbols, prices)
        if score_df.empty or len(score_df) < config.top_n:
            return [], []

        # Take top candidates with buffer for filtering
        top = score_df.head(config.top_n + 5)

        # Skip stocks already held
        held = {p["symbol"] for batch in state.positions for p in batch["stocks"]}

        picks = []
        skipped = []

        for symbol in top.index:
            if symbol in held:
                continue

            row = top.loc[symbol]

            # Entry timing filter — don't enter if crashing today
            today_ret = today_returns.get(symbol, 0)
            if today_ret < MAX_TODAY_DROP:
                skipped.append({
                    "symbol": symbol,
                    "reason": f"down {today_ret*100:.1f}% today (> {MAX_TODAY_DROP*100:.0f}% limit)",
                    "ret_5d": float(row["ret_5d"]),
                })
                logger.info(f"Skipped {symbol}: down {today_ret*100:.1f}% today")
                continue

            picks.append({
                "symbol": symbol,
                "score": float(row["score"]),
                "ret_5d": float(row["ret_5d"]),
                "ret_today": today_ret,
                "price": float(row["price"]),
            })

            if len(picks) >= config.top_n:
                break

        return picks, skipped

    # =========================================================================
    # Position Management
    # =========================================================================

    def _enter_positions(
        self,
        config: EngineConfig,
        state: EngineState,
        picks: list[dict],
        prices: dict,
        today: date,
    ) -> None:
        """Simulate entry for an engine."""
        # Fix #5: Size relative to engine capital, 10% per stock for 7 stocks = 70% invested
        per_stock = state.capital * 0.10

        batch = {"entry_date": str(today), "stocks": []}

        for pick in picks:
            price = pick["price"]
            entry_price = price * (1 + config.slippage_pct)
            quantity = int(per_stock / entry_price)
            if quantity <= 0:
                continue

            cost = entry_price * quantity * config.cost_per_side

            batch["stocks"].append({
                "symbol": pick["symbol"],
                "quantity": quantity,
                "entry_price": entry_price,
                "entry_cost": cost,
                "score": pick["score"],
                "ret_5d": pick["ret_5d"],
                "ret_today": pick.get("ret_today", 0),
            })

        if batch["stocks"]:
            state.positions.append(batch)
            logger.info(f"[{config.name}] Entered {len(batch['stocks'])} positions")

    def _check_engine_exits(
        self, config: EngineConfig, state: EngineState, prices: dict, today: date
    ) -> list[dict]:
        """Check and exit mature positions for an engine."""
        exits = []
        remaining = []

        for batch in state.positions:
            entry_date = datetime.strptime(batch["entry_date"], "%Y-%m-%d").date()
            days_held = (today - entry_date).days
            trading_days = days_held - (days_held // 7) * 2

            if trading_days >= config.hold_days:
                for stock in batch["stocks"]:
                    current = prices.get(stock["symbol"], stock["entry_price"])
                    exit_price = current * (1 - config.slippage_pct)
                    exit_cost = exit_price * stock["quantity"] * config.cost_per_side

                    gross_pnl = (exit_price - stock["entry_price"]) * stock["quantity"]
                    total_cost = stock["entry_cost"] + exit_cost
                    net_pnl = gross_pnl - total_cost

                    state.capital += net_pnl

                    trade = {
                        "symbol": stock["symbol"],
                        "engine": config.name,
                        "entry_date": batch["entry_date"],
                        "exit_date": str(today),
                        "entry_price": stock["entry_price"],
                        "exit_price": exit_price,
                        "quantity": stock["quantity"],
                        "net_pnl": net_pnl,
                        "win": net_pnl > 0,
                    }
                    state.trade_history.append(trade)
                    exits.append(trade)
            else:
                remaining.append(batch)

        state.positions = remaining
        return exits

    # =========================================================================
    # Signal Health & Portfolio Metrics (for dynamic allocation)
    # =========================================================================

    def _compute_current_drawdown(self) -> float:
        """Compute current drawdown from peak portfolio value."""
        if not self.daily_log:
            return 0.0

        values = [entry.get("portfolio_value", self.total_capital) for entry in self.daily_log]
        values.append(self.cash + sum(es.capital for es in self.engine_states.values()))

        peak = max(values)
        current = values[-1]

        if peak <= 0:
            return 0.0

        return max(0.0, (peak - current) / peak)

    def _compute_rolling_wr(self) -> float | None:
        """Compute rolling win rate across all engines (last 20 trades)."""
        all_trades = []
        for es in self.engine_states.values():
            all_trades.extend(es.trade_history)

        if len(all_trades) < 10:
            return None

        recent = all_trades[-20:]
        return sum(1 for t in recent if t.get("win")) / len(recent)

    def _get_nifty_5d_return(self) -> float | None:
        """Get NIFTY 5-day return for midcap scaling."""
        if self.kite:
            try:
                nifty = self.kite.ohlc(["NSE:NIFTY 50"])
                close = nifty.get("NSE:NIFTY 50", {}).get("last_price", 0)
                nifty_path = _DATA_DIR / "index" / "NIFTY50_daily.csv"
                if nifty_path.exists() and close > 0:
                    df = pd.read_csv(nifty_path)
                    if len(df) >= 5:
                        return (close - df["close"].iloc[-5]) / df["close"].iloc[-5]
            except Exception:
                pass

        # Fallback: saved data
        nifty_path = _DATA_DIR / "index" / "NIFTY50_daily.csv"
        if nifty_path.exists():
            df = pd.read_csv(nifty_path)
            if len(df) >= 5:
                return (df["close"].iloc[-1] - df["close"].iloc[-5]) / df["close"].iloc[-5]

        return None

    # =========================================================================
    # Kill Switches
    # =========================================================================

    def _check_kill_switch(self, state: EngineState) -> bool:
        """Per-engine kill switch: win rate based."""
        if len(state.trade_history) < 20:
            return False
        recent = state.trade_history[-20:]
        wr = sum(1 for t in recent if t["win"]) / len(recent)
        return wr < 0.50

    def _compute_rolling_ic(self, prices: dict) -> float | None:
        """
        Fix #4: Compute rolling IC — the TRUE kill switch.

        Measures if our reversal signal is still working in live trading.
        Uses last 20 completed trades: correlates entry score with actual return.
        """
        # Collect all completed trades across engines
        all_trades = []
        for es in self.engine_states.values():
            all_trades.extend(es.trade_history)

        if len(all_trades) < 10:
            return None

        recent = all_trades[-20:]

        # Score = entry reversal score, Return = actual P&L %
        scores = []
        returns = []

        for t in recent:
            if "entry_price" in t and "exit_price" in t and t["entry_price"] > 0:
                ret = (t["exit_price"] - t["entry_price"]) / t["entry_price"]
                returns.append(ret)
                # Higher score = more oversold = expected to bounce more
                scores.append(t.get("score", 0.5))

        if len(scores) < 10:
            return None

        ic, _ = spearmanr(scores, returns)
        if np.isnan(ic):
            return None

        # Log IC
        self.ic_history.append({
            "date": str(date.today()),
            "ic": ic,
            "n_trades": len(scores),
        })

        logger.info(f"Rolling IC (last {len(scores)} trades): {ic:.4f}")
        return ic

    # =========================================================================
    # Helpers
    # =========================================================================

    def _engine_pnl(self, state: EngineState) -> float:
        """Total realized P&L for an engine."""
        return sum(t["net_pnl"] for t in state.trade_history)

    def _open_position_value(self, state: EngineState, prices: dict) -> float:
        """Mark-to-market value of open positions."""
        value = 0
        for batch in state.positions:
            for stock in batch["stocks"]:
                current = prices.get(stock["symbol"], stock["entry_price"])
                value += current * stock["quantity"]
        return value

    def _print_summary(self, result: dict) -> None:
        """Print daily summary."""
        total_pnl = result["portfolio_value"] - self.total_capital

        print(f"\n{'='*60}")
        print(f"MULTI-ENGINE — {result['date']}")
        print(f"{'='*60}")
        print(f"  Regime: {result['regime']}")
        print(f"  Portfolio: ₹{result['portfolio_value']:,.0f}")
        print(f"  Cash: ₹{result['cash']:,.0f}")
        print(f"  Capital Util: {result.get('capital_utilization', 0):.0f}%")
        print(f"  Confidence:  {result.get('confidence', 0.5):.2f}")
        dd = result.get("drawdown_pct", 0)
        print(f"  Drawdown:    {dd:.1f}%{'  ⚠ SCALING DOWN' if dd > 3.0 else ''}")
        print(f"  Total P&L: ₹{total_pnl:,.0f} ({total_pnl/self.total_capital*100:+.1f}%)")

        if result.get("rolling_ic") is not None:
            ic = result["rolling_ic"]
            status = "HEALTHY" if ic > 0 else "WARNING" if ic > -0.02 else "KILLED"
            print(f"  Rolling IC: {ic:.4f} [{status}]")

        for name, eng in result["engines"].items():
            status = "ACTIVE" if eng["active"] else "INACTIVE"
            print(f"\n  [{name.upper()}] {status} — {eng['allocation_pct']:.0f}% alloc")
            print(f"    Capital: ₹{eng['capital']:,.0f}")
            print(f"    Open: {eng['open_positions']} positions")
            print(f"    Trades: {eng['total_trades']}")
            print(f"    P&L: ₹{eng['pnl']:,.0f}")
            print(f"    Action: {eng['action']}")

            if eng.get("picks"):
                for p in eng["picks"][:3]:
                    today_str = f" today={p.get('ret_today', 0)*100:+.1f}%" if p.get("ret_today") else ""
                    print(f"      → {p['symbol']} (5d: {p['ret_5d']*100:+.1f}%{today_str})")

            if eng.get("skipped"):
                for s in eng["skipped"]:
                    print(f"      ✗ {s['symbol']} — {s['reason']}")

    # =========================================================================
    # State Persistence
    # =========================================================================

    def _save_state(self) -> None:
        """Save complete state to disk."""
        state = {
            "total_capital": self.total_capital,
            "cash": self.cash,
            "current_regime": self.current_regime.value,
            "ic_history": self.ic_history[-100:],  # Keep last 100
            "engines": {},
        }

        for name, es in self.engine_states.items():
            state["engines"][name] = {
                "capital": es.capital,
                "positions": es.positions,
                "trade_history": es.trade_history,
                "active": es.active,
            }

        STATE_FILE.write_text(json.dumps(state, indent=2, default=str))

        # Save daily log
        log_file = _STATE_DIR / "daily_log.json"
        if self.daily_log:
            log_file.write_text(json.dumps(self.daily_log, indent=2, default=str))

    def _load_state(self) -> None:
        """Load state from disk."""
        if not STATE_FILE.exists():
            return

        try:
            state = json.loads(STATE_FILE.read_text())
            self.cash = state.get("cash", self.total_capital)
            self.current_regime = Regime(state.get("current_regime", "NEUTRAL"))
            self.ic_history = state.get("ic_history", [])

            for name, es_data in state.get("engines", {}).items():
                if name in self.engine_states:
                    es = self.engine_states[name]
                    es.capital = es_data.get("capital", 0)
                    es.positions = es_data.get("positions", [])
                    es.trade_history = es_data.get("trade_history", [])
                    es.active = es_data.get("active", False)
        except Exception as e:
            logger.warning(f"Failed to load state: {e}")

        # Load daily log
        log_file = _STATE_DIR / "daily_log.json"
        if log_file.exists():
            try:
                self.daily_log = json.loads(log_file.read_text())
            except Exception:
                pass

    def reset(self) -> None:
        """Reset all state."""
        self.cash = self.total_capital
        self.current_regime = Regime.NEUTRAL
        self.daily_log = []
        self.ic_history = []

        for es in self.engine_states.values():
            es.capital = 0
            es.positions = []
            es.trade_history = []
            es.active = False

        for f in _STATE_DIR.iterdir():
            f.unlink()

        logger.info("Multi-engine reset")

    def get_status(self) -> dict:
        """Get status for dashboard API."""
        total_pnl = sum(self._engine_pnl(es) for es in self.engine_states.values())
        total_trades = sum(len(es.trade_history) for es in self.engine_states.values())
        total_wins = sum(
            sum(1 for t in es.trade_history if t["win"])
            for es in self.engine_states.values()
        )

        engines_status = {}
        for name, es in self.engine_states.items():
            eng_trades = len(es.trade_history)
            eng_wins = sum(1 for t in es.trade_history if t["win"])
            engines_status[name] = {
                "active": es.active,
                "capital": es.capital,
                "pnl": self._engine_pnl(es),
                "open_positions": sum(len(b["stocks"]) for b in es.positions),
                "total_trades": eng_trades,
                "win_rate": eng_wins / eng_trades * 100 if eng_trades > 0 else 0,
                "positions": es.positions,
                "recent_trades": es.trade_history[-5:] if es.trade_history else [],
            }

        regime_info = self.regime_classifier.get_status()

        # Compute current dynamic allocation
        latest_ic = self.ic_history[-1]["ic"] if self.ic_history else None
        rolling_wr = self._compute_rolling_wr()
        nifty_ret_5d = self._get_nifty_5d_return()
        current_dd = self._compute_current_drawdown()
        alloc = compute_dynamic_allocation(
            self.current_regime, latest_ic, rolling_wr, nifty_ret_5d,
            current_drawdown_pct=current_dd,
        )
        confidence = compute_confidence(latest_ic, rolling_wr, nifty_ret_5d)

        # Capital utilization
        portfolio_value = self.cash + sum(es.capital for es in self.engine_states.values())
        invested = sum(es.capital for es in self.engine_states.values() if es.positions)
        cap_util = invested / portfolio_value * 100 if portfolio_value > 0 else 0

        return {
            "regime": self.current_regime.value,
            "regime_detail": regime_info,
            "allocation": {k: v * 100 for k, v in alloc.items()},
            "total_capital": self.total_capital,
            "cash": self.cash,
            "portfolio_value": portfolio_value,
            "total_pnl": total_pnl,
            "total_pnl_pct": total_pnl / self.total_capital * 100,
            "total_trades": total_trades,
            "win_rate": total_wins / total_trades * 100 if total_trades > 0 else 0,
            "rolling_ic": latest_ic,
            "confidence": confidence,
            "drawdown_pct": current_dd * 100,
            "capital_utilization": cap_util,
            "engines": engines_status,
        }
