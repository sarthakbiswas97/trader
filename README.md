# Autonomous Trading Agent

An ML-powered autonomous trading agent for Indian equity markets using Zerodha Kite Connect.

## Overview

```
Market Data → Feature Engineering → ML Prediction → Risk Check → Execute Trade
     ↑                                                              ↓
     └──────────────────── Monitor & Exit ←─────────────────────────┘
```

## Features

- **Real-time trading** via Zerodha Kite Connect API
- **ML-based signals** using XGBoost with 17 technical features
- **Paper trading mode** for safe testing with real market data
- **Risk management** with position limits, daily loss limits, and circuit breakers
- **Multi-timeframe analysis** (5-min, hourly, daily)

## Tech Stack

| Component | Technology |
|-----------|------------|
| Backend | Python, FastAPI |
| ML | XGBoost, SHAP |
| Broker | Zerodha Kite Connect |
| Database | PostgreSQL, Redis |
| Frontend | Next.js (planned) |

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Configure credentials
cp .env.example .env
# Edit .env with your Kite API key and secret

# Authenticate with Zerodha (daily)
python scripts/auth.py

# Download historical data
python scripts/download_data.py --test
```

## Project Structure

```
trader/
├── backend/
│   ├── broker/       # Zerodha & Paper trading
│   ├── services/     # Market data, features, execution
│   ├── agent/        # Trading strategy
│   ├── ml/           # Model training & inference
│   └── core/         # Logging, exceptions
├── scripts/          # CLI tools
├── data/             # Historical data
└── frontend/         # Dashboard (planned)
```

## Trading Strategy

**Entry**: ML confidence ≥60% + ADX >25 + Volume confirmation + Multi-TF alignment

**Exit**: Stop-loss (ATR-based) | Take-profit (2%) | Signal reversal | Market close

## Risk Limits

| Rule | Limit |
|------|-------|
| Position size | 5% of capital |
| Total exposure | 20% |
| Daily loss | 3% |
| Max drawdown | 10% |

## License

MIT
