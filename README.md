# Autonomous Trading System

An ML-powered trading system for Indian equity markets (NIFTY 100) using Zerodha Kite Connect. Built through systematic research — testing 6+ strategies across 4 years of data to find a validated edge.

## How It Works

```
                    ┌─────────────────────────┐
                    │     MARKET REGIME GATE   │
                    │  NIFTY < -0.5% → BLOCK  │
                    │  Breadth weak → BLOCK    │
                    │  5d decline > 3% → BLOCK │
                    └──────────┬──────────────┘
                               │ Market OK?
                               ▼
                    ┌─────────────────────────┐
                    │   DAILY REVERSAL SIGNAL  │
                    │                         │
                    │  Rank NIFTY 100 stocks  │
                    │  by 5d + 10d + 21d      │
                    │  past returns           │
                    │                         │
                    │  Buy top 10 biggest     │
                    │  recent losers          │
                    └──────────┬──────────────┘
                               │
                    ┌──────────┴──────────────┐
                    │                         │
              ┌─────┴─────┐           ┌───────┴───────┐
              │   SWING   │           │   INTRADAY    │
              │   (CNC)   │           │   (MIS)       │
              │           │           │               │
              │ Hold 5    │           │ VWAP cross or │
              │ trading   │           │ OR low hold   │
              │ days      │           │ confirmation  │
              │           │           │               │
              │ Rebalance │           │ Exit same day │
              │ weekly    │           │ or convert    │
              └───────────┘           │ to CNC        │
                                      └───────────────┘
                               │
                    ┌──────────┴──────────────┐
                    │      KILL SWITCH        │
                    │                         │
                    │  Rolling 20-trade       │
                    │  win rate < 50%         │
                    │  → Pause all trading    │
                    └─────────────────────────┘
```

## The Edge (Validated)

**Short-term reversal in Indian large-cap equities:** Stocks that fell the most over the past 5-21 days tend to bounce back over the next 5 days.

| Metric | Value |
|--------|-------|
| Signal | Daily reversal factor |
| IC (Information Coefficient) | +0.029 (t-stat = 5.0) |
| Universe | NIFTY 100 (96 stocks) |
| Holding period | 5 trading days |
| Backtest return (4 years) | +60% total (~12.5% CAGR) |
| Win rate | 59% |
| Max drawdown | 27.6% (17.6% with kill switch) |
| Years profitable | 4 out of 5 (80%) |

## Research Journey

We tested 6+ strategies before finding this edge. Each failure taught us something:

```
Strategy                   Trades   P&L        PF     Why It Failed
─────────────────────────────────────────────────────────────────────
1. ML Prediction (5-min)   1,635   -₹6,088    0.29   No signal in features
2. Breakout (5-min)          200   -₹1,684    0.42   Fakeouts, no follow-through
3. Breakout + Regime          22     -₹128    0.69   Too few trades
4. Mean Reversion (5-min)  1,064   -₹8,693    0.10   Signal too weak after costs
5. Trend Following (30-min)  405   -₹4,011    0.32   No intraday trend persistence
6. Cross-Sectional ML     831K rows  IC≈0       —     Features have no intraday signal

✅ Daily Reversal (5-day)    187   +₹60,337   1.60   WORKS — structural market effect
```

### Key Discovery

```
 Intraday (5-min candles)          Daily (holding 5 days)
┌─────────────────────────┐    ┌─────────────────────────┐
│                         │    │                         │
│  IC ≈ 0 (no signal)    │    │  IC = +0.029 (signal!)  │
│  Every strategy loses   │    │  4/5 years profitable   │
│  Costs eat any edge     │    │  Costs are negligible   │
│                         │    │                         │
│  DEAD ZONE for retail   │    │  VIABLE for retail      │
│                         │    │                         │
└─────────────────────────┘    └─────────────────────────┘
```

**Why intraday failed:** Indian large-cap stocks are too efficient at 5-min resolution. Price-derived features (RSI, MACD, breakout patterns) are already arbitraged by institutions and HFT. The signal-to-noise ratio is too low to overcome transaction costs.

**Why daily works:** Short-term reversal is a structural behavioral effect — stocks that fall hard attract value buyers, leading to a 5-day bounce. This effect has been documented academically and persists because it's driven by human psychology, not arbitrageable patterns.

## Performance by Market Regime

The reversal signal works across all market conditions, but absolute returns depend on regime:

```
Regime      IC        Years          P&L        Behavior
────────────────────────────────────────────────────────────
Bull      +0.020    2022-2024    +₹55,000    Buy dips → strong bounces
Bear      +0.055    2026 (Q1)   -₹17,000    Buy dips → still falling
Sideways  +0.031    Mixed        +₹8,000    Moderate bounces

Key: IC is HIGHEST in bear markets (0.055) — the signal is strongest
when fear is highest. But absolute returns are negative because even
the "best" dips continue falling in a crash.

Solution: Market regime gate blocks entries when NIFTY falls > 0.5%
```

## Walk-Forward Validation (Unseen Data)

Each year tested independently — the system was never tuned on this data:

```
Year    P&L         Win Rate    Max DD     IC        Status
──────────────────────────────────────────────────────────────
2022   +₹14,872      59%        7.8%    +0.052     ✓ Profitable
2023   +₹49,647      75%        9.6%    +0.055     ✓ Profitable
2024   +₹14,134      58%       17.7%    +0.011     ✓ Profitable
2025   +₹24,655      49%        8.1%    +0.045     ✓ Profitable
2026   -₹17,291      14%       20.8%    -0.110     ✗ Bear market

Consistency: 4/5 years profitable (80%)
```

## Quick Start

```bash
# Install everything
make install

# Authenticate with Zerodha (daily, before 9:15 AM)
make auth

# Run daily reversal strategy (after 9:30 AM)
make reversal

# Check current status
make reversal-status

# Run intraday entry filter on reversal picks
make intraday-scan

# Reset all state (fresh start)
make reversal-reset
```

## Project Structure

```
trader/
├── backend/
│   ├── strategies/
│   │   ├── daily_momentum/    # ✅ Active: reversal + pseudo trading
│   │   ├── breakout/          # ✗ Tested, not viable for intraday
│   │   ├── mean_reversion/    # ✗ Tested, signal too weak
│   │   ├── trend_30m/         # ✗ Tested, no follow-through
│   │   └── cross_sectional/   # ✗ Tested, IC ≈ 0 intraday
│   ├── broker/                # Zerodha + Paper trading
│   ├── services/              # Backtester, execution engine
│   ├── ml/                    # XGBoost, LightGBM models
│   ├── api/                   # FastAPI backend (22 endpoints)
│   ├── core/                  # Symbols, indicators, logging
│   ├── scripts/               # CLI tools
│   └── data/                  # Historical data + reports
├── frontend/                  # Next.js dashboard
├── Makefile                   # All commands
└── .env                       # Zerodha credentials
```

## Available Commands

```bash
make install          # Setup backend + frontend
make dev              # Start backend + frontend servers
make auth             # Zerodha OAuth login
make reversal         # Run daily reversal cycle
make reversal-status  # Check portfolio status
make reversal-reset   # Reset state
make intraday-scan    # Scan for intraday entries
make intraday         # Continuous intraday monitoring
make backtest         # Run backtester
make backtest-compare # Compare long-only vs long-short
make robustness       # Rolling window validation
make sweep            # TP/SL parameter sweep
make train            # Train ML model
make download         # Download historical data
```

## Tech Stack

| Component | Technology |
|-----------|------------|
| Backend | Python 3.13, FastAPI |
| ML | XGBoost, LightGBM, scipy |
| Broker | Zerodha Kite Connect |
| Frontend | Next.js, Tailwind, shadcn/ui |
| Data | 5yr daily + 200d 5-min for 96 stocks |

## Risk Management

| Rule | Value |
|------|-------|
| Market regime gate | NIFTY < -0.5% → no trades |
| Kill switch | Rolling WR < 50% → pause |
| Position size | 5% of capital per stock |
| Portfolio | Max 10 stocks at a time |
| Holding | 5 trading days (rebalance weekly) |

## License

MIT
