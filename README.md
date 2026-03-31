# Autonomous Trading System

A research-backed trading system for Indian equity markets (NIFTY 100) using Zerodha Kite Connect. Built through systematic research — tested 6 strategies, found one that works, then iterated through 4 versions of allocation logic to maximize capital efficiency.

## The Edge

**Short-term reversal in Indian equities.** Stocks that fall the most over the past 5–21 days tend to bounce back within 5 trading days. This is a structural behavioral effect — driven by human psychology (panic selling → value buying), not patterns that algorithms can arbitrage away.

| Metric | Value |
|--------|-------|
| Signal | Daily cross-sectional reversal |
| Universe | 96 stocks (NIFTY 50 + NIFTY 100 Extra) |
| Holding period | 5 trading days |
| IC (Information Coefficient) | +0.020 large-cap, +0.025 midcap |
| Win rate | 54–58% |
| Backtest return (5.4 years) | +40% combined (v4.2 locked baseline) |

## System Architecture

```
Market Data → Regime Classifier → Dynamic Allocation → Engines → Execution
                  │                      │                 │
            BULL/NEUTRAL/WEAK    Confidence Score    Large-cap + Midcap
                  │                      │            Reversal Engines
            Adjusts exposure     IC + WR + Momentum        │
            continuously         + Breadth → 0-1       Buy top losers
                                                       Hold 5 days
                                        │
                                  Drawdown Dampening
                                  Recovery Boost
                                  Kill Switch
```

### Multi-Engine Design

Two engines running the same alpha (reversal) on different universes:

| Engine | Universe | Stocks | IC | Backtest Return |
|--------|----------|--------|-----|----------------|
| Large-Cap | NIFTY 50 | 48 | +0.020 | +38% |
| Midcap | NIFTY 100 Extra | 48 | +0.025 | +108% |

### Dynamic Allocation (v4.2)

Capital allocation adapts continuously based on:
- **Regime** — Bull/Neutral/Weak determines base exposure
- **Confidence score** — IC + win rate + momentum + breadth → smooth 0-1 scaling
- **Drawdown dampening** — Regime-weighted (gentle in bull, aggressive in weak)
- **Recovery boost** — When drawdown recovering AND signal improving, lean in faster
- **Midcap cap** — Adaptive ceiling tightens during stress

| Regime | Exposure Range | Behavior |
|--------|---------------|----------|
| Bull | 65–85% | Aggressive, midcap-heavy |
| Neutral | 50–75% | Balanced, largecap-heavy |
| Weak | 8–40% | Defensive but active (IC is strongest here) |

## Version History

| Version | Change | Combined Return |
|---------|--------|----------------|
| v1 | Core reversal + 100% cash in weak | +26% |
| v2 | Deploy capital in weak regime | +38% (+44% vs v1) |
| v3 | Step-based IC/momentum sizing | +40% |
| v4 | Continuous confidence scoring | +38% (robustness tradeoff) |
| **v4.2** | **Soft DD + regime floors + recovery boost** | **+40% (locked baseline)** |

Every improvement came from better capital allocation — the signal never changed.

## Research Journey

Tested 6 strategies before finding the edge:

| # | Strategy | Result | Why |
|---|----------|--------|-----|
| 1 | ML Prediction (5-min) | Failed | No signal in OHLCV features |
| 2 | Breakout Detection | Failed | Fakeouts, no follow-through |
| 3 | Mean Reversion (5-min) | Failed | Signal too weak after costs |
| 4 | Trend Following (30-min) | Failed | No intraday trend persistence |
| 5 | Cross-Sectional ML | Failed | IC ≈ 0 at intraday resolution |
| 6 | **Daily Reversal** | **Validated** | Structural behavioral effect |

**Key finding:** Indian large-cap stocks are too efficient at 5-minute resolution. Every intraday strategy loses money. The edge exists at the daily level where behavioral effects (overreaction, panic selling) create predictable 5-day bounces.

## Quick Start

```bash
# Install
make install

# Authenticate with Zerodha (daily)
make auth

# Start backend + frontend
make dev

# Run multi-engine daily cycle
python -m backend.scripts.run_multi_engine

# Check status
python -m backend.scripts.run_multi_engine --status

# Run backtest
python -m backend.scripts.backtest_regime --compare
```

## Project Structure

```
trader/
├── backend/
│   ├── strategies/
│   │   ├── multi_engine.py          # Orchestrator (dynamic allocation)
│   │   ├── regime.py                # 3-state regime classifier
│   │   ├── daily_momentum/          # Reversal engine + pseudo trading
│   │   ├── midcap_momentum/         # Midcap backtest + regime analysis
│   │   └── (breakout, mean_reversion, trend_30m, cross_sectional — tested, not used)
│   ├── core/
│   │   ├── scoring.py               # Shared reversal ranking
│   │   ├── symbols.py               # NIFTY 50 + 100 universes
│   │   └── indicators.py            # Technical indicators
│   ├── db/                          # Postgres persistence (Neon)
│   │   ├── models.py                # trades, snapshots, scores, regime_history
│   │   ├── repository.py            # Data access layer
│   │   └── persist.py               # Multi-engine → DB bridge
│   ├── api/                         # FastAPI (22 endpoints)
│   ├── broker/                      # Zerodha + Paper trading
│   ├── services/                    # Backtester, execution, risk, features
│   ├── ml/                          # XGBoost (demo only — system uses rule-based ranking)
│   └── scripts/                     # CLI tools
├── frontend/                        # Next.js dashboard
├── Dockerfile                       # Multi-stage (non-root)
└── docker-compose.yml
```

## Tech Stack

| Component | Technology |
|-----------|------------|
| Backend | Python 3.13, FastAPI |
| Frontend | Next.js 16, Tailwind, shadcn/ui |
| Database | Neon Postgres (SQLAlchemy) |
| Broker | Zerodha Kite Connect |
| ML | XGBoost (prediction page demo) |
| Data | 5.4 years daily OHLCV for 96 stocks |

## Risk Management

| Layer | Mechanism |
|-------|-----------|
| Regime gate | Reduces exposure in weak markets (never zero — floor at 8%) |
| Drawdown dampening | Soft curve: `alloc *= (1 - k * drawdown)`, regime-weighted k |
| Recovery boost | Increase exposure when DD recovering + IC improving |
| Kill switch | Pause engine if rolling 20-trade WR < 50% |
| IC kill switch | Halt all trading if rolling IC < -0.02 |
| Entry filter | Skip stocks down > 5% today (panic continuation risk) |
| Position limits | 10% capital per stock, 7 stocks per engine |

## Paper Trading

The system runs daily pseudo-trades with state persisted to Neon Postgres:

```bash
# Run daily (after 9:30 AM IST)
python -m backend.scripts.run_multi_engine

# All trades, snapshots, scores logged to:
#   trades          — every entry/exit with context
#   daily_snapshots — portfolio state each day
#   stock_scores    — full ranking (RL-ready action space)
#   regime_history  — every regime transition
```

## License

MIT
